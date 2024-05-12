import json
import os
import time
from threading import Thread

import openai
import litellm
from typing import Union, List, Dict, Optional

from src.exceptions.cost_limit_exception import CostLimitException
from src.llm.response import Response
from src.llm.stream.streamed_response_builder import stream_chunk_builder
from src.collections.cache_llm_collection import CacheLLMCollection
from src.slack_message.slack_message import SlackMessage
from src.slack_message.streaming_slack_callback_handler import StreamingSlackCallbackHandler
from src.utils.env_util import cfg
import concurrent.futures
from src.exceptions.stopped_by_user_exception import StoppedByUserException
from litellm.exceptions import APIError

import logging
from src.utils.setup_logging import setup_logging
logger = setup_logging(__file__, logging.DEBUG)
db = os.environ.get('MONGO_DB')
empty_response_error = "AnthropicException - No content in response. Handle with `litellm.APIError`."

class OpenAIWrapper:
    def __init__(
            self,
            initial_timeout: int = 120,
            num_retries: int = 3,
            timeout_to_latency_ratio: float = 10.0,
            retry_increment: float = 2.0,
            caching: bool = True,
            cache_ttl: int = 60 * 60 * 24 * 30,
            stream: bool = False,
            slack_message_to_stream_to: Optional[SlackMessage] = None,
            costs_limit=cfg['llm']['cost_limit'],
    ):
        self.headers = {"Authorization": f"Bearer {openai.api_key}", "Content-Type": "application/json"}
        self.timeout = initial_timeout  # Initial timeout for requests
        self.mean_latency = 0  # Average response time
        self.latencies = []  # List to store latencies
        self.timeout_to_latency_ratio = timeout_to_latency_ratio  # Ratio to calculate timeout based on mean latency
        self.retry_increment = retry_increment  # Multiplier to increase timeout after each retry
        self.caching = caching  # Enable or disable caching
        self.cache_ttl = cache_ttl  # Time-to-live for cache entries
        self.num_retries = num_retries  # Number of retries before failing
        self.stream = stream
        self.slack_message_to_stream_to = slack_message_to_stream_to
        self.cost_limit = costs_limit

        # init cache
        self.cache = CacheLLMCollection(db_name=db, collection_name=cfg['mongo']['collections']['cache_llm'], ttl=self.cache_ttl)

    def completion(self, model: str, messages: Union[List[Dict], List[List[Dict]]], batch_size: int = 8,
                   mock: bool = False, current_cost: float = 0., prefill: str = None, **kwargs):
        # Check if messages contain batches or single completion
        if all(isinstance(i, list) for i in messages):  # Handling batches
            return self._batch_completion(model, messages, batch_size, mock, current_cost, prefill, **kwargs)
        else:  # Handling single completion
            return self._create_single_completion(model, messages, mock, current_cost, prefill, **kwargs)

    def _batch_completion(self, model: str, messages: List[List[Dict]], batch_size: int, mock: bool = False, current_cost: float = 0., prefill: str = None, **kwargs):
        responses = []
        for i in range(0, len(messages), batch_size):
            with concurrent.futures.ThreadPoolExecutor(max_workers=batch_size) as executor:
                batch = messages[i:i + batch_size]
                futures = [executor.submit(self._create_single_completion, model, single_message, mock, current_cost, prefill, **kwargs) for
                           single_message in batch]
                for future in futures:
                    responses.append(future.result())
        return responses

    def _create_single_completion(self, model: str, messages: List[Dict], mock: bool = False, current_cost: float = 0., prefill: str = None, **kwargs):
            
        # make sure function args in all messages are string
        for message in messages:
            if 'tool_calls' in message:
                for tool_call in message['tool_calls']:
                    if tool_call['type'] == 'function' and type(tool_call['function']['arguments']) != str:
                        tool_call['function']['arguments'] = json.dumps(tool_call['function']['arguments'])

            if 'role' in message and message['role'] == 'tool' and 'content' in message and type(message['content']) == dict:
                try:
                    message['content'] = json.dumps(message['content'])
                except:
                    logger.warning(f"Failed to convert message content to string. Trying with str()")
                    message['content'] = str(message['content'])

        # remove stopped by user information
        messages = list(map(lambda d: {k: v for k, v in d.items() if k != 'generation_stopped'} , messages))
    
        prompt_tokens = litellm.token_counter(model=model, text=str(messages))
        completion_tokens = kwargs.get('max_tokens')
        total_tokens = prompt_tokens + completion_tokens
        max_cost = litellm.cost_per_token(model, completion_tokens, prompt_tokens)
        logger.info(f"Current turn cost: {current_cost}")

        if self.cost_limit < sum(max_cost) + current_cost:
            raise CostLimitException(f"LLM could exceed cost limit ({self.cost_limit}) with this response by {(sum(max_cost) + current_cost - self.cost_limit)}, stopping completion")

        # In mocking mode, just calculate tokens and return
        if mock:
            try:
                created = int(time.time() * 1000)
                result = {
                    'id': str(created),
                    'object': 'chat.completion',
                    'created': created,
                    'model': model,
                    'choices': [{'index': 0,
                                 'message': {'role': 'assistant',
                                             'content': 'SEP' * completion_tokens, },
                                 'finish_reason': 'stop'}],
                    'usage':
                        {'prompt_tokens': prompt_tokens,
                         'completion_tokens': completion_tokens if completion_tokens is not None else 300,
                         'total_tokens': total_tokens}}

                logger.debug(
                    f"Mocked response. Prompt tokens: {prompt_tokens}, completion tokens: {completion_tokens}, total tokens: {total_tokens}")
                return result
            except:
                logger.exception("Failed to mock response")
                raise


        url = "https://api.openai.com/v1/chat/completions"
        payload = {
            "model": model,
            "messages": messages,
            **kwargs
        }

        try:
            if self.caching:  # Check if response is in cache
                response = self.cache.get(payload)
                if response is not None:
                    logger.debug(f"Response found in cache, returning cached response")
                    response['from_cache'] = True
                    return response
                else:
                    logger.debug(f"Response not found in cache, making API request. Timeout: {round(self.timeout, 2)}")

        except Exception:
            logger.exception("Failed caching")

        if self.stream:
            streamed_chunks = []
            streamed_text = ""
            tool_text = "\n🛠️ Gearing up the tools...\n"
            stream_callback = None

        try:
            start_time = time.time()  # Start time of the single request
            try:
                response = self._complete(
                    model=model,
                    messages=messages,
                    **kwargs
                )
            except APIError as e:
                # One retry for LLM providing empty response
                if e.message != empty_response_error:
                    raise e
                logger.info(f"Empty response from LLM handled. Adding synthetic message and attempting another LLM call")
                retry_message = [{"role": "user",
                                  "content": "<system>You responded with empty message. Re-read the recent conversation and respond properly to continue helping user</system>"}] if 'claude' in model else [
                    {"role": "system",
                     "content": "You responded with empty message. Re-read the recent conversation and respond properly to continue helping user"}]

                response = self._complete(
                    model=model,
                    messages=messages + retry_message,
                    **kwargs
                )
            
            if self.stream:
                if self.slack_message_to_stream_to:
                    stream_callback = StreamingSlackCallbackHandler(self.slack_message_to_stream_to)
                for chunk in response:
                    delta = chunk.choices[0].delta.dict()
                    print(f"Delta: {json.dumps(delta, indent=2)}")

                    # Tool calls
                    if delta.get('tool_calls') and not delta.get('content'):
                        streamed_text = tool_text

                        if stream_callback:
                            stream_callback.on_llm_new_token(token="", complete_text=streamed_text)

                    else:
                        token = delta.get('content', "")
                        if token:
                            streamed_text += token
                            if stream_callback:
                                stream_callback.on_llm_new_token(token)

                    streamed_chunks.append(chunk)

                response = stream_chunk_builder(streamed_chunks, messages=messages, tools=kwargs.get('tools'))

            end_time = time.time()  # End time of the single request

            # Calculate and store latency for the single request
            latency = end_time - start_time
            logger.debug(f"API request took {latency} seconds")
            self._update_latency_and_timeout([latency])

            result = response.json()

            # inject prefilled content into the result
            if prefill:
                if result.get('choices', [{}])[0].get('message', {}).get('role') == 'assistant':
                    if result['choices'][0]['message'].get('content'):
                        result['choices'][0]['message']['content'] = prefill + result['choices'][0]['message']['content']

            if self.caching:
                logger.info("Caching response")
                thread = Thread(target=self._update_cache, args=(payload, result), kwargs={'latency': latency})
                thread.start()

            return result
        
        except (KeyboardInterrupt, StoppedByUserException) as e:
            logger.info("Stopping generation because - user clicked stop button")
            end_time = time.time()
            result = None
            if self.stream:
                if streamed_text != tool_text:
                    if isinstance(response, litellm.CustomStreamWrapper):
                        response.completion_stream.close()
                        if streamed_chunks:
                            response = stream_chunk_builder(streamed_chunks, messages=messages, tools=kwargs.get('tools'))
                    if response:
                        result = response.json()
                if self.caching:
                   latency = end_time - start_time
                   self._update_cache(payload, result, latency=latency, generation_stopped=True)
            if isinstance(e, StoppedByUserException):
                raise StoppedByUserException(result=result)
            if isinstance(e, KeyboardInterrupt):
                raise e
        except Exception as e:
            logger.exception(f"Request failed: Payload: \n{json.dumps(payload, indent=2)}")
            # # Increase timeout for the next retry
            # self.timeout *= self.retry_increment
             
            # Raisean exception in case of empty response from LLM persisting
            if hasattr(e, 'message'):
                if e.message == empty_response_error:
                    logger.exception(f"Empty response from LLM persisted. Raising exception.")
                    raise e
            
            # Return a response with an error message instead of raising an exception

            created = int(time.time() * 1000)   
            error_message = f"I'm sorry, but it seems there was an issue with your message. I received the following error from the LLM: `{str(e)[:1000]}`"
                
           
            result = {
                'id': str(created),
                'object': 'chat.completion',
                'created': created,
                'model': model,
                'choices': [{'index': 0,
                             'message': {'role': 'assistant',
                                         'content': error_message},
                             'finish_reason': 'stop'}],
                'usage':
                    {'prompt_tokens': 0,
                     'completion_tokens': 0,
                     'total_tokens': 0}}
            
            logger.warning(f"Returning error response (likely 400 from OpenAI): {result}")
            
            return result

    def _complete(self, model, messages, **kwargs):
        result = litellm.completion(
            model=model,
            messages=messages,
            **kwargs,
            stream=self.stream,
            request_timeout=self.timeout,
            num_retries=self.num_retries,
        )
        logger.debug(f"Completion successful with model: {result.get('model', None)}")

        return result


    def _update_cache(self, payload, result, latency=None, generation_stopped=False):
        cost = Response(result).cost if result else 0
        meta = {
            "cost": cost,
            "generation_stopped": generation_stopped,
            **self.headers,
        }
        if latency is not None:
            meta["latency"] = latency
        self.cache.set(payload, meta, result)
        logger.debug(f"Response with code 200 cached")

    def _update_latency_and_timeout(self, latencies: List[float]):
        self.latencies += latencies
        logger.debug(f"Added latencies with mean {sum(latencies) / len(latencies)}")

        self.mean_latency = sum(self.latencies) / len(self.latencies)
        logger.debug(f"New total mean latency: {self.mean_latency}. Old timeout: {self.timeout}")

        # Update timeout based on the new mean latency
        self.timeout = self.mean_latency * self.timeout_to_latency_ratio
        logger.debug(f"New timeout: {self.timeout}")

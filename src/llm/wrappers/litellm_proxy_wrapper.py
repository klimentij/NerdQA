import json
import os
import time
import requests
from threading import Thread
from typing import Union, List, Dict, Optional

from src.llm.response import Response
from src.util.env_util import cfg, litellm_cfg
from src.db.cache_llm import CacheLLM

from src.util.setup_logging import setup_logging
logger = setup_logging(__file__, 'INFO')

class LiteLLMProxyWrapper:
    def __init__(
            self,
            caching: bool = False,
            stream: bool = False,
    ):
        self.headers = {"Authorization": f"Bearer {litellm_cfg['general_settings']['master_key']}", "Content-Type": "application/json"}
        self.caching = caching  # Enable or disable caching
        self.stream = stream
        
        # init cache
        self.cache = CacheLLM()

    def completion(self, model: str, messages: List[Dict], mock: bool = False, current_cost: float = 0., prefill: str = None, **kwargs):
            
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
                    logger.debug(f"Response not found in cache, making API request")

        except Exception:
            logger.exception("Failed caching")


        start_time = time.time()  # Start time of the single request
        response = self._complete(
            model=model,
            messages=messages,
            **kwargs
        )
        
        end_time = time.time()  # End time of the single request

        # Calculate and store latency for the single request
        latency = end_time - start_time
        logger.debug(f"API request took {latency} seconds")
        result = response.json()

        # inject prefilled content into the result
        if prefill:
            if result.get('choices', [{}])[0].get('message', {}).get('role') == 'assistant':
                if result['choices'][0]['message'].get('content'):
                    result['choices'][0]['message']['content'] = prefill + result['choices'][0]['message']['content']

        if self.caching:
            logger.info("Caching response")
            # thread = Thread(target=self._update_cache, args=(payload, result), kwargs={'latency': latency})
            # thread.start()
            self._update_cache(payload, result, latency=latency)

        return result
        

    def _complete(self, model, messages, **kwargs):

        url = f"{cfg['api']['llm']['base']}/chat/completions"
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f"Bearer {litellm_cfg['general_settings']['master_key']}"
        }
        data = {
            "model": model,
            "messages": messages,
        }
        data.update(kwargs)

        logger.debug(f"Making API request to {url}. \n\nData: {json.dumps(data, indent=2)}")
        result = requests.post(url, headers=headers, json=data)
        return result


    def _update_cache(self, payload, result, latency=None):
        cost = Response(result).cost if result else 0
        meta = {
            "cost": cost,
            **self.headers,
        }
        if latency is not None:
            meta["latency"] = latency
        self.cache.set(payload, meta, result)
        logger.debug(f"Response with code 200 cached")


import json

import litellm

from src.utils.kb_utils import turns_collection

import logging
from src.utils.setup_logging import setup_logging
logger = setup_logging(__file__, logging.DEBUG)
class Response:
    def __init__(self, response: dict, prompt: str = '', indexed_turn_id: str = None, indexed_turn_ts=None,
                 observability_tool_properties: dict = None):
        logger.debug("Response object created, see llm.Completion -> \"Response from self.llm.completion\" "
                     "log message for more info")
        # Set the text of the response
        self.content = self._get_content_from_response(response)

        # Set additional attributes
        self.response = response
        self.tool_calls = None
        self.prompt = prompt
        self.indexed_turn_id = indexed_turn_id
        self.indexed_turn_ts = indexed_turn_ts

        if observability_tool_properties:
            self.observability_tool_properties = observability_tool_properties
        else:
            self.observability_tool_properties = {}

        # Set the cost of the response
        # Cached are free
        if response.get('from_cache'):
            self.cost = 0
        else:
            self.cost = self._get_cost()

        if response.get('choices', [])[0].get('message', {}).get('tool_calls', []):
            # and response.get('choices', [])[0].get('finish_reason') == 'tool_calls':
            self.tool_calls = response['choices'][0]['message']['tool_calls']

            # try parsing tool call arguments
            for tool_call in self.tool_calls:
                try:
                    if type(tool_call['function']['arguments']) == str:
                        tool_call['function']['arguments'] = json.loads(tool_call['function']['arguments'],
                                                                        strict=False)
                except:
                    logger.warning(
                        f"Failed to parse tool call arguments: {tool_call['function']['arguments']} with type {type(tool_call['function']['arguments'])}. Leaving as string.")

    def __str__(self):
        # When the object is converted to a string, return the text of the response
        return '' if self.content is None else self.content

    def _get_cost(self):
        try:
            prompt_tokens = self.response.get('usage', {}).get('prompt_tokens', None)
            completion_tokens = self.response.get('usage', {}).get('completion_tokens', None)
            if prompt_tokens is None or completion_tokens is None:
                logger.warning(f"Failed to get cost for response")
                return 0
            else:
                return sum(litellm.cost_per_token(
                    model=self.response['model'],
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens
                ))
        except:
            logger.exception(f"Failed to get cost for response")
            return 0

    def _get_content_from_response(self, response):
        if not isinstance(response, dict):
            logger.error(f"Unexpected type {type(response)} for response: {response}")
            return None
        try:
            return response['choices'][0]['message']['content']
        except (KeyError, IndexError, TypeError) as e:
            logger.error(f"Failed to get content from response: {e}")
            return None

    def update_message_in_db(self):
        """
        To handle a (very special) case when we artificially modify LLM's message that was already indexed.
        E.g. when we inject an artificial tool call to a list of tool calls.
        Important: for now we don't re-calculate embeddings for the modified message, we just update the content.
        """
        if self.indexed_turn_id:
            try:
                message = self.response.get('choices', [])[0].get('message', {})

                # force update tool calls in response
                if self.tool_calls:
                    message['tool_calls'] = self.tool_calls

                turns_collection.update_single_message(self.indexed_turn_id, message)
                logger.debug(f"Updated message in DB with id: {self.indexed_turn_id}")
            except:
                logger.exception(f"Failed to update message in DB with id: {self.indexed_turn_id}")

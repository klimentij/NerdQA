import inspect
from threading import Thread
from typing import Union, List, Dict, Optional, Tuple
import os
import re
import yaml
import litellm

import time
import json

import pandas as pd
from tenacity import RetryError

from src.exceptions.cost_limit_exception import CostLimitException
from src.exceptions.stopped_by_user_exception import StoppedByUserException
from src.llm.response import Response
from src.llm.trim import Trim, TrimType
from src.llm.wrappers.ligth_llm_wrapper import LiteLLMWrapper
from src.llm.wrappers.openai_wrapper import OpenAIWrapper
from src.llm.tokenizer import VdTokenizer
from src.turns.turns_history import TurnsHistory

os.chdir(__file__.split('src/')[0])
import sys
sys.path.append(os.getcwd())

from src.utils.env_util import cfg
from src.utils.kb_utils import turns_collection
from src.slack_message.slack_message import SlackMessage
from langchain.schema import Document



# Set up logger
import logging
from src.utils.setup_logging import setup_logging
logger = setup_logging(__file__, logging.INFO)


class Completion:
    """
    A class to handle completions using the OpenAI API.

    Attributes
    ----------
    model : str
        The model to use for the completion.
    completion_kwargs : dict
        Additional arguments for the completion.
    observability_tool : str
        The observability tool to use.
    observability_tool_kwargs : dict
        Additional arguments for the observability tool.
    observability_tool_properties : dict
        Properties for the observability tool.
    all_skills_path : str
        The path to the skills.
    observability_tool_auth_key : str
        The authentication key for the observability tool.
    api_base : str
        The base URL for the API.
    """
    
    def __init__(self,
                 skill: Tuple[str],
                 prompt_inputs_fixed: Optional[Dict] = None,
                 messages: Optional[List[Dict]] = None,
                 completion_kwargs: Optional[Dict] = None,
                 observability_tool: Optional[str] = 'Vd',
                 observability_tool_kwargs: Optional[Dict] = None,
                 observability_tool_properties: Optional[Dict] = None,
                 observability_tool_auth_key: Optional[str] = os.environ.get('HELICONE_AUTH_KEY'),
                 observability_tool_inputs_as_properties: Optional[List[str]] = None,
                 tools: Optional[List[Dict]] = None,
                 all_skills_path: Optional[str] = cfg['all_skills_path'],
                 api_base: str = cfg['observability_tool']['api_base'],
                 trim: Optional[List[Trim]] = None,
                 trim_just_in_case_tokens: Optional[int] = 100,
                 llm_wrapper: Optional[Union[LiteLLMWrapper, OpenAIWrapper]] = OpenAIWrapper,
                 channel_id: Optional[str] = None,
                 user_id: Optional[str] = None,
                 initial_timeout: int = 100,
                 num_retries: int = 3,
                 stream: bool = False,
                 slack_message_to_stream_to: Optional[SlackMessage] = None,
                 log_level: int = logging.DEBUG,
                 costs_limit: int = cfg['llm']['cost_limit'],
                 current_cost: float = 0.,
                 async_processing: bool = False,
                 completion_model: str = None
                 ):
        """
        Initializes the Completion class.

        It is recommended to use this class with a skill. If a skill is provided,
        the 'complete' method only requires 'prompt_inputs'. If no skill is provided,
        'complete' requires 'messages'.
        """
        
        # Handle mutable default arguments
        if prompt_inputs_fixed is None:
            prompt_inputs_fixed = {}
        if messages is None:
            messages = []
        if completion_kwargs is None:
            completion_kwargs = {}
        if observability_tool_kwargs is None:
            observability_tool_kwargs = {}
        if observability_tool_properties is None:
            observability_tool_properties = {}
        if observability_tool_inputs_as_properties is None:
            observability_tool_inputs_as_properties = []
        if tools is None:
            tools = []
        if trim is None:
            trim = []

        # Set the attributes
        self.skill = skill
        self.prompt_inputs_fixed = prompt_inputs_fixed
        self.messages = messages
        self.completion_kwargs = completion_kwargs
        self.observability_tool = observability_tool
        self.observability_tool_kwargs = observability_tool_kwargs
        self.observability_tool_properties = observability_tool_properties
        self.observability_tool_auth_key = observability_tool_auth_key
        self.observability_tool_inputs_as_properties = observability_tool_inputs_as_properties
        self.tools = tools
        self.all_skills_path = all_skills_path
        self.api_base = api_base
        self.trim = trim
        self.trim_just_in_case_tokens = trim_just_in_case_tokens
        self.llm_wrapper = llm_wrapper
        self.channel_id = channel_id
        self.user_id = user_id
        self.initial_timeout = initial_timeout
        self.num_retries = num_retries
        self.stream = stream
        self.slack_message_to_stream_to = slack_message_to_stream_to
        self.doc_placeholders = []

        self.prefill = None
        self.prompt_placeholders = []
        self.model_info = {}

        self.costs_limit = costs_limit
        self.current_cost = current_cost
        self.async_processing = async_processing
        self.completion_model = completion_model

        logger.user_id = user_id
        logger.turn_id = channel_id
        logger.setLevel(log_level)

        # default caching is True, can be overwritten by skill config
        self.caching = True 

        self._load_skill(self.skill)

        if llm_wrapper == LiteLLMWrapper:
            self.llm = LiteLLMWrapper()
            self.llm.headers = {
                    f"{observability_tool}-Auth": "Bearer " + self.observability_tool_auth_key,
                    f"{observability_tool}-User-Id": cfg['observability_tool']['default_user_id'],
                    f"{observability_tool}-Cache-Enabled": "true",
                    }    
            self.llm.api_base = api_base

        else:
            self.llm = OpenAIWrapper(
                initial_timeout=self.initial_timeout,
                num_retries=self.num_retries,
                caching=self.caching,
                stream=self.stream,
                slack_message_to_stream_to=self.slack_message_to_stream_to,
                costs_limit=self.costs_limit
                )
        
        self._set_headers()
        self.total_cost = 0

        self._validate()
    
    def _validate(self):
        # Validate trims: 
        """
        limit = llm_context_length
            - trim_just_in_case_tokens
            - prompt_len
            - max_tokens

        1. All max_length must be <= limit
        2. A sum of min_lengths must <= limit
        """
        if self.trim:
            limit = self.llm_context_length \
                - self.trim_just_in_case_tokens \
                - self.prompt_len \
                - self.completion_kwargs['max_tokens']
            
            min_length_sum = sum([t.min_length for t in self.trim])
            if min_length_sum > limit:
                raise ValueError(f"Sum of trim min_lengths {min_length_sum} exceed limit of {limit} for the skill {self.skill}. Adjust trim min_lengths or completions parameters")
            
            for t in self.trim:
                if t.max_length is not None and t.max_length > limit:
                    raise ValueError(f"Trim {t.name} max_length {t.max_length} exceed limit of {limit} for the skill {self.skill}. Adjust trim max_lengths or completions parameters")
                

    def __call__(self, **kwargs):
        """Allows the class instance to be called directly."""
        return self.complete(**kwargs)

    def _load_skill(self, skill: Tuple[str]):
        """Loads the skill."""
        skill_path = os.path.join(self.all_skills_path, *skill)
        if not os.path.exists(skill_path):
            logger.error(f"Skill not found: {skill}")
            raise FileNotFoundError(f"Skill not found: {skill}")
        
        with open(os.path.join(skill_path, "config.yaml"), "r") as f:
            scfg = yaml.safe_load(f)
            self.skill_config = scfg
        
        with open(os.path.join(skill_path, "prompt.md"), "r") as f:
            self.prompt = f.read()

        # read input placeholders from prompt
        self.prompt_placeholders = re.findall(r'\{\{\$(.*?)\}\}', self.prompt)

        prefill_path = os.path.join(skill_path, "prefill.md")
        if os.path.exists(prefill_path):
            with open(prefill_path, "r") as f:
                self.prefill = f.read()

        if not self.tools and os.path.exists(os.path.join(skill_path, "tools.json")):
            with open(os.path.join(skill_path, "tools.json"), "r") as f:
                self.tools = json.load(f)
                self.completion_kwargs['tools'] = self.tools

        # Overwrite model for completion if present
        if self.completion_model:
            logger.debug(f"Model defined in skill config has been overwritten to: {self.completion_model}")
            self.skill_config['completion_kwargs']['model'] = self.completion_model

        try:
            self.completion_kwargs.update(self.skill_config.get("completion_kwargs", {}))
            self.observability_tool_kwargs.update(self.skill_config.get("observability_tool_kwargs", {}))
            self.observability_tool_properties.update(self.skill_config.get("observability_tool_properties", {}))
        except:
            logger.exception(f"Failed to update completion_kwargs, observability_tool_kwargs, observability_tool_properties from skill config")


        self.observability_tool_properties["Skill"] = "_".join(skill)
        self.model_info = litellm.get_model_info(scfg['completion_kwargs']['model'])
        self.llm_context_length = self.model_info.get('max_input_tokens', self.model_info.get('max_tokens', 32000))
        self.trim_limit_chars = self.llm_context_length * 6 # roughly the llm context length, to protect llm tokenizer from extremely long inputs
        self.tokenizer = VdTokenizer(scfg['completion_kwargs']['model'])
        self.prompt_len = len(self.tokenizer.encode(str(self.prompt)))
        self.trim_label = "[trimmed]"

        if scfg.get("caching") is not None:
            self.caching = scfg.get("caching")

        # If trimming is not overriden, use the skill config
        # which is like:
        """
        trims:
            - name: 'adjective'
            trim_type: 'START'
            min_length: 42
        """
        if not self.trim:
            self.trim = [Trim(**t) for t in scfg.get("trims", [])]


    def _process_prompt_inputs(self, prompt_inputs: Union[Dict, List[Dict]]) -> Union[List[Dict], List[List[Dict]]]:
        """
        Processes the prompt inputs and returns a list of messages.

        If a skill is provided, this method is used to process the 'prompt_inputs' into 'messages'.
        """
        if prompt_inputs is not None:
            if type(prompt_inputs) == dict:
                return self._single_input_to_messages(prompt_inputs)
            
            if type(prompt_inputs) == list:
                return [self._single_input_to_messages(i) for i in prompt_inputs]
            
    def _trim_prompt_inputs(self, prompt_inputs: Dict[str, str]) -> Dict[str, str]:
        """Trim the prompt inputs based on the trim dictionary."""
        
        for trim_obj in self.trim:
            if trim_obj.name in prompt_inputs:
                
                # if this trim_obj has max_length, trim the input to max_length anyway
                if trim_obj.max_length:
                    content = prompt_inputs[trim_obj.name]
                    tokens = self.tokenizer.encode(str(content))
                    excess_tokens = len(tokens) - trim_obj.max_length
                    if excess_tokens > 0:
                        logger.debug(f"Trimming {trim_obj.name} by {excess_tokens} tokens, trim type: {trim_obj.trim_type}, max length: {trim_obj.max_length}")
                        prompt_inputs[trim_obj.name] = self._trim_single_input_value(trim_obj, prompt_inputs, excess_tokens)

                prompt = self.prompt
                for k, v in prompt_inputs.items():
                    placeholder = '{{$'+k+'}}'
                    if placeholder in prompt:
                        prompt = prompt.replace(placeholder, str(v))
                    
                messages = self._parse_messages(prompt)
                total_tokens = litellm.token_counter(self.completion_kwargs['model'], messages=messages) \
                    + self.trim_just_in_case_tokens \
                    + self.completion_kwargs['max_tokens']
                
                excess_tokens = total_tokens - self.llm_context_length
                logger.debug(f"Total tokens: {total_tokens}, excess tokens: {excess_tokens}")
                if excess_tokens > 0:
                    logger.debug(f"Trimming {trim_obj.name} by {excess_tokens} tokens, trim type: {trim_obj.trim_type}, min length: {trim_obj.min_length}")
                    trimmed_content = self._trim_single_input_value(trim_obj, prompt_inputs, excess_tokens)
                    prompt_inputs[trim_obj.name] = trimmed_content

        return prompt_inputs

    def _trim_single_input_value(self, trim_obj: Trim, prompt_inputs: Dict[str, str], excess_tokens: int) -> str:
        """Trim the content by the specified number of tokens."""
        content = prompt_inputs[trim_obj.name]
        logger.debug(f"Content length in chars: {len(content)}")

        tokens = self.tokenizer.encode(str(content))
        logger.debug(f"Content length in tokens: {len(tokens)}")

        # Calculate the maximum number of tokens that can be trimmed without going below min_length
        max_tokens_to_trim = max(0, len(tokens) - trim_obj.min_length)
        tokens_to_trim = min(max_tokens_to_trim, excess_tokens)
        logger.debug(f"Trimming {tokens_to_trim} tokens")

        if trim_obj.trim_type == TrimType.START:
            content = self.trim_label + ".." + self.tokenizer.decode(tokens[tokens_to_trim:])
        elif trim_obj.trim_type == TrimType.END:
            content = self.tokenizer.decode(tokens[:-tokens_to_trim]) + ".." + self.trim_label
        elif trim_obj.trim_type == TrimType.MIDDLE:
            # Calculate the start and end points of the middle section to remove
            start_middle = (len(tokens) - tokens_to_trim) // 2
            end_middle = start_middle + tokens_to_trim
            # Concatenate the start and end tokens, skipping the middle section
            content = self.tokenizer.decode(tokens[:start_middle]) + f"..{self.trim_label}.." + self.tokenizer.decode(tokens[end_middle:])

        logger.debug(f"Content length in tokens after trimming: {len(self.tokenizer.encode(str(content)))}")
        return content


    def _single_input_to_messages(self, single_input: Dict) -> List[Dict]:
        """Converts a single input into a message."""

        # if any fixed inputs are provided, add them to the single input
        if self.prompt_inputs_fixed:
            single_input.update(self.prompt_inputs_fixed)

        # Protect llm tokenizer from extremely long inputs
        # by trimming as string to roughly the llm context length
        for k, v in single_input.items():
            if len(str(v)) > self.trim_limit_chars:
                # trim the value to the limit
                # but if there's a Trim created for this input
                # we have to check the Trim mode first

                # Try to find the Trim for this input
                trim_obj = next((t for t in self.trim if t.name == k), None)
                if trim_obj:
                    #calculate the excess length in chars to trim
                    excess_length = len(str(v)) - self.trim_limit_chars

                    # Trim found, trim the input
                    if trim_obj.trim_type == TrimType.START:
                        single_input[k] = self.trim_label + '..' + str(v)[excess_length:]
                    elif trim_obj.trim_type == TrimType.END:
                        single_input[k] = str(v)[:-excess_length] + '..' + self.trim_label
                    elif trim_obj.trim_type == TrimType.MIDDLE:
                        # Calculate the start and end points of the middle section to remove
                        start_middle = (len(str(v)) - excess_length) // 2
                        end_middle = start_middle + excess_length
                        # Concatenate the start and end tokens, skipping the middle section
                        single_input[k] = str(v)[:start_middle] + f"..{self.trim_label}.." + str(v)[end_middle:]

                else:
                    # Trim not found, trim the input from the end
                    single_input[k] = str(v)[:self.trim_limit_chars]

                logger.debug(f"Value of {k} is trimmed to {self.trim_limit_chars} chars")

        single_input = self._trim_prompt_inputs(single_input)
        prompt = self.prompt
        for k, v in single_input.items():
            placeholder = '{{$'+k+'}}'
            if placeholder in prompt:
                prompt = prompt.replace(placeholder, str(v))
            else:
                logger.warning(f"Placeholder {placeholder} not found in prompt")

        remaining_placeholders = re.findall(r'\{\{\$.*?\}\}', prompt)
        # Filter out any placeholders from doc
        if self.doc_placeholders:
            remaining_placeholders = [ph for ph in remaining_placeholders if ph not in self.doc_placeholders]

        if remaining_placeholders:
            error_message = f"Unfilled placeholders found: {', '.join(remaining_placeholders)}"
            logger.error(error_message)
            raise ValueError(error_message)
        
        # some inputs can be logger as properties in observability tool
        # override/add observability_tool_properties from inputs using self.observability_tool_inputs_as_properties
        if self.observability_tool_inputs_as_properties:
            for k in self.observability_tool_inputs_as_properties:
                if k in single_input:
                    self.observability_tool_properties[k] = single_input[k]
            self._set_headers()
            

        return self._parse_messages(prompt)
    
    def _parse_messages(self, prompt: str) -> List[Dict]:
        """Parse the messages from the text using roles in triple curly braces
        as delimiters. If no roles are found, assume it's a single user message."""

        # Split the text into blocks
        blocks = re.split(r'\{\{\{(\w+)\}\}\}', prompt)[1:]

        # If no roles found, assume it's a single user message
        if not blocks:
            return [{'role': 'user', 'content': prompt.strip()}]

        # Group the blocks by role and content
        messages = [{'role': blocks[i], 'content': blocks[i + 1].strip()} for i in range(0, len(blocks), 2)]

        return messages

    def _set_headers(self):
        """Sets the some special properties for the observability tool."""
        self.llm.headers[f"{self.observability_tool}-Property-Env"] = cfg['branch']

        # Get the filename of the script that's calling the Completion class
        calling_script = inspect.stack()[1].filename
        self.llm.headers[f"{self.observability_tool}-Property-App"] = calling_script.split('/')[-1].split('.')[0]

        # set observability tool properties
        for k, v in self.observability_tool_properties.items():
            self.llm.headers[f"{self.observability_tool}-Property-{k}"] = str(v)

        # set observability tool kwargs
        for k, v in self.observability_tool_kwargs.items():
            self.llm.headers[f"{self.observability_tool}-{k}"] = str(v)
    
    def _get_content_from_response(self, response: dict) -> str:
        """Gets the content from the response."""
        try:
            return response['choices'][0]['message']['content']
        except:
            logger.exception("Failed to get content from LLM response, possibly due to an error")
            return "Error"

    def index_messages(self, messages: List[Dict], cost: int = 0, turn_id=None, generation_stopped=False):
        try:
            timestamp = pd.Timestamp.now()

            if not turn_id:
                turn_id = self.observability_tool_properties.get('turn_id')
            turn = turns_collection.find_by_turn_id(turn_id)

            if turn:
                timestamp = turn.get('created_on')
                response = None
                if messages[-1].get("role") == "assistant":
                    response = messages[-1].get('content')

                turn_thread =  Thread(target=lambda: turns_collection.update_turn(turn_id=turn_id,
                                                                   messages=messages,
                                                                   response=response,
                                                                   total_cost=cost,
                                                                   generation_stopped=generation_stopped,
                                                                   tokenizer=self.tokenizer))
            else:
                user_id = self.llm.headers.get(f"{self.observability_tool}-Property-User-Id",
                            self.llm.headers.get(
                                f"{self.observability_tool}-Property-user_id",
                                self.user_id if self.user_id else 'unknown'))
                model = self.skill_config.get('completion_kwargs', {}).get('model', 'unknown')
                turn_thread = Thread(target=lambda: turns_collection.create_turn(messages=messages,
                                                                   user_id=user_id,
                                                                   turn_id=turn_id,
                                                                   channel_id=self.channel_id,
                                                                   generation_stopped=generation_stopped,
                                                                   cost=cost,
                                                                   created_on=timestamp,
                                                                   model=model,
                                                                   tokenizer=self.tokenizer))
            turn_thread.start()
            
            if not self.async_processing:
                turn_thread.join()
            # return ids of indexed messages
            return {"id": turn_id, "timestamp": timestamp}
        except StoppedByUserException as e:
            raise e
        except Exception as e:
            logger.exception(f"Failed to add messages to vector search: {e}")

    def _inject_system_to_assistant(self, messages: List[Dict]) -> List[Dict]:
        for i, message in enumerate(messages):
            if message.get('role') == 'system':
                injected_text = f"<system>{message.get('content')}</system>"
                try:
                    if messages[i-1].get('role') == 'assistant':
                        messages[i-1]['content'] += '\n' + injected_text
                    else:
                        raise
                except:
                    try:
                        if messages[i+1].get('role') == 'assistant':
                            messages[i+1]['content'] = injected_text + '\n' + messages[i+1]['content']
                    except:
                        pass
        
        glued = [message for message in messages if message.get('role') != 'system']
        return glued

    def _glue_multiple_assistant_in_a_row(self, messages: List[Dict]) -> List[Dict]:
        for i, message in enumerate(messages):
            if message.get('role') == 'assistant':
                try:
                    if messages[i+1].get('role') == 'assistant':
                        messages[i+1]['content'] = message.get('content') + '\n\n' + messages[i+1]['content']
                        messages[i]['delete'] = ''
                except:
                    pass

        glued = [message for message in messages if 'delete' not in message]
        return glued

    def _glue_multiple_user_in_a_row(self, messages: List[Dict]) -> List[Dict]:
        for i, message in enumerate(messages):
            if message.get('role') == 'user':
                try:
                    if messages[i+1].get('role') == 'user':
                        messages[i+1]['content'] = message.get('content') + '\n\n' + messages[i+1]['content']
                        messages[i]['delete'] = ''
                except:
                    pass

        glued = [message for message in messages if 'delete' not in message]
        return glued

    def _remove_repeated_chunks(self, messages: List[Dict]) -> List[Dict]:
        """
        Removes repeated occurrences of text chunks in a list of messages. 

        This function scans through each message in the list and identifies text chunks that are delineated by 
        a specific pattern (chunk_id). When a chunk that has already appeared in a previous message is found, 
        it replaces the entire chunk with a brief note indicating the chunk's ID and that it was omitted for brevity.
        """
        # Regex pattern to find chunks
        pattern = r"{\"chunk_id\": \"(\d+)\", &lt;DOCUMENT STARTS&gt;.*?&lt;DOCUMENT ENDS&gt;"
        found_chunks = set()

        # Process each message
        for i in range(len(messages)):
            # Find all chunks in the current message
            if messages[i].get('content') is None:
                continue
            current_chunks = re.findall(pattern, str(messages[i]["content"]), re.DOTALL)
            
            # Replace repeating occurrences of chunks
            for chunk_id in current_chunks:
                if chunk_id in found_chunks:
                    replacement_text = f"[chunk with chunk_id={chunk_id} was omitted for brevity as it was already shown above]"
                    messages[i]["content"] = re.sub(rf"\{{\"chunk_id\": \"{chunk_id}\", &lt;DOCUMENT STARTS&gt;.*?&lt;DOCUMENT ENDS&gt;", replacement_text, messages[i]["content"], flags=re.DOTALL)
                else:
                    found_chunks.add(chunk_id)
        return messages

    def heal_messages(self, messages: Union[List[Dict], List[List[Dict]]]) -> Union[List[Dict], List[List[Dict]]]:
        if messages is None:
            return []
        # if messages is a list of lists, heal each list separately
        if type(messages[0]) == list:
            healed_messages_batch = []
            for messages_list_of_dicts in messages:
                healed_messages_batch.append(self.heal_messages(messages_list_of_dicts))
            return healed_messages_batch

        ### All providers
        messages = self._remove_repeated_chunks(messages)
        # logger.debug(f"Removed repeated chunks from messages: {json.dumps(messages, indent=2)}")

        # remove first messages until the first one with role user
        # but keep system messages
        first_user_found = False
        new_messages = []
        for i, message in enumerate(messages):
            if message.get('role') == 'user':
                first_user_found = True
            if first_user_found or message.get('role') == 'system':
                new_messages.append(message)
        messages = new_messages
        # logger.debug(f"Removed first messages until the first one with role user: {json.dumps(messages, indent=2)}")

        ### Openai
        if self.model_info.get('litellm_provider','') == 'openai':  
            if 'stop_sequences' in self.completion_kwargs:
                self.completion_kwargs['stop'] = self.completion_kwargs.pop('stop_sequences')
        
        ### All providers - Post processing
        # remove the last assistant message if no pre-fill is provided
        if not self.prefill and messages and messages[-1].get('role') == 'assistant':
            messages = messages[:-1]
            logger.warning(f"Removed the last assistant message from the history as no pre-fill was provided")
            # logger.debug(f"Messages after removing the last assistant message: {json.dumps(messages, indent=2)}")

        msg_ids_allowed_tool_responses = set()
        tool_call_ids_to_fake = []
        tools_to_heal = []
        for i, message in enumerate(messages):
            allowed_tool_call_ids = set()
            if message.get('tool_calls', []):

                is_bad_tool_response = False
                for tool_call in message['tool_calls']:
                    allowed_tool_call_ids.add(tool_call['id'])
                    function = tool_call['function']

                    if function.get('name', None) == 'render_slack_response' and function['arguments'].get(
                            'text', None) is not None and message['content'] is not None:
                        is_bad_tool_response = True

                if allowed_tool_call_ids:
                    # take next messages with role tool until first non-tool message
                    for j in range(i+1, len(messages)):
                        next_message = messages[j]
                        if next_message.get('role') == 'tool':
                            if next_message.get('tool_call_id') in allowed_tool_call_ids:
                                # remove this tool_call_id from allowed_tool_call_ids as its tool call is found
                                allowed_tool_call_ids.discard(next_message['tool_call_id'])
                                msg_ids_allowed_tool_responses.add(j)
                        else:
                            break

                    # if there are still unfulfilled tool calls, add fake tool responses
                    if allowed_tool_call_ids:
                        tools_to_heal.append(i)
                        tool_call_ids_to_fake.extend(list(allowed_tool_call_ids))

        if tool_call_ids_to_fake:
            logger.info(f"Found {len(tool_call_ids_to_fake)} unfulfilled tool calls in the history, adding fake tool responses")

        healed_messages = []
        healed_to_fill = []
        for i, message in enumerate(messages):
            if message.get('role') == 'tool':
                if i in msg_ids_allowed_tool_responses:
                    healed_messages.append(message)
            else:
                healed_messages.append(message)
                if i in tools_to_heal:
                    healed_to_fill.append(len(healed_messages) - 1)

        if len(healed_messages) != len(messages):
            logger.info(f"Removed {len(messages) - len(healed_messages)} tool messages from the history as they didn't have preceding tool calls")

        # add fake tool responses
        healed_filled_messages = []
        if tool_call_ids_to_fake:
            for i, message in enumerate(healed_messages):
                healed_filled_messages.append(message)
                if message.get('role') == 'assistant' and i in healed_to_fill:
                    for tool_call in message.get('tool_calls', []):
                        if tool_call['id'] in tool_call_ids_to_fake:
                            if message.get("generation_stopped", False):
                                fake_tool_message = {
                                    "role": "tool",
                                    "tool_call_id": tool_call['id'],
                                    "name": "StoppedTool",
                                    "content": "User stopped you from responding after this tool was called. This is a fake tool response to avoid error messages"
                                }
                            else:
                                fake_tool_message = {
                                    "role": "tool",
                                    "tool_call_id": tool_call['id'],
                                    "name": "FakeTool",
                                    "content": "The conversation was interrupted after this tool was called. This is a fake tool response just to avoid error messages"
                                }
                            healed_filled_messages.append(fake_tool_message)
                            tool_call_ids_to_fake.remove(tool_call['id'])
        else:
            healed_filled_messages = healed_messages
        return healed_filled_messages
    
    def _get_history(self):
        try:
            start = time.time()
            if not self.channel_id:
                logger.warning(f"Channel_id not provided, returning empty history")
                return []
            
            if not self.skill_config.get('history', {}).get('token_limit'):
                logger.warning(f"History token_limit not provided in the skill config, returning empty history")
                return []


            tool_trim_config = self.skill_config.get('history', {}).get("tool_responses", {})
            turns_untrimmed = tool_trim_config.get('turns_untrimmed', 1)
            turns_gradual_trimming = tool_trim_config.get('turns_gradual_trimming', 5)
            token_limit_high = tool_trim_config.get('token_limit_high', 5000)
            token_limit_low = tool_trim_config.get('token_limit_low', 1000)

            cursor = turns_collection.get_turns(self.channel_id, self.skill_config.get('history', {}).get('turn_limit', 30))
            history = TurnsHistory(cursor, tokenizer=self.tokenizer)
            if len(history) == 0:
                logger.warn("No messages retrieved from history, returning empty list")
                return []

            st = time.time()
            history.trim_turns("tool_calls", turns_untrimmed=turns_untrimmed,
                                     gradual_trimming=turns_gradual_trimming,
                                     token_limit_high=token_limit_high,
                                     token_limit_low=token_limit_low)
            logger.debug(
                f"_get_history: Got messages from history, channel_id: {self.channel_id}, total tokens: {history.total_tokens}. Took {round(time.time() - st, 4)} seconds")

            messages = history.flatten_turns(self.skill_config['history']['token_limit'])

            logger.debug(f"Converted {len(messages)} messages from history to a list of message dicts, channel_id: {self.channel_id}, total tokens: {history.total_tokens}. Took {round(time.time() - start, 4)} seconds")
            return messages
        except Exception as e:
            logger.warning(f"Failed to get history for channel_id: {self.channel_id}, returning empty history. Error: {e}")
            return []
        

    def _check_cost_limit(self, turn_id):
        result = turns_collection.find_one({"turn_id": turn_id})

        if result is not None:
            if self.current_cost == 0:
                cost = result.get("usage", {}).get('total_cost', 0)
                self.current_cost = cost
            return self.costs_limit < self.current_cost
        else:
            return False


    def complete(
            self, 
            prompt_inputs: Optional[Union[Dict, List[Dict]]] = None, 
            messages: Optional[List[Dict]] = None, # non-batch only!
            observability_tool_properties: Optional[Dict] = None,
            doc_placeholders = False,
            mock: bool = False, 
            ) -> Union[Response, List[Response]]:
        """
        Performs actual the completion.
        """

        if doc_placeholders:
            self.doc_placeholders = doc_placeholders

        if observability_tool_properties is None:
            observability_tool_properties = {}

        # override/add observability_tool_properties using observability_tool_properties variable
        if observability_tool_properties:
            self.observability_tool_properties.update(observability_tool_properties)

        if 'user_id' in self.observability_tool_properties:
            logger.user_id = self.observability_tool_properties['user_id']
        
        if 'channel_id' in self.observability_tool_properties:
            logger.turn_id = self.observability_tool_properties['channel_id']

        if 'turn_id' in self.observability_tool_properties:
            turn_id = self.observability_tool_properties['turn_id']
            logger.turn_id = turn_id
            if self._check_cost_limit(turn_id):
                raise CostLimitException(f"Turn cost limit exceeded for: {turn_id}")
        
        # set headers again to update observability_tool_properties between calls
        self._set_headers()

        # reset messages (history is kept in DB)
        self.messages = []

        # if prompt_inputs are not provided, use prompt_inputs_fixed
        if prompt_inputs is None:
            prompt_inputs = self.prompt_inputs_fixed

        # Mind the order of messages below!
        # create messages from prompt_inputs only for the first messages
        if prompt_inputs is not None:
            self.messages = self._process_prompt_inputs(prompt_inputs)
        
        # add messages from history
        if self.channel_id:
            self.messages += self._get_history()

        # if messages are provided, append them to self.messages
        if messages:
            self.messages += messages

        # if prefill is not None, create an additional assistant message with the prefilled content
        if self.prefill:
            self.messages.append({'role': 'assistant', 'content': self.prefill})

        # heal messages
        # logger.debug(f"Messages before healing: {json.dumps(self.messages, indent=2)}")
        self.messages = self.heal_messages(self.messages)
        # logger.debug(f"Messages after healing: {json.dumps(self.messages, indent=2)}")

        response = self.llm.completion(
            messages=self.messages, mock=mock, current_cost=self.current_cost, prefill=self.prefill, **self.completion_kwargs)
        logger.debug(f"Response from self.llm.completion: {response}")

        if type(self.messages[0]) == dict:
            # keep messages in the object (e.g. for agents)
            message = response.get('choices', [])[0].get('message', {})
            self.messages.append(message)
            
            # Index newly submitted and response messages to vector search
            indexed_messages = None
            if self.channel_id:
                cost = Response(response).cost
                indexed_messages = self.index_messages(messages + [message], cost)

            # Detect a special case when the finish_reason is 'tool_calls' and there are no tool_calls in message
            # In this case we add a system message like GO and re-run the completion recursively
            choice = response.get('choices', [])[0]

            if choice.get('finish_reason') == 'tool_calls' and not choice.get('message', {}).get('tool_calls'):
                logger.debug(f"Detected a special case when the finish_reason is 'tool_calls' and there are no tool_calls in message. Adding a system message like GO and re-running the completion recursively")
                return self.complete(
                    prompt_inputs=prompt_inputs,
                    messages=[{'role': 'system', 'content': 'You forgot to add tool call(s), fix!'}],
                    observability_tool_properties=observability_tool_properties,
                    mock=mock,
                    )
            
            last_indexed_turn_id = None
            last_indexed_turn_ts = None
            if indexed_messages:
                last_indexed_turn_id = indexed_messages['id']
                last_indexed_turn_ts = indexed_messages['timestamp']

            return Response(response, prompt=json.dumps(self.messages, indent=2),
                            indexed_turn_id=last_indexed_turn_id, indexed_turn_ts=last_indexed_turn_ts,
                            observability_tool_properties=observability_tool_properties)

        elif type(self.messages[0]) == list and type(self.messages[0][0]) == dict:
            # we don't track thread for batch completions
            return [Response(r, prompt=json.dumps(self.messages, indent=2),
                             observability_tool_properties=observability_tool_properties) for r in response]

        else:
            error_message = f"Invalid type for 'messages'. Must be either a list of dicts or a list of lists of dicts. Got {type(self.messages)}"
            logger.error(error_message)
            raise ValueError(error_message)
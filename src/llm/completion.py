from typing import Union, List, Dict, Optional, Tuple
import os
import re
import json
import yaml

os.chdir(__file__.split('src/')[0])
import sys
sys.path.append(os.getcwd())

from src.llm.response import Response
from src.llm.trim import Trim, TrimType
from src.llm.wrappers.litellm_proxy_wrapper import LiteLLMProxyWrapper
from src.llm.tokenizer import VdTokenizer
from src.util.env_util import cfg, litellm_cfg

# Set up logger
from src.util.setup_logging import setup_logging
logger = setup_logging(__file__, "INFO")


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
                 tools: Optional[List[Dict]] = None,
                 all_skills_path: Optional[str] = cfg['paths']['skills'],
                 trim: Optional[List[Trim]] = None,
                 trim_just_in_case_tokens: Optional[int] = 100,
                 channel_id: Optional[str] = None,
                 user_id: Optional[str] = None,
                 initial_timeout: int = 100,
                 num_retries: int = 3,
                 stream: bool = False,
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
        if tools is None:
            tools = []
        if trim is None:
            trim = []

        # Set the attributes
        self.skill = skill
        self.prompt_inputs_fixed = prompt_inputs_fixed
        self.messages = messages
        self.completion_kwargs = completion_kwargs
        self.tools = tools
        self.all_skills_path = all_skills_path
        self.trim = trim
        self.trim_just_in_case_tokens = trim_just_in_case_tokens
        self.channel_id = channel_id
        self.user_id = user_id
        self.initial_timeout = initial_timeout
        self.num_retries = num_retries
        self.stream = stream
        self.doc_placeholders = []

        self.prefill = None
        self.prompt_placeholders = []
        self.model_info = {}
        self.completion_model = completion_model

        logger.user_id = user_id
        logger.turn_id = channel_id

        # Change the default value of caching to False
        self.caching = False 

        self._load_skill(self.skill)

        self.llm = LiteLLMProxyWrapper(
                caching=self.caching
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
                raise ValueError(f"Sum of trim min_lengths {min_length_sum} exceed limit of {limit} for the skill {self.skill}. "
                                 f"Limit is calculated as: context length ({self.llm_context_length}) - "
                                 f"trim_just_in_case_tokens ({self.trim_just_in_case_tokens}) - "
                                 f"prompt length ({self.prompt_len}) - "
                                 f"max_tokens ({self.completion_kwargs['max_tokens']}). "
                                 f"Adjust trim min_lengths or completion parameters.")
            
            for t in self.trim:
                if t.max_length is not None and t.max_length > limit:
                    raise ValueError(f"Trim {t.name} max_length {t.max_length} exceed limit of {limit} for the skill {self.skill}. "
                                     f"Limit is calculated as: context length ({self.llm_context_length}) - "
                                     f"trim_just_in_case_tokens ({self.trim_just_in_case_tokens}) - "
                                     f"prompt length ({self.prompt_len}) - "
                                     f"max_tokens ({self.completion_kwargs['max_tokens']}). "
                                     f"Adjust trim max_lengths or completion parameters.")

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

        # Load response_format.json if it exists
        response_format_path = os.path.join(skill_path, "response_format.json")
        if os.path.exists(response_format_path):
            with open(response_format_path, "r") as f:
                self.response_format = json.load(f)
                self.completion_kwargs['response_format'] = self.response_format

        # Overwrite model for completion if present
        if self.completion_model:
            logger.debug(f"Model defined in skill config has been overwritten to: {self.completion_model}")
            self.skill_config['completion_kwargs']['model'] = self.completion_model

        try:
            self.completion_kwargs.update(self.skill_config.get("completion_kwargs", {}))
        except:
            logger.exception(f"Failed to update completion_kwargs, observability_tool_kwargs, observability_tool_properties from skill config")

        self.litellm_model_config = [m for m in litellm_cfg['model_list'] if m['model_name'] == self.completion_kwargs['model']][0]
        self.llm_context_length = self.litellm_model_config.get("context_length", 128000)
        self.trim_limit_chars = self.llm_context_length * 6 # roughly the llm context length, to protect llm tokenizer from extremely long inputs
        self.tokenizer = VdTokenizer(scfg['completion_kwargs']['model'])
        self.prompt_len = len(self.tokenizer.encode(str(self.prompt)))
        self.trim_label = "[trimmed]"

        
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
                total_tokens = len(self.tokenizer.encode(str(messages))) \
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
        return
    
    def _get_content_from_response(self, response: dict) -> str:
        """Gets the content from the response."""
        try:
            return response['choices'][0]['message']['content']
        except:
            logger.exception("Failed to get content from LLM response, possibly due to an error")
            return "Error"


    def complete(
            self, 
            prompt_inputs: Optional[Union[Dict, List[Dict]]] = None, 
            messages: Optional[List[Dict]] = None, # non-batch only!
            doc_placeholders = False,
            mock: bool = False, 
            completion_kwargs: Optional[Dict] = None,
            generation_name_suffix: Optional[str] = "",
            ) -> Union[Response, List[Response]]:
        """
        Performs actual the completion.
        """
        # Update completion_kwargs
        self.completion_kwargs.update(completion_kwargs or {})

        # Ensure metadata exists in completion_kwargs   
        if 'metadata' not in self.completion_kwargs:
            self.completion_kwargs['metadata'] = {}
        
        # Always set the generation_name in metadata
        skill_path = '/'.join(self.skill)
        suffix = self.completion_kwargs['metadata'].get('generation_name_suffix', '')
        self.completion_kwargs['metadata']['generation_name'] = f"{skill_path}{suffix}"

        if doc_placeholders:
            self.doc_placeholders = doc_placeholders

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


        response = self.llm.completion(
            messages=self.messages, prefill=self.prefill, **self.completion_kwargs)
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
                    )
            
            last_indexed_turn_id = None
            last_indexed_turn_ts = None
            if indexed_messages:
                last_indexed_turn_id = indexed_messages['id']
                last_indexed_turn_ts = indexed_messages['timestamp']

            return Response(response, prompt=json.dumps(self.messages, indent=2),
                            indexed_turn_id=last_indexed_turn_id, indexed_turn_ts=last_indexed_turn_ts,
                            )

        elif type(self.messages[0]) == list and type(self.messages[0][0]) == dict:
            # we don't track thread for batch completions
            return [Response(r, prompt=json.dumps(self.messages, indent=2),
                             ) for r in response]

        else:
            error_message = f"Invalid type for 'messages'. Must be either a list of dicts or a list of lists of dicts. Got {type(self.messages)}"
            logger.error(error_message)
            raise ValueError(error_message)
        


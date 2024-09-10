
#%%
from typing import List
from litellm import encode, decode

class VdTokenizer:
    """
    A wrapper class for LiteLLM's encode and decode functions
    to support legacy tiktoken interface
    """

    def __init__(self, model_name: str = "gpt-4-0125-preview"):
        self.model_name = model_name
        if self.model_name.startswith('claude'):
            self.model_name = "gpt-4-0125-preview"


    def encode(self, text: str):
        encoding = encode(model=self.model_name, text=text)
        if type(encoding) == list:
            return encoding
        else:
            return encoding.ids

    def decode(self, tokens: List[int]):
        return decode(model=self.model_name, tokens=tokens)

# %%
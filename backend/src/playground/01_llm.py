#%%
from typing import Union, List, Dict, Optional, Tuple
import os
import re

os.chdir(__file__.split('src/')[0])
import sys
sys.path.append(os.getcwd())

from src.llm.completion import Completion
from src.util.env_util import cfg, litellm_cfg
from src.tools.web_search import BraveSearchClient

# Set up logger
from src.util.setup_logging import setup_logging
logger = setup_logging(__file__)
#%%

q = "How can we develop an efficient and scalable method for performing k-NN search with cross-encoders that significantly reduces computational costs and resource demands while maintaining high recall accuracy in large-scale datasets?"

web_search = BraveSearchClient()

skill = Completion(
    ('Forward', 'SubQuestions')
)

search_results = web_search.search(q)
#%%
%%time


result = skill.complete(
    prompt_inputs={
        "ORIGINAL_QUESTION": q,
        "SEARCH_RESULTS": str(search_results),
        "NUM_SUBQUESTIONS": str(3)
        }
)
result
# %%
result.content
# %%

def parse_subquestions(text):
    # Define the regex pattern to match subquestions within <subquestion> tags
    pattern = re.compile(r'<subquestion>(.*?)<\/subquestion>', re.DOTALL)
    
    # Find all matches in the text
    subquestions = pattern.findall(text)
    
    return subquestions


parse_subquestions(result.content)
# %%

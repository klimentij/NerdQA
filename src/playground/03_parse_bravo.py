#%%
import json

import json
import os
import re
import time
import sys
from typing import List
from abc import ABC, abstractmethod

os.chdir(__file__.split('src/')[0])
import sys
sys.path.append(os.getcwd())

from src.llm.completion import Completion
from src.util.env_util import cfg, litellm_cfg
from src.tools.web_search import BraveSearchClient

search = BraveSearchClient()
response = search.search("How can we develop an efficient and scalable method for performing k-NN search with cross-encoders that significantly reduces computational costs and resource demands while maintaining high recall accuracy in large-scale datasets?")
# %%
resutls = response.get('web', {}).get('results', [])
len(resutls)
# %%
resutls
# %%
len(resutls)
# %%
resutls[0]
# %%
keys_to_keep = ['title', 'page_age', 'description', 'extra_snippets']
filtered_results = [{key: result[key] for key in keys_to_keep if key in result} for result in resutls]
filtered_results
# %%
filtered_results[0]
# %%

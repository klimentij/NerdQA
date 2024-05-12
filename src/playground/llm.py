#%%
from typing import Union, List, Dict, Optional, Tuple
import os

os.chdir(__file__.split('src/')[0])
import sys
sys.path.append(os.getcwd())

from src.llm.completion import Completion
from src.util.env_util import cfg, litellm_cfg

# Set up logger
from src.util.setup_logging import setup_logging
logger = setup_logging(__file__)


skill = Completion(
    ('Test', 'Excuse')
)


result = skill.complete(
    prompt_inputs={"event": "party"}
)
result
# %%
# %%


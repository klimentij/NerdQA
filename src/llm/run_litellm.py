import os
import sys

os.chdir(__file__.split('src/')[0])
sys.path.append(os.getcwd())

from src.util.env_util import cfg
import subprocess

# Run the litellm command
subprocess.run(["litellm", "--config", "config/litellm.yml", "--debug"])


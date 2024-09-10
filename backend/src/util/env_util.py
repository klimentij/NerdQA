#%%
import os
from dotenv import load_dotenv

os.chdir(__file__.split('src/')[0])
import sys
sys.path.append(os.getcwd())

# read yml config file
import yaml
cfg_path = os.path.join(os.getcwd(), 'config', 'global.yml')
with open(cfg_path, 'r') as f:
    cfg = yaml.load(f, Loader=yaml.FullLoader)

load_dotenv(cfg['paths']['env'])

# litellm cfg
lite_cfg_path = os.path.join(os.getcwd(), 'config', 'litellm.yml')
with open(lite_cfg_path, 'r') as f:
    litellm_cfg = yaml.load(f, Loader=yaml.FullLoader)

# # Set up logger
# import logging
# from src.utils.setup_logging import setup_logging
# logger = setup_logging(__file__, log_level=logging.DEBUG, )
# logger.user_id = "utiluser"


# # detect Slack bot type (env name) from Slack bot credentials
# env_name = "unknown"
# sb_token = os.environ.get('SLACK_BOT_TOKEN', "")
# if "XgoQrfldwYtW" in sb_token:
#     env_name = "dev"
# elif "MhXodGgM07kFWTWR" in sb_token:
#     env_name = "exp"
# elif "Y28CpxFQZif" in sb_token:
#     env_name = "prod"
# else:
#     logger.warning(f"Could not detect Slack bot type (env name) from Slack bot credentials, using default: {env_name}")
import logging
import os
import json_log_formatter
import threading
import time

from logging.handlers import TimedRotatingFileHandler
from dotenv import load_dotenv

_global_json_handler = None
_global_text_handler = None
_handler_lock = threading.Lock()

os.chdir(__file__.split('src/')[0])
import sys

sys.path.append(os.getcwd())

# read yml config file (can't read from util due to circular import)
import yaml

cfg_path = os.path.join(os.getcwd(), 'configs', 'config.yml')
with open(cfg_path, 'r') as f:
    cfg = yaml.load(f, Loader=yaml.FullLoader)
load_dotenv(cfg['import']['folders']['env'])

# detect Slack bot type (env name) from Slack bot credentials
env_name = "unknown"
sb_token = os.environ.get('SLACK_BOT_TOKEN', "")
if "XgoQrfldwYtW" in sb_token:
    env_name = "dev"
elif "MhXodGgM07kFWTWR" in sb_token:
    env_name = "exp"
elif "Y28CpxFQZif" in sb_token:
    env_name = "prod"
else:
    logging.warning(f"Could not detect Slack bot type (env name) from Slack bot credentials, using default: {env_name}")


# Custom LogRecord class
class CustomLogRecord(logging.LogRecord):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user_id = getattr(logging.getLogger(self.name), 'user_id', None)
        self.turn_id = getattr(logging.getLogger(self.name), 'turn_id', None)
        self.channel_id = getattr(logging.getLogger(self.name), 'channel_id', None)


# Custom factory method to use the CustomLogRecord
def custom_record_factory(*args, **kwargs):
    return CustomLogRecord(*args, **kwargs)


def setup_logging(script_path, log_level=logging.INFO):
    """
    Setup Logger instances.
    """
    # Use custom record factory
    logging.setLogRecordFactory(custom_record_factory)
    logger_name = script_path.split('/')[-1].replace('.py', '')
    logger = logging.getLogger(logger_name)
    logger.setLevel(log_level)
    logger.propagate = False  # Stop propagation to avoid duplicate logs

    # Set Global Handlers
    global _global_json_handler
    global _global_text_handler

    # Stream Handler for console logging
    if not any(isinstance(handler, logging.StreamHandler) for handler in logger.handlers):
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
        logger.addHandler(stream_handler)

    # set up _global_json_handler if not yet and add to loggers
    with _handler_lock:
        if _global_json_handler is None:
            alpha_log_file_path = cfg['datadog']['alpha_log_file_path']
            _global_json_handler = ChunkedTimeRotatingFileHandler(alpha_log_file_path, when='midnight', interval=1, backupCount=7)
            _global_json_handler.setFormatter(CustomizedJSONFormatter())
            _global_json_handler.setLevel(logging.DEBUG)

        if _global_text_handler is None:
            text_log_file_path = os.path.join(cfg['general']['folders']['logs'], 'alpha.log')
            _global_text_handler = ChunkedTimeRotatingFileHandler(text_log_file_path, when='midnight', interval=1, backupCount=7)
            _global_text_handler.setFormatter(CustomizedTextFormatter())
            _global_text_handler.setLevel(logging.DEBUG)

    if _global_json_handler not in logger.handlers:
        logger.addHandler(_global_json_handler)

    if _global_text_handler not in logger.handlers:
        logger.addHandler(_global_text_handler)

    return logger


class ChunkedTimeRotatingFileHandler(TimedRotatingFileHandler):
    """
    ChunkedSizeRotatingFileHandler does 2 things:
    1. Writes big logs in batches to avoid broken pipe errors,
    2. Rotates based on size, Max disk space taken is 200mb
    """
    new_log = True

    def emit(self, record):
        try:
            if self.shouldRollover(record):
                self.doRollover()

            self.new_log = True
            log = self.format(record)

            if len(log) > 1000:
                for i in range(0, len(log), 1000):
                    chunk = log[i:i + 1000]
                    self.write_chunk(chunk)
            else:
                self.write_chunk(log)

        except Exception:
            self.handleError(record)

    def write_chunk(self, chunk):
        try:
            if self.stream is None:
                if self.mode != 'w':
                    self.stream = self._open()
            if self.stream:
                if not self.new_log:
                    self.stream.write(chunk)
                    self.flush()
                else:
                    self.new_log = False
                    self.stream.write("\n" + chunk)
                    self.flush()
        except RecursionError:
            raise
        except Exception:
            self.handleError(chunk)


class CustomizedJSONFormatter(json_log_formatter.JSONFormatter):
    """
        Formats log with desired attributes and json format
    """

    def __init__(self, timestamp=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.timestamp = timestamp

    def json_record(self, message: str, extra: dict, record: logging.LogRecord) -> dict:

        # Call parent
        log_output = super().json_record(message, extra, record)

        # Add time stamp when log was created
        if self.timestamp:
            log_output['timestamp'] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(record.created))

        # Append logger path information
        dir_path, file_name = os.path.split(record.pathname)
        last_folder = os.path.basename(dir_path)
        log_output['Log_call_path'] = os.path.join(last_folder, file_name)

        log_output['level'] = record.levelname

        # Add the 'environment' variable to the JSON data
        log_output['env'] = env_name

        return log_output


class CustomizedTextFormatter(logging.Formatter):
    """
        Formats log with desired attributes and text format
    """

    def format(self, record):
        try:

            # Format additional attributes
            attributes = {
                "path": os.path.join(os.path.basename(os.path.dirname(record.pathname)), os.path.basename(record.pathname)),
                "env": env_name,
                "user_id": getattr(record, 'user_id', None),
                "turn_id": getattr(record, 'turn_id', None),
                "channel_id": getattr(record, 'channel_id', None)
            }

            # remove None values
            attributes = {k: v for k, v in attributes.items() if v is not None}

            # Format timestamp, level, and message
            timestamp = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(record.created))
            
            message = record.getMessage()
            if "\n" in message:
                message = '\n' + message + '\n'

            if record.exc_text:
                trace = '\n\n' + record.exc_text + '\n\n'
            else:
                trace = ''
            
            log = f"{timestamp} {record.levelname} {message} {trace}{str(attributes)}".strip()

            return log
        
        except:
            return super().format(record)

# # Usage example
# logger = setup_logging(__file__)
# logger.info("Starting logger")
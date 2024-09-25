import os
import json
import sys
import hashlib
import redis
import yaml

os.chdir(__file__.split('src/')[0])
sys.path.append(os.getcwd())
from src.util.setup_logging import setup_logging
logger = setup_logging(__file__, "INFO")

class LocalCache:
    def __init__(self, config_file='config/litellm.yml', ttl=2592000):
        self.ttl = ttl
        self.redis_client = self._setup_redis(config_file)

    def _setup_redis(self, config_file):
        """Set up Redis connection using parameters from the config file."""
        with open(config_file, 'r') as file:
            config = yaml.safe_load(file)
        
        cache_params = config.get('litellm_settings', {}).get('cache_params', {})
        if cache_params.get('type') != 'redis':
            raise ValueError("Cache type is not set to 'redis' in the config file")

        return redis.Redis(
            host=cache_params.get('host', 'localhost'),
            port=cache_params.get('port', 6379),
            password=cache_params.get('password', None),
            decode_responses=True
        )

    def _hash(self, key):
        """Create a hash for a given key."""
        return hashlib.md5(json.dumps(key, sort_keys=True).encode('utf-8')).hexdigest()

    def get(self, key):
        """Retrieve an item from the cache."""
        hashed_key = self._hash(key)
        result = self.redis_client.get(hashed_key)
        if result:
            logger.debug(f"Cache hit for key '{hashed_key}'.")
            return json.loads(result)
        else:
            logger.debug(f"Cache miss for key '{hashed_key}'.")
            return None

    def set(self, key, value):
        """Store an item in the cache."""
        hashed_key = self._hash(key)
        self.redis_client.setex(hashed_key, self.ttl, json.dumps(value))
        logger.debug(f"Cache set for key '{hashed_key}'.")

    def delete(self, key):
        """Delete an item from the cache."""
        hashed_key = self._hash(key)
        self.redis_client.delete(hashed_key)
        logger.debug(f"Cache entry deleted for key '{hashed_key}'.")

# Example usage:
# cache = LocalCache()
# cache.set("query_key", {"results": "some search results"})
# response = cache.get("query_key")
# print(response)

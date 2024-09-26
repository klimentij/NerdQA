#%%
import os
import json
import sys
import hashlib
import redis
import yaml
import asyncio

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
        return hashlib.md5(str(key).encode('utf-8')).hexdigest()

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

    def __call__(self, func):
        """Decorator to cache function results based on input parameters."""
        async def async_wrapper(*args, **kwargs):
            # Create a cache key based on the function name and its arguments
            cache_key = self._hash((func.__name__, str(args), str(sorted(kwargs.items()))))
            
            # Try to get the result from the cache
            cached_result = self.get(cache_key)
            if cached_result is not None:
                return cached_result
            
            # Call the function and cache the result
            result = await func(*args, **kwargs)
            self.set(cache_key, result)
            return result

        def sync_wrapper(*args, **kwargs):
            # Create a cache key based on the function name and its arguments
            cache_key = self._hash((func.__name__, str(args), str(sorted(kwargs.items()))))
            
            # Try to get the result from the cache
            cached_result = self.get(cache_key)
            if cached_result is not None:
                return cached_result
            
            # Call the function and cache the result
            result = func(*args, **kwargs)
            self.set(cache_key, result)
            return result

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

def main():
    # Example usage:
    cache = LocalCache()
    import time

    @cache
    def expensive_function(param1, param2):
        # Simulate an expensive computation
        time.sleep(3)
        return param1 + param2

    result = expensive_function(1, 3)
    print(result)

    # Example usage:
    # cache = LocalCache()
    # cache.set("query_key", {"results": "some search results"})
    # response = cache.get("query_key")
    # print(response)

    # Define a Pydantic dataclass
    from pydantic import BaseModel
    from typing import Tuple, Dict, Any

    class InputData(BaseModel):
        param1: int
        param2: str

    # Example usage:
    cache = LocalCache()

    @cache
    def complex_function(data: InputData) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        # Simulate an expensive computation
        result1 = {"result": data.param1 * 2, "description": data.param2}
        result2 = {"result": data.param1 + 5, "description": data.param2.upper()}
        time.sleep(3)
        return result1, result2

    # Create an instance of the Pydantic dataclass
    input_data = InputData(param1=2, param2="example")

    # Call the cached function
    result = complex_function(input_data)
    print(result)

if __name__ == "__main__":
    main()
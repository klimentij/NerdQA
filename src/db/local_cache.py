import os
import json
import sys
import hashlib
from diskcache import FanoutCache

os.chdir(__file__.split('src/')[0])
sys.path.append(os.getcwd())
from src.util.setup_logging import setup_logging
logger = setup_logging(__file__)

class LocalCache:
    def __init__(self, cache_dir='./cache', ttl=2592000):
        self.cache = FanoutCache(cache_dir, shards=8)  # Use 8 shards for better concurrency
        self.ttl = ttl

    def _hash(self, key):
        """Create a hash for a given key."""
        return hashlib.md5(json.dumps(key, sort_keys=True).encode('utf-8')).hexdigest()

    def get(self, key):
        """Retrieve an item from the cache."""
        hashed_key = self._hash(key)
        result = self.cache.get(hashed_key)
        if result:
            logger.debug(f"Cache hit for key '{hashed_key}'.")
            return result
        else:
            logger.debug(f"Cache miss for key '{hashed_key}'.")
            return None

    def set(self, key, value):
        """Store an item in the cache."""
        hashed_key = self._hash(key)
        self.cache.set(hashed_key, value, expire=self.ttl)
        logger.debug(f"Cache set for key '{hashed_key}'.")

    def delete(self, key):
        """Delete an item from the cache."""
        hashed_key = self._hash(key)
        self.cache.delete(hashed_key)
        logger.debug(f"Cache entry deleted for key '{hashed_key}'.")

# Example usage:
# cache = LocalCache()
# cache.set("query_key", {"results": "some search results"})
# response = cache.get("query_key")
# print(response)
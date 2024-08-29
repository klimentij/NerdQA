import json
import hashlib
import os
import time
from supabase import create_client, Client

os.chdir(__file__.split('src/')[0])
import sys
sys.path.append(os.getcwd())

from src.util.setup_logging import setup_logging
logger = setup_logging(__file__)

class CacheLLM:
    def __init__(self, ttl=2592000):
        self.ttl = ttl
        self.supabase: Client = create_client(
            os.environ.get("SUPABASE_URL"),
            os.environ.get("SUPABASE_KEY")
        )

    def _hash(self, input):
        """Create a hash for a given input."""
        return hashlib.md5(json.dumps(input, sort_keys=True).encode('utf-8')).hexdigest()

    def get(self, payload):
        """Retrieve an item from the cache."""
        start_time = time.time()
        key = self._hash(payload)

        response = self.supabase.table('cache_llm').select('response').eq('payload_hash', key).execute()
        result = response.data[0] if response.data else None

        query_time = time.time() - start_time
        if result:
            logger.debug(f"Cache hit for key '{key}'. Retrieved in {query_time:.6f} seconds.")
            return result['response']  # This is already a dict due to JSONB in Supabase
        else:
            logger.debug(f"Cache miss for key '{key}'. Lookup took {query_time:.6f} seconds.")
            return None

    def set(self, payload, headers, response):
        """Store an item in the cache."""
        start_time = time.time()
        key = self._hash(payload)
        data = {
            'payload_hash': key,
            'env': headers.get('env'),
            'latency': headers.get('latency'),
            'model': headers.get('model'),
            'skill': headers.get('skill'),
            'user_id': headers.get('user_id'),
            'payload': payload,  # This will be stored as JSONB
            'response': response  # This will be stored as JSONB
        }

        self.supabase.table('cache_llm').upsert(data).execute()

        query_time = time.time() - start_time
        logger.debug(f"Cache set for key '{key}' took {query_time:.6f} seconds.")

    def delete(self, payload):
        """Delete an item from the cache."""
        key = self._hash(payload)
        self.supabase.table('cache_llm').delete().eq('payload_hash', key).execute()

# # Example usage:
# cache = CacheLLM()
# cache.set({"query": "hello world"}, {"env": "prod"}, {"result": "hello"})
# response = cache.get({"query": "hello world"})
# print(response)

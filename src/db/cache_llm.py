import json
import hashlib
import os
import time

os.chdir(__file__.split('src/')[0])
import sys
sys.path.append(os.getcwd())

from src.db.database_connection import DatabaseConnection
from src.util.setup_logging import setup_logging
logger = setup_logging(__file__)

class CacheLLM(DatabaseConnection):
    def __init__(self, ttl=2592000):  # Default TTL of 30 days
        super().__init__()
        self.ttl = ttl

    def _hash(self, input):
        """Create a hash for a given input."""
        return hashlib.md5(str(input).encode('utf-8')).hexdigest()

    def get(self, payload):
        """Retrieve an item from the cache."""
        start_time = time.time()
        key = self._hash(payload)
        start_time = time.time()
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT response FROM cache_llm WHERE payload_hash = %(key)s",
                            {'key': key})
                result = cur.fetchone()
                logger.debug(f"Checked cache for key: '{key}'. Took {time.time() - start_time:.10f} seconds.")
                return result['response'] if result else None

    def set(self, payload, headers, response):
        """Store an item in the cache."""
        start_time = time.time()
        key = self._hash(payload)
        env = headers.get('env')
        latency = headers.get('latency')
        model = headers.get('model')
        skill = headers.get('skill')
        user_id = headers.get('user_id')

        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO cache_llm (payload_hash, env, latency, model, skill, user_id, payload, response)
                    VALUES (%(key)s, %(env)s, %(latency)s, %(model)s, %(skill)s, %(user_id)s, %(payload)s, %(response)s)
                    ON CONFLICT (payload_hash) DO UPDATE SET
                        response = EXCLUDED.response,
                        timestamp = CURRENT_TIMESTAMP
                    """,
                    {
                        'key': key,
                        'env': env,
                        'latency': latency,
                        'model': model,
                        'skill': skill,
                        'user_id': user_id,
                        'payload': json.dumps(payload),
                        'response': json.dumps(response)
                    }
                )
                conn.commit()
        logger.debug(f"Saved response in cache for key: {key}. Took {time.time() - start_time:.10f} seconds.")


    def delete(self, payload):
        """Delete an item from the cache."""
        key = self._hash(payload)
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM cache_llm WHERE payload_hash = %(key)s", {'key': key})
                conn.commit()

# # Example usage:
# cache = CacheLLM()
# cache.set({"query": "hello world"}, {"env": "prod"}, {"result": "hello"})
# response = cache.get({"query": "hello world"})
# print(response)

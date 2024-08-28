import os
import sys
import time
import json
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
import hashlib

os.chdir(__file__.split('src/')[0])
sys.path.append(os.getcwd())
from src.util.env_util import cfg
from src.db.cache_llm import CacheLLM

# Set up logger
from src.util.setup_logging import setup_logging
logger = setup_logging(__file__)

class BraveSearchClient:
    def __init__(self):
        self.base_url = "https://api.search.brave.com/res/v1/web/search"
        self.api_key = os.environ.get("BRAVE_SEARCH_API_KEY")
        self.headers = {
            'X-Subscription-Token': self.api_key,
            'Accept-Encoding': 'gzip'
        }
        self.default_params = {
            'result_filter': 'web',
            'extra_snippets': '1',
            'text_decorations': '0'
        }
        self.session = requests.Session()
        retries = Retry(total=5, backoff_factor=1, status_forcelist=[502, 503, 504])
        self.session.mount('https://', HTTPAdapter(max_retries=retries))
        self.cache = CacheLLM()

    def search(self, query, **kwargs):
        """
        Perform a search using the Brave Search API, with caching.

        Parameters:
            query (str): The search query.
            **kwargs: Optional parameters to override default search parameters.

        Returns:
            dict: The filtered search results.
        """
        start_time = time.time()
        params = self.default_params.copy()
        params.update(kwargs)   
        params['q'] = query

        # Check cache
        cached_response = self.cache.get(params)
        if cached_response:
            # Convert to dict if it's a string
            if isinstance(cached_response, str):
                try:
                    return json.loads(cached_response)
                except json.JSONDecodeError:
                    logger.error("Failed to decode cached response as JSON")
                    return None
            return cached_response  # Already a dict

        try:
            logger.debug(f"Sending search request to Brave API: {params}")
            response = self.session.get(self.base_url, headers=self.headers, params=params)
            response.raise_for_status()

            # Filter results and add IDs
            filtered_results = self._filter_results(response.json())

            # Add debug log for number of returned results
            num_results = len(filtered_results['web']['results'])
            logger.debug(f"Number of returned results: {num_results}")

            # Store filtered results in cache
            latency = time.time() - start_time
            logger.debug(f"Received and processed response in {latency:.4f} seconds")
            self.cache.set(params, self.headers, filtered_results)

            return filtered_results
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTPError during search: {e}")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {e}")
            raise

    def _filter_results(self, response):
        """
        Filter the search results to include only specified keys and format description and extra_snippets.

        Parameters:
            response (dict): The raw search results.

        Returns:
            dict: The filtered search results with formatted description and extra_snippets.
        """
        keys_to_keep = ['title', 'page_age', 'description', 'extra_snippets']
        results = response.get('web', {}).get('results', [])
        filtered_results = []

        for result in results:
            filtered_result = {}
            for key in keys_to_keep:
                if key in result:
                    if key == 'description':
                        filtered_result[key] = self._format_text_as_json(result[key])
                    elif key == 'extra_snippets':
                        filtered_result[key] = [self._format_text_as_json(snippet) for snippet in result[key]]
                    else:
                        filtered_result[key] = result[key]
            filtered_results.append(filtered_result)

        return {'web': {'results': filtered_results}}

    def _format_text_as_json(self, text):
        """
        Format text as a JSON object with 'id' and 'text' keys.

        Parameters:
            text (str): The text to format.

        Returns:
            dict: A JSON object with 'id' and 'text' keys.
        """
        text_hash = int(hashlib.md5(text.encode()).hexdigest(), 16)
        unique_id = f"E{text_hash % 10**10:010d}"
        return {"id": unique_id, "text": text}

# Example usage
# brave_search = BraveSearchClient()
# results = brave_search.search("Can the curse of dimensionality be overcome entirely, or is it an inherent challenge that must be managed when working with high-dimensional data? What are the trade-offs and limitations of various approaches?")
# logger.info(f"Search results: \n\n{json.dumps(results, indent=2, sort_keys=False)}")

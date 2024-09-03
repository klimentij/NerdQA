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
from src.db.local_cache import LocalCache

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
        self.cache = LocalCache()

    def search(self, query, **kwargs):
        """
        Perform a search using the Brave Search API, with caching.

        Parameters:
            query (str): The search query.
            **kwargs: Optional parameters to override default search parameters.

        Returns:
            dict: The search results wrapped in a dictionary.
        """
        start_time = time.time()
        params = self.default_params.copy()
        params.update(kwargs)   
        params['q'] = query

        # Check cache
        cached_response = self.cache.get(params)
        if cached_response is not None:
            logger.debug("Returning cached results")
            return {"results": cached_response}

        try:
            logger.debug(f"Sending search request to Brave API: {params}")
            response = self.session.get(self.base_url, headers=self.headers, params=params)
            response.raise_for_status()

            # Filter results and add IDs
            filtered_results = self._filter_results(response.json())

            # Add debug log for number of returned results
            num_results = len(filtered_results)
            logger.debug(f"Number of returned results: {num_results}")

            # Store filtered results in cache
            latency = time.time() - start_time
            logger.debug(f"Received and processed response in {latency:.4f} seconds")
            self.cache.set(params, filtered_results)

            # Wrap the results in a dictionary
            return {"results": filtered_results}
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTPError during search: {e}")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {e}")
            raise

    def _filter_results(self, response):
        """
        Filter the search results to include only specified keys and format as a single-level list.

        Parameters:
            response (dict): The raw search results.

        Returns:
            list: A list of dictionaries, each containing 'id', 'text', and 'meta' keys.
        """
        results = response.get('web', {}).get('results', [])
        filtered_results = []

        for result in results:
            meta = {
                'title': result.get('title', ''),
                'url': result.get('url', ''),
                'page_age': result.get('page_age', '')
            }

            # Create the main text from description and extra_snippets
            main_text = result.get('description', '')
            if 'extra_snippets' in result:
                main_text += ' ' + ' '.join(result['extra_snippets'])

            # Add the main result
            filtered_results.append(self._format_text_as_json(main_text, meta=meta))

            # Add individual entries for description and extra_snippets
            if 'description' in result:
                filtered_results.append(self._format_text_as_json(result['description'], meta=meta))
            
            if 'extra_snippets' in result:
                for snippet in result['extra_snippets']:    
                    filtered_results.append(self._format_text_as_json(snippet, meta=meta))

        return filtered_results

    def _format_text_as_json(self, text, meta=None):
        """
        Format text as a JSON object with 'id', 'meta', and 'text' keys.
        Drop empty/none fields from meta.

        Parameters:
            text (str): The text to format.
            meta (dict): Metadata for the text.

        Returns:
            dict: A JSON object with 'id', 'meta', and 'text' keys.
        """
        text_hash = int(hashlib.md5(text.encode()).hexdigest(), 16)
        unique_id = f"E{text_hash % 10**10:010d}"
        
        # Drop empty/none fields from meta
        cleaned_meta = {k: v for k, v in (meta or {}).items() if v}
        
        return {"id": unique_id, "meta": cleaned_meta, "text": text}

# Example usage
# brave_search = BraveSearchClient()
# results = brave_search.search("Can the curse of dimensionality be overcome entirely, or is it an inherent challenge that must be managed when working with high-dimensional data? What are the trade-offs and limitations of various approache`?")
# logger.info(f"Search results: \n\n{json.dumps(results, indent=2, sort_keys=False)}")
import os
import sys
import time
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

os.chdir(__file__.split('src/')[0])
sys.path.append(os.getcwd())
from src.util.env_util import cfg

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

    def search(self, query, **kwargs):
        """
        Perform a search using the Brave Search API.

        Parameters:
            query (str): The search query.
            **kwargs: Optional parameters to override default search parameters.

        Returns:
            dict: The search results.
        """
        params = self.default_params.copy()
        params.update(kwargs)
        params['q'] = query
        start_time = time.time()
        try:
            logger.debug(f"Sending search request to Brave API: {params}")
            response = self.session.get(self.base_url, headers=self.headers, params=params)
            response.raise_for_status()
            latency = time.time() - start_time
            logger.debug(f"Received response in {latency:.2f} seconds")
            return response.json()
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTPError during search: {e}")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {e}")
            raise

# Usage example:
if __name__ == "__main__":
    brave_search = BraveSearchClient()
    results = brave_search.search("ethical implications of AI")
    print(results)

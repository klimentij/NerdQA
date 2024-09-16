import os
import sys
import time
import json
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
import hashlib
import urllib.parse
from abc import ABC, abstractmethod

os.chdir(__file__.split('src/')[0])
sys.path.append(os.getcwd())
from src.util.env_util import cfg
from src.db.local_cache import LocalCache

# Set up logger
from src.util.setup_logging import setup_logging
logger = setup_logging(__file__)

class SearchClient(ABC):
    def __init__(self):
        self.session = requests.Session()
        retries = Retry(
            total=10,
            backoff_factor=0.1,
            status_forcelist=[429, 502, 503, 504],
            respect_retry_after_header=True
        )
        self.session.mount('https://', HTTPAdapter(max_retries=retries))
        self.cache = LocalCache()

    @abstractmethod
    def _get_search_url(self, query: str) -> str:
        pass

    @abstractmethod
    def _get_headers(self) -> dict:
        pass

    @abstractmethod
    def _get_payload(self, query: str) -> dict:
        pass

    def search(self, query: str) -> dict:
        url = self._get_search_url(query)
        headers = self._get_headers()
        payload = self._get_payload(query)
        
        # Generate a cache key
        cache_key = hashlib.md5(f"{url}{json.dumps(headers)}{json.dumps(payload)}".encode()).hexdigest()
        
        # Check cache
        cached_response = self.cache.get(cache_key)
        if cached_response is not None:
            logger.debug("Returning cached results")
            return cached_response

        logger.debug(f"Sending request to URL: {url}")
        logger.debug(f"Headers: {headers}")
        logger.debug(f"Payload: {payload}")
        
        try:
            if payload:
                response = self.session.post(url, headers=headers, json=payload)
            else:
                response = self.session.get(url, headers=headers)
            response.raise_for_status()
            raw_results = response.json()
            
            # Debug log the unfiltered search results
            logger.debug(f"Unfiltered search results: {json.dumps(raw_results, indent=2)}")
            
            filtered_results = self._filter_results(raw_results)
            result = {"results": filtered_results}
            
            # Cache the result
            self.cache.set(cache_key, result)
            
            return result
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                logger.warning(f"Rate limit exceeded (429 error). Retrying...")
                raise
            logger.error(f"HTTP error occurred: {e}")
            logger.error(f"Response content: {e.response.content}")
            return {"error": str(e), "response_content": e.response.content.decode()}
        except Exception as e:
            logger.error(f"An error occurred during web search: {e}")
            return {"error": str(e)}

    @abstractmethod
    def _filter_results(self, response):
        pass

    def _format_text_as_json(self, text, meta=None):
        text_hash = int(hashlib.md5(text.encode()).hexdigest(), 16)
        unique_id = f"E{text_hash % 10**10:010d}"
        
        cleaned_meta = {k: v for k, v in (meta or {}).items() if v}
        
        return {"id": unique_id, "meta": cleaned_meta, "text": text}

class BraveSearchClient(SearchClient):
    def __init__(self):
        super().__init__()
        self.base_url = "https://api.search.brave.com/res/v1/web/search"
        self.api_key = os.environ.get("BRAVE_SEARCH_API_KEY")
        if not self.api_key:
            raise ValueError("BRAVE_SEARCH_API_KEY environment variable is not set")
        self.headers = {
            'X-Subscription-Token': self.api_key,
            'Accept': 'application/json',
            'Accept-Encoding': 'gzip'
        }
        self.default_params = {
            'result_filter': 'web',
            'extra_snippets': '1',
            'text_decorations': '0'
        }

    def _get_search_url(self, query: str) -> str:
        encoded_query = urllib.parse.quote(query)
        return f"{self.base_url}?q={encoded_query}&result_filter=web&extra_snippets=1&text_decorations=0"

    def _get_headers(self) -> dict:
        return self.headers

    def _get_payload(self, query: str) -> dict:
        return None

    def search(self, query: str) -> dict:
        return super().search(query)

    def _filter_results(self, response):
        results = response.get('web', {}).get('results', [])
        filtered_results = []

        for result in results:
            meta = {
                'title': result.get('title', ''),
                'url': result.get('url', ''),
                'page_age': result.get('page_age', '')
            }

            main_text = result.get('description', '')
            if 'extra_snippets' in result:
                main_text += ' ' + ' '.join(result['extra_snippets'])

            filtered_results.append(self._format_text_as_json(main_text, meta=meta))

            if 'description' in result:
                filtered_results.append(self._format_text_as_json(result['description'], meta=meta))
            
            if 'extra_snippets' in result:
                for snippet in result['extra_snippets']:    
                    filtered_results.append(self._format_text_as_json(snippet, meta=meta))

        return filtered_results

class ExaSearchClient(SearchClient):
    def __init__(self):
        super().__init__()
        self.base_url = "https://api.exa.ai/search"
        self.api_key = os.environ.get("EXA_SEARCH_API_KEY")
        if not self.api_key:
            raise ValueError("EXA_SEARCH_API_KEY environment variable is not set")
        self.headers = {
            'x-api-key': self.api_key,
            'accept': 'application/json',
            'content-type': 'application/json'
        }

    def _get_search_url(self, query: str) -> str:
        return self.base_url

    def _get_headers(self) -> dict:
        return self.headers

    def _get_payload(self, query: str) -> dict:
        payload = {
            "query": query,
            "type": "keyword",
            "numResults": 10,
            "contents": {
                "text": {
                    "maxCharacters": 200000
                }
            }
        }
        return payload

    def search(self, query: str) -> dict:
        return super().search(query)

    def _filter_results(self, response):
        results = response.get('results', [])
        filtered_results = []

        for result in results:
            meta = {
                'title': result.get('title', ''),
                'url': result.get('url', ''),
                'author': result.get('author', ''),
                'published_date': result.get('publishedDate', '')
            }

            main_text = result.get('text', '')

            filtered_results.append(self._format_text_as_json(main_text, meta=meta))

        return filtered_results

# Example usage
# web_search = BraveSearchClient()
# web_search = ExaSearchClient()
# results = web_search.search("Can  the curse of dimensionality be overcome entirely, or is it an inherent challenge that must be managed when working with high-dimensional data? What are the trade-offs and limitations of various approache`?")
# top_3_results = {"results": results["results"][:3]}  # Get only the top 3 results
# logger.info(f"Top 3 search results: \n\n{json.dumps(top_3_results, indent=2, sort_keys=False)}")
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
from typing import List, Dict

os.chdir(__file__.split('src/')[0])
sys.path.append(os.getcwd())
from src.util.env_util import cfg
from src.db.local_cache import LocalCache

# Set up logger
from src.util.setup_logging import setup_logging
logger = setup_logging(__file__)

class SearchClient(ABC):
    def __init__(self, max_document_size_tokens: int = 3000, chunk_size: int = 2048, chunk_overlap: int = 256):
        self.session = requests.Session()
        retries = Retry(
            total=10,
            backoff_factor=0.1,
            status_forcelist=[429, 502, 503, 504],
            respect_retry_after_header=True
        )
        self.session.mount('https://', HTTPAdapter(max_retries=retries))
        self.cache = LocalCache()
        self.max_document_size_tokens = max_document_size_tokens
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.cohere_api_key = os.environ.get("COHERE_API_KEY")
        if not self.cohere_api_key:
            raise ValueError("COHERE_API_KEY environment variable is not set")
        self.reranker_model = cfg['models']['reranker']

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
            processed_results = []
            for result in filtered_results:
                processed_results.extend(self._process_result(result))
            
            result = {"results": processed_results}
            
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

    def _format_text_as_json(self, text, meta=None, num_tokens=None):
        text_hash = int(hashlib.md5(text.encode()).hexdigest(), 16)
        unique_id = f"E{text_hash % 10**10:010d}"
        
        cleaned_meta = {k: v for k, v in (meta or {}).items() if v}
        
        if num_tokens is not None:
            cleaned_meta['num_tokens'] = num_tokens
        
        return {"id": unique_id, "meta": cleaned_meta, "text": text}

    def _tokenize(self, text: str) -> List[int]:
        url = "https://api.cohere.com/v1/tokenize"
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "Authorization": f"bearer {self.cohere_api_key}"
        }
        payload = {
            "model": self.reranker_model,
            "text": text
        }
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json().get("tokens", [])

    def _detokenize(self, tokens: List[int]) -> str:
        url = "https://api.cohere.com/v1/detokenize"
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "Authorization": f"bearer {self.cohere_api_key}"
        }
        payload = {
            "model": self.reranker_model,
            "tokens": tokens
        }
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json().get("text", "")

    def _chunk_text(self, text: str, meta: Dict, tokens: List[int]) -> List[Dict]:
        chunks = []
        start = 0
        total_chunks = -(-len(tokens) // (self.chunk_size - self.chunk_overlap))  # Ceiling division

        while start < len(tokens):
            end = start + self.chunk_size
            chunk_tokens = tokens[start:end]
            chunk_text = self._detokenize(chunk_tokens)
            chunk_meta = meta.copy()
            chunk_meta["chunk"] = f"{len(chunks) + 1} of {total_chunks}"
            chunks.append(self._format_text_as_json(chunk_text, meta=chunk_meta, num_tokens=len(chunk_tokens)))
            start += self.chunk_size - self.chunk_overlap

        return chunks

    def _process_result(self, result: Dict) -> List[Dict]:
        meta = result.get("meta", {})
        text = result.get("text", "")
        
        tokens = self._tokenize(text)
        num_tokens = len(tokens)
        
        if num_tokens <= self.max_document_size_tokens:
            return [self._format_text_as_json(text, meta=meta, num_tokens=num_tokens)]
        
        if num_tokens <= self.chunk_size:
            return [self._format_text_as_json(text, meta=meta, num_tokens=num_tokens)]
        
        return self._chunk_text(text, meta, tokens)

class BraveSearchClient(SearchClient):
    def __init__(self, max_document_size_tokens: int = 3000, chunk_size: int = 2048, chunk_overlap: int = 256):
        super().__init__(max_document_size_tokens, chunk_size, chunk_overlap)
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
    def __init__(self, max_document_size_tokens: int = 3000, chunk_size: int = 2048, chunk_overlap: int = 256):
        super().__init__(max_document_size_tokens, chunk_size, chunk_overlap)
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

# ... existing code ...

# Example usage
exa_search = ExaSearchClient(max_document_size_tokens=100, chunk_size=10, chunk_overlap=3)

# Example text chunking using existing methods
example_text = """
Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum.

Sed ut perspiciatis unde omnis iste natus error sit voluptatem accusantium doloremque laudantium, totam rem aperiam, eaque ipsa quae ab illo inventore veritatis et quasi architecto beatae vitae dicta sunt explicabo. Nemo enim ipsam voluptatem quia voluptas sit aspernatur aut odit aut fugit, sed quia consequuntur magni dolores eos qui ratione voluptatem sequi nesciunt. Neque porro quisquam est, qui dolorem ipsum quia dolor sit amet, consectetur, adipisci velit, sed quia non numquam eius modi tempora incidunt ut labore et dolore magnam aliquam quaerat voluptatem.
"""

example_meta = {
    "title": "Lorem Ipsum Example",
    "source": "Example Text"
}

logger.info(f"Example text: \n\n{example_text}")
# Tokenize the text before passing it to _chunk_text
start_time = time.time()
example_tokens = exa_search._tokenize(example_text)

# Use the existing _chunk_text method with the tokenized text
chunked_text = exa_search._chunk_text(example_text, example_meta, example_tokens)
logger.info(f"Chunked text example: \n\n{json.dumps(chunked_text, indent=2, sort_keys=False)}")
end_time = time.time()
tokenization_time = end_time - start_time
logger.info(f"took {tokenization_time:.4f} seconds")

# Existing search examples (commented out)
# results = brave_search.search("Can the curse of dimensionality be overcome entirely, or is it an inherent challenge that must be managed when working with high-dimensional data? What are the trade-offs and limitations of various approaches?")
# top_3_results = {"results": results["results"][:3]}  # Get only the top 3 results
# logger.info(f"Top 3 search results: \n\n{json.dumps(top_3_results, indent=2, sort_keys=False)}")
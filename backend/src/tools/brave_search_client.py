import os
import sys
from typing import Dict, List
import urllib.parse

os.chdir(__file__.split('src/')[0])
sys.path.append(os.getcwd())

# Set up logger
from src.util.setup_logging import setup_logging
logger = setup_logging(__file__, log_level="DEBUG")

from src.util.setup_logging import setup_logging
from src.tools.search_client import SearchClient

logger = setup_logging(__file__, log_level="DEBUG")

class BraveSearchClient(SearchClient):
    def __init__(self, reranking_threshold: float = 0.2, **kwargs):
        super().__init__(reranking_threshold=reranking_threshold, **kwargs)
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
        return f"{self.base_url}?q={encoded_query}&result_filter=web&extra_snippets=1&text_decorations=0" # &count={self.num_results}"

    def _get_headers(self) -> dict:
        return self.headers

    def _get_payload(self, query: str, start_published_date: str = None, end_published_date: str = None, **kwargs) -> dict:
        return None

    def search(self, query: str, main_question: str = None, start_published_date: str = None, end_published_date: str = None, **kwargs) -> dict:
        return super().search(query, main_question, start_published_date, end_published_date, **kwargs)

    def _filter_results(self, response):
        results = response.get('web', {}).get('results', [])
        filtered_results = []

        for result in results:
            meta = {
                'title': result.get('title', ''),
                'url': result.get('url', ''),
                'published_date': result.get('page_age', '')  # Changed from 'page_age' to 'published_date'
            }

            main_text = result.get('description', '')
            if 'extra_snippets' in result:
                main_text += ' ' + ' '.join(result['extra_snippets'])

            filtered_results.append({"text": main_text, "meta": meta})

        return filtered_results

    def _process_result(self, result: Dict) -> List[Dict]:
        meta = result.get("meta", {})
        text = result.get("text", "")
        
        tokens = self._tokenize(text)
        num_tokens = len(tokens)
        
        if num_tokens <= self.max_document_size_tokens:
            return [self._format_text_as_json(text, meta=meta, num_tokens=num_tokens)]
        
        return self._chunk_text(text, meta, tokens)
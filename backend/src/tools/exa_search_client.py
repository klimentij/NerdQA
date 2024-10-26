import os
import sys
import hashlib
from typing import Dict, List

os.chdir(__file__.split('src/')[0])
sys.path.append(os.getcwd())
from src.util.env_util import cfg
from src.db.local_cache import LocalCache

# Set up logger
from src.util.setup_logging import setup_logging
logger = setup_logging(__file__, log_level="DEBUG")

from src.util.setup_logging import setup_logging
from src.tools.search_client import SearchClient

logger = setup_logging(__file__, log_level="DEBUG")

class ExaSearchClient(SearchClient):
    def __init__(self, type: str = "neural", use_autoprompt: bool = True, reranking_threshold: float = 0.05, **kwargs):
        super().__init__(reranking_threshold=reranking_threshold, **kwargs)
        self.base_url = "https://api.exa.ai/search"
        self.api_key = os.environ.get("EXA_SEARCH_API_KEY")
        if not self.api_key:
            raise ValueError("EXA_SEARCH_API_KEY environment variable is not set")
        self.headers = {
            'x-api-key': self.api_key,
            'accept': 'application/json',
            'content-type': 'application/json'
        }
        self.type = type
        self.use_autoprompt = use_autoprompt

    def _get_search_url(self, query: str) -> str:
        return self.base_url

    def _get_headers(self) -> dict:
        return self.headers

    def _get_payload(self, query: str, start_published_date: str = None, end_published_date: str = None, type: str = None, use_autoprompt: bool = None) -> dict:
        payload = {
            "query": query[:20000],  # ExaSearch has some character limit
            "type": type if type is not None else self.type,
            "use_autoprompt": use_autoprompt if use_autoprompt is not None else self.use_autoprompt,
            "numResults": self.num_results,
            "excludeText": ["Chain-of-Thought"],
            "contents": {
                "text": {
                    "maxCharacters": 200000
                }
            }
        }
        if start_published_date:
            payload["start_published_date"] = f"{start_published_date}T00:00:00.000Z"
        if end_published_date:
            payload["end_published_date"] = f"{end_published_date}T23:59:59.999Z"
        return payload

    def search(self, query: str, main_question: str = None, start_published_date: str = None, end_published_date: str = None, type: str = None, use_autoprompt: bool = None) -> dict:
        return super().search(query, main_question, start_published_date, end_published_date, type=type, use_autoprompt=use_autoprompt)

    def _create_limited_meta(self, meta):
        # For ExaSearchClient, we'll use the same limited_meta as the full meta
        return meta.copy()

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

    def search(self, query: str, main_question: str = None, start_published_date: str = None, end_published_date: str = None, type: str = None, use_autoprompt: bool = None) -> dict:
        return super().search(query, main_question, start_published_date, end_published_date, type=type, use_autoprompt=use_autoprompt)

    def _format_text_as_json(self, text, meta=None, num_tokens=None):
        text_hash = int(hashlib.md5(text.encode()).hexdigest(), 16)
        unique_id = f"E{text_hash % 10**10:010d}"
        
        cleaned_meta = {k: v for k, v in (meta or {}).items() if v}
        
        if num_tokens is not None:
            cleaned_meta['num_tokens'] = num_tokens
        
        # Create limited_meta (by default, same as full meta)
        limited_meta = self._create_limited_meta(cleaned_meta)
        
        return {"id": unique_id, "meta": cleaned_meta, "limited_meta": limited_meta, "text": text}

    def _process_result(self, result: Dict) -> List[Dict]:
        meta = result.get("meta", {})
        text = result.get("text", "")
        
        tokens = self._tokenize(text)
        num_tokens = len(tokens)
        
        if not self.use_chunking or num_tokens <= self.max_document_size_tokens:
            return [self._format_text_as_json(text, meta=meta, num_tokens=num_tokens)]
        
        if num_tokens <= self.chunk_size:
            return [self._format_text_as_json(text, meta=meta, num_tokens=num_tokens)]
        
        chunked_results = self.chunker.chunk_text(text, meta)
        return [self._format_text_as_json(chunk["text"], meta=chunk["meta"], num_tokens=chunk["num_tokens"]) for chunk in chunked_results]

    # ... rest of the class ...

# Exa example usage
exa_search = ExaSearchClient(rerank=True, caching=False, 
                             reranking_threshold=0.2, 
                             initial_top_to_retrieve=20,
                             chunk_size=1024)

def main():
    exa_results = exa_search.search(
        "What are the latest advancements in quantum computing?",
        start_published_date="2023-01-01", 
        end_published_date="2023-12-31",
        type="neural",
        use_autoprompt=True
    )
    
    print(f"Total results: {len(exa_results['results'])}")  
    for i, result in enumerate(exa_results['results'][:5], 1):
        print(f"\nResult {i}:")
        print(f"Title: {result['meta'].get('title', 'N/A')}")
        print(f"URL: {result['meta'].get('url', 'N/A')}")
        print(f"Published Date: {result['meta'].get('published_date', 'N/A')}")
        print(f"Reranker Score: {result['meta'].get('reranker_score', 'N/A')}")
        print(f"Text snippet: {result['text'][:200]}...")

if __name__ == "__main__":
    main()
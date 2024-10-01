import os
import random
import sys
import time
import json
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import hashlib
from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from tokenizers import Tokenizer
from src.tools.exa_downloader import ExaDownloader
from src.util.chunking_util import Chunker

os.chdir(__file__.split('src/')[0])
sys.path.append(os.getcwd())
from src.util.env_util import cfg
from src.db.local_cache import LocalCache
from src.util.setup_logging import setup_logging

logger = setup_logging(__file__, log_level="DEBUG")

# Add this constant at the script level
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/115.0'
]

def get_random_user_agent():
    return random.choice(USER_AGENTS)

def get_common_headers():
    return {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }

class SearchClient(ABC):
    def __init__(self, max_document_size_tokens: int = 3000, chunk_size: int = 2048, chunk_overlap: int = 512, 
                 rerank: bool = True, max_docs_to_rerank: int = 1000, num_results: int = 25, 
                 caching: bool = True, sort: str = None, initial_top_to_retrieve: int = 3, 
                 reranking_threshold: float = 0.2, max_concurrent_downloads: int = 50, 
                 url_list_retry_rounds: int = 1, use_pdf_cache: bool = True, downloader=None,
                 use_chunking: bool = True):  # Add this parameter
        self.session = requests.Session()
        retries = Retry(
            total=10,
            backoff_factor=0.1,
            status_forcelist=[429, 502, 503, 504],
            respect_retry_after_header=True
        )
        self.session.mount('https://', HTTPAdapter(max_retries=retries))
        self.downloader = downloader or ExaDownloader(
            max_concurrent_downloads=max_concurrent_downloads,
            url_list_retry_rounds=url_list_retry_rounds,
            use_cache=use_pdf_cache
        )
        self.cache = LocalCache() if caching else None
        self.max_document_size_tokens = max_document_size_tokens
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.cohere_api_key = os.environ.get("COHERE_API_KEY")
        if not self.cohere_api_key:
            raise ValueError("COHERE_API_KEY environment variable is not set")
        self.tokenizer = Tokenizer.from_pretrained("Cohere/rerank-english-v3.0")
        self.tokenizer.enable_truncation(max_length=int(1e6))
        self.reranker_model = cfg['models']['reranker']
        self.rerank = rerank
        self.max_docs_to_rerank = max_docs_to_rerank
        self.num_results = num_results
        self.sort = sort
        self.initial_top_to_retrieve = initial_top_to_retrieve
        self.reranking_threshold = reranking_threshold
        self.max_concurrent_downloads = max_concurrent_downloads
        self.use_chunking = use_chunking  # Store the new parameter
        self.chunker = Chunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)  # Initialize Chunker

    @abstractmethod
    def _get_search_url(self, query: str) -> str:
        pass

    @abstractmethod
    def _get_headers(self) -> dict:
        pass

    @abstractmethod
    def _get_payload(self, query: str, start_published_date: str = None, end_published_date: str = None, **kwargs) -> dict:
        pass

    @abstractmethod
    def _filter_results(self, response):
        pass

    def search(self, query: str, main_question: str = None, start_published_date: str = None, end_published_date: str = None, sort: str = None, **kwargs) -> dict:
        url = self._get_search_url(query)
        headers = self._get_headers()
        payload = self._get_payload(query, start_published_date, end_published_date, **kwargs)
        
        # Generate a cache key
        cache_key = hashlib.md5(f"{url}{json.dumps(headers)}{json.dumps(payload)}".encode()).hexdigest()
        
        # Check cache only if caching is enabled
        if self.cache:
            cached_response = self.cache.get(cache_key)
            if cached_response is not None:
                logger.debug(f"Returning cached results: {json.dumps(cached_response, indent=2)}")
                return cached_response
        
        try:
            start_time = time.time()
            if payload:
                response = self.session.post(url, headers=headers, json=payload)
            else:
                response = self.session.get(url, headers=headers)
            response.raise_for_status()
            raw_results = response.json()
            
            end_time = time.time()
            search_time = end_time - start_time
            
            logger.info(f"Retrieved raw results from search in {search_time:.2f} seconds")
            
            start_time = time.time()
            filtered_results = self._filter_results(raw_results)
            initially_retrieved = len(filtered_results)
            processed_results = []
            for result in filtered_results:
                processed_results.extend(self._process_result(result))
            
            after_chunking = len(processed_results)
            
            end_time = time.time()
            processing_time = end_time - start_time
            
            logger.info(f"Processed and chunked {len(filtered_results)} results (turned into {len(processed_results)} results) in {processing_time:.2f} seconds")
            
            # Log unchunked results before reranker
            logger.debug(f"Unchunked results before reranker: {json.dumps(filtered_results, indent=2)}")
            
            # Rerank the results if enabled
            reranked_results = self._rerank_results(query, processed_results, main_question)
            
            after_reranking = len(reranked_results)
            
            result = {"results": reranked_results}
            
            # Cache the result only if caching is enabled
            if self.cache:
                self.cache.set(cache_key, result)
            
            # Add search summary log
            logger.info(f"""
Search Summary:
- Initially retrieved results: {initially_retrieved}
- Results after chunking: {after_chunking}
- Results after reranking and threshold filtering: {after_reranking}
""")
            
            return result
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                logger.warning(f"Rate limit exceeded (429 error). Retrying...")
                raise
            logger.error(f"HTTP error occurred: {e}")
            logger.error(f"Response content: {e.response.content.decode()}")
            return {"error": str(e), "response_content": e.response.content.decode()}
        except Exception as e:
            logger.error(f"An error occurred during web search: {e}")
            return {"error": str(e)}

    def _format_text_as_json(self, text, meta=None, num_tokens=None):
        text_hash = int(hashlib.md5(text.encode()).hexdigest(), 16)
        unique_id = f"E{text_hash % 10**10:010d}"
        
        cleaned_meta = {k: v for k, v in (meta or {}).items() if v}
        
        if num_tokens is not None:
            cleaned_meta['num_tokens'] = num_tokens
        
        # Create limited_meta (by default, same as full meta)
        limited_meta = self._create_limited_meta(cleaned_meta)
        
        return {"id": unique_id, "meta": cleaned_meta, "limited_meta": limited_meta, "text": text}

    def _create_limited_meta(self, meta):
        # By default, limited_meta is the same as full meta
        # Subclasses can override this method to customize limited_meta
        return meta.copy()

    def _tokenize(self, text: str) -> List[int]:
        return self.tokenizer.encode(text).ids

    def _detokenize(self, tokens: List[int]) -> str:
        return self.tokenizer.decode(tokens)

    def _chunk_text(self, text: str, meta: Dict, tokens: List[int]) -> List[Dict]:
        chunks = []
        start = 0
        total_chunks = -(-len(tokens) // (self.chunk_size - self.chunk_overlap))  # Ceiling division

        while start < len(tokens):
            end = start + self.chunk_size
            chunk_tokens = tokens[start:end]
            chunk_text = self._detokenize(chunk_tokens)
            
            if start > 0:
                chunk_text = ".." + chunk_text
            if end < len(tokens):
                chunk_text = chunk_text + ".."
            
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
        
        if not self.use_chunking or num_tokens <= self.max_document_size_tokens:
            return [self._format_text_as_json(text, meta=meta, num_tokens=num_tokens)]
        
        if num_tokens <= self.chunk_size:
            return [self._format_text_as_json(text, meta=meta, num_tokens=num_tokens)]
        
        chunked_results = self.chunker.chunk_text(text, meta)
        return [self._format_text_as_json(chunk["text"], meta=chunk["meta"], num_tokens=chunk["num_tokens"]) for chunk in chunked_results]

    def _rerank_results(self, query: str, results: List[Dict], main_question: str = None) -> List[Dict]:
        if not self.rerank:
            return results

        rerank_url = "https://api.cohere.ai/v1/rerank"
        headers = {
            "Authorization": f"Bearer {self.cohere_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        if main_question:
            rerank_query = f"""
The main research question:
'''{main_question}'''

Current query the user needs to answer to progress towards solving the main question:
'''{query}'''
"""
        else:
            rerank_query = query

        payload = {
            "model": self.reranker_model,
            "query": rerank_query,
            "documents": [str(result) for result in results[:self.max_docs_to_rerank]],
            "top_n": self.max_docs_to_rerank
        }

        try:
            start_time = time.time()
            response = self.session.post(rerank_url, headers=headers, json=payload)
            response.raise_for_status()
            reranked_data = response.json()
            end_time = time.time()
            num_documents = min(len(results), self.max_docs_to_rerank)
            logger.info(f"Reranked {num_documents} documents in {end_time - start_time:.2f} seconds")

            index_to_score = {item['index']: item['relevance_score'] for item in reranked_data['results']}

            for i, result in enumerate(results):
                result['meta']['reranker_score'] = index_to_score.get(i, 0)

            filtered_results = [
                result for result in results 
                if result['meta'].get('reranker_score', 0) >= self.reranking_threshold
            ]

            filtered_results.sort(key=lambda x: x['meta']['reranker_score'], reverse=True)

            for i, result in enumerate(filtered_results, 1):
                result['meta']['reranker_rank'] = i

            return filtered_results

        except Exception as e:
            logger.error(f"An error occurred during reranking: {e}")
            return results

    async def process_papers(self, results: List[Dict]) -> List[Dict]:
        return await self.downloader.process_papers(results, self.cache)
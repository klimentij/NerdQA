#%%
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
from tokenizers import Tokenizer

os.chdir(__file__.split('src/')[0])
sys.path.append(os.getcwd())
from src.util.env_util import cfg
from src.db.local_cache import LocalCache

# Set up logger
from src.util.setup_logging import setup_logging
logger = setup_logging(__file__, log_level="DEBUG")

class SearchClient(ABC):
    def __init__(self, max_document_size_tokens: int = 3000, chunk_size: int = 2048, chunk_overlap: int = 512, rerank: bool = True, max_docs_to_rerank: int = 1000, num_results: int = 25, caching: bool = True, sort: str = None):
        self.session = requests.Session()
        retries = Retry(
            total=10,
            backoff_factor=0.1,
            status_forcelist=[429, 502, 503, 504],
            respect_retry_after_header=True
        )
        self.session.mount('https://', HTTPAdapter(max_retries=retries))
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

    @abstractmethod
    def _get_search_url(self, query: str) -> str:
        pass

    @abstractmethod
    def _get_headers(self) -> dict:
        pass

    @abstractmethod
    def _get_payload(self, query: str, start_published_date: str = None, end_published_date: str = None, **kwargs) -> dict:
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
                logger.debug("Returning cached results")
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
            processed_results = []
            for result in filtered_results:
                processed_results.extend(self._process_result(result))
            
            end_time = time.time()
            processing_time = end_time - start_time
            
            logger.info(f"Processed and chunked {len(filtered_results)} results (turned into {len(processed_results)} results) in {processing_time:.2f} seconds")
            
            # Log unchunked results before reranker
            logger.info(f"Unchunked results before reranker: {json.dumps(filtered_results, indent=2)}")
            
            # Rerank the results if enabled
            reranked_results = self._rerank_results(query, processed_results, main_question)
            
            result = {"results": reranked_results}
            
            # Cache the result only if caching is enabled
            if self.cache:
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
            
            # Add ".." before and after the chunk, except for the first and last chunks
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
        
        if num_tokens <= self.max_document_size_tokens:
            return [self._format_text_as_json(text, meta=meta, num_tokens=num_tokens)]
        
        if num_tokens <= self.chunk_size:
            return [self._format_text_as_json(text, meta=meta, num_tokens=num_tokens)]
        
        return self._chunk_text(text, meta, tokens)

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
            "documents": [str(result) for result in results],
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
            reranked_data = response.json()

            # Create a mapping of original index to new score
            index_to_score = {item['index']: item['relevance_score'] for item in reranked_data['results']}

            # Add scores to the original results and sort
            for i, result in enumerate(results):
                result['relevance_score'] = index_to_score.get(i, 0)

            results.sort(key=lambda x: x['relevance_score'], reverse=True)
            return results

        except Exception as e:
            logger.error(f"An error occurred during reranking: {e}")
            return results  # Return original results if reranking fails

class BraveSearchClient(SearchClient):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
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

class ExaSearchClient(SearchClient):
    def __init__(self, type: str = "neural", use_autoprompt: bool = True, **kwargs):
        super().__init__(**kwargs)
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

class OpenAlexSearchClient(SearchClient):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.base_url = "https://api.openalex.org/works"
        self.headers = {
            'Accept': 'application/json'
        }

    def _get_search_url(self, query: str, sort: str = None) -> str:
        encoded_query = urllib.parse.quote(query)
        url = f"{self.base_url}?search={encoded_query}"
        url += f"&select=id,doi,title,relevance_score,publication_date,cited_by_count,topics,keywords,concepts,best_oa_location,abstract_inverted_index,updated_date,created_date"
        
        # Use the provided sort parameter, or default to relevance_score:desc
        sort = sort or self.sort or "relevance_score:desc"
        url += f"&sort={sort}"
        
        url += f"&per-page={self.num_results}"
        return url

    def _get_headers(self) -> dict:
        return self.headers

    def _get_payload(self, query: str, start_published_date: str = None, end_published_date: str = None, **kwargs) -> dict:
        return None  # We don't need a payload for GET requests

    def search(self, query: str, main_question: str = None, start_published_date: str = None, end_published_date: str = None, sort: str = None, **kwargs) -> dict:
        url = self._get_search_url(query, sort)
        
        if start_published_date and end_published_date:
            url += f"&filter=from_publication_date:{start_published_date},to_publication_date:{end_published_date}"

        if kwargs.get("has_fulltext"):
            url += "&filter=has_fulltext:true"

        if kwargs.get("is_oa"):
            url += "&filter=oa_status:gold|bronze|green"

        headers = self._get_headers()
        
        # Generate a cache key
        cache_key = hashlib.md5(f"{url}{json.dumps(headers)}".encode()).hexdigest()
        
        # Check cache only if caching is enabled
        if self.cache:
            cached_response = self.cache.get(cache_key)
            if cached_response is not None:
                logger.debug("Returning cached results")
                return cached_response
        
        try:
            start_time = time.time()
            response = self.session.get(url, headers=headers)
            response.raise_for_status()
            raw_results = response.json()
            
            end_time = time.time()
            search_time = end_time - start_time
            
            logger.info(f"Retrieved raw results from search in {search_time:.2f} seconds")
            
            start_time = time.time()
            filtered_results = self._filter_results(raw_results)
            processed_results = []
            for result in filtered_results:
                processed_results.extend(self._process_result(result))
            
            end_time = time.time()
            processing_time = end_time - start_time
            
            logger.info(f"Processed and chunked {len(filtered_results)} results (turned into {len(processed_results)} results) in {processing_time:.2f} seconds")
            
            # Rerank the results if enabled
            reranked_results = self._rerank_results(query, processed_results, main_question)
            
            result = {"results": reranked_results}
            
            # Cache the result only if caching is enabled
            if self.cache:
                self.cache.set(cache_key, result)
            
            return result
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error occurred: {e}")
            logger.error(f"Response content: {e.response.content}")
            return {"error": str(e), "response_content": e.response.content.decode()}
        except Exception as e:
            logger.error(f"An error occurred during web search: {e}")
            return {"error": str(e)}

    def _filter_results(self, response):
        results = response.get('results', [])
        filtered_results = []

        for result in results:
            meta = {
                'id': result.get('id', ''),
                'title': result.get('title', ''),
                'publication_date': result.get('publication_date', ''),
                'cited_by_count': result.get('cited_by_count', 0),
                'topics': ', '.join([topic.get('display_name', '') for topic in result.get('topics', [])]),
                'keywords': ', '.join([keyword.get('display_name', '') for keyword in result.get('keywords', [])]),
                'concepts': ', '.join([concept.get('display_name', '') for concept in result.get('concepts', [])]),
                'best_oa_location': result.get('best_oa_location', {}).get('pdf_url', ''),
            }

            abstract = self._reconstruct_abstract(result.get('abstract_inverted_index', {}))

            filtered_results.append({"text": abstract, "meta": meta})

        return filtered_results

    def _reconstruct_abstract(self, abstract_inverted_index):
        if not abstract_inverted_index:
            return ""

        # Create a list of (position, word) tuples
        word_positions = []
        for word, positions in abstract_inverted_index.items():
            for pos in positions:
                word_positions.append((pos, word))

        # Sort the list by position
        word_positions.sort()

        # Join the words in order
        return " ".join(word for _, word in word_positions)

    def _process_result(self, result: Dict) -> List[Dict]:
        meta = result.get("meta", {})
        text = result.get("text", "")
        
        tokens = self._tokenize(text)
        num_tokens = len(tokens)
        
        if num_tokens <= self.max_document_size_tokens:
            return [self._format_text_as_json(text, meta=meta, num_tokens=num_tokens)]
        
        return self._chunk_text(text, meta, tokens)

#%%
# Example usage
# web_search = BraveSearchClient()
# brave_results = web_search.search("""reated with 2 and 120 h later, expression of the SASP factors CCL2, CCL8, CXCL1PCR. In HCT116p53+/+, SW48 and SW48 cells a weak induction of IL8 and CCL2 (2-4-fold) was observed after exposure toiplatin. A weak induction of CCL2 in LoVo cells was observed at 120 h (3-fold), whereas a strong induction of IL8 (8-fold) was observed both at 96 and 120 h. Furthermore, LoVo cells also exhibited an upregulation of CCL8 and IL6 (4-8 fold); induction of IL""", 
#                              main_question="hey yo?")
# top_3_brave_results = {"results": brave_results["results"][:3]}  # Get only the top 3 results
# logger.info(f"Top 3 Brave search results: \n\n{json.dumps(top_3_brave_results, indent=2, sort_keys=False)}")

# OpenAlex example usage
openalex_search = OpenAlexSearchClient(rerank=False, caching=False)

# Default sort (by relevance_score:desc)
openalex_results = openalex_search.search("How can natural language rationales improve reasoning in language models?", start_published_date="2020-01-01", end_published_date="2023-12-31")
print("Default sort results:")
print(json.dumps(openalex_results, indent=2, sort_keys=False))

# Sort by cited_by_count:desc
openalex_results_cited = openalex_search.search(
    "How can natural language rationales improve reasoning in language models?", 
    start_published_date="2020-01-01", end_published_date="2023-12-31")
print(json.dumps(openalex_results_cited, indent=2, sort_keys=False))
# %%

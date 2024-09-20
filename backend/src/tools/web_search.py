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
from io import BytesIO
from pdfminer.high_level import extract_text
from pdfminer.layout import LAParams

import concurrent.futures
from threading import Semaphore
from functools import partial

os.chdir(__file__.split('src/')[0])
sys.path.append(os.getcwd())
from src.util.env_util import cfg
from src.db.local_cache import LocalCache

# Set up logger
from src.util.setup_logging import setup_logging
logger = setup_logging(__file__, log_level="DEBUG")

class SearchClient(ABC):
    def __init__(self, max_document_size_tokens: int = 3000, chunk_size: int = 2048, chunk_overlap: int = 512, rerank: bool = True, max_docs_to_rerank: int = 1000, num_results: int = 25, caching: bool = True, sort: str = None, initial_top_to_retrieve: int = 1000, reranking_threshold: float = 0.2):
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
        self.initial_top_to_retrieve = initial_top_to_retrieve
        self.reranking_threshold = reranking_threshold

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
            initially_retrieved = len(filtered_results)
            processed_results = []
            for result in filtered_results:
                processed_results.extend(self._process_result(result))
            
            after_chunking = len(processed_results)
            
            end_time = time.time()
            processing_time = end_time - start_time
            
            logger.info(f"Processed and chunked {len(filtered_results)} results (turned into {len(processed_results)} results) in {processing_time:.2f} seconds")
            
            # Log unchunked results before reranker
            logger.info(f"Unchunked results before reranker: {json.dumps(filtered_results, indent=2)}")
            
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

            # Create a mapping of original index to new score
            index_to_score = {item['index']: item['relevance_score'] for item in reranked_data['results']}

            # Add scores to the original results and sort
            for i, result in enumerate(results):
                result['meta']['reranker_score'] = index_to_score.get(i, 0)

            # Modify this part to apply the reranking threshold
            filtered_results = [
                result for result in results 
                if result['meta'].get('reranker_score', 0) >= self.reranking_threshold
            ]

            # Sort the filtered results
            filtered_results.sort(key=lambda x: x['meta']['reranker_score'], reverse=True)

            # Add reranker rank to filtered results
            for i, result in enumerate(filtered_results, 1):
                result['meta']['reranker_rank'] = i

            return filtered_results

        except Exception as e:
            logger.error(f"An error occurred during reranking: {e}")
            return results  # Return original results if reranking fails

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

class ExaSearchClient(SearchClient):
    def __init__(self, type: str = "neural", use_autoprompt: bool = True, reranking_threshold: float = 0.2, **kwargs):
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
    def __init__(self, reranking_threshold: float = 0.2, **kwargs):
        super().__init__(reranking_threshold=reranking_threshold, **kwargs)
        self.base_url = "https://api.openalex.org/works"
        self.headers = {
            'Accept': 'application/json'
        }
        self.per_page = min(self.initial_top_to_retrieve, 200)  # Adjust per_page based on initial_top_to_retrieve

    def _get_search_url(self, query: str, sort: str = None, page: int = 1) -> str:
        encoded_query = urllib.parse.quote(query)
        url = f"{self.base_url}?search={encoded_query}"
        url += f"&select=id,doi,title,relevance_score,publication_date,cited_by_count,topics,keywords,concepts,best_oa_location,abstract_inverted_index,updated_date,created_date,locations"
        
        # Use the provided sort parameter, or default to relevance_score:desc
        sort = sort or self.sort or "relevance_score:desc"
        url += f"&sort={sort}"
        
        url += f"&per-page={self.per_page}&page={page}"
        return url

    def _get_headers(self) -> dict:
        return self.headers

    def _get_payload(self, query: str, start_published_date: str = None, end_published_date: str = None, **kwargs) -> dict:
        return None  # We don't need a payload for GET requests

    def _download_and_parse_pdf(self, pdf_url, locations):
        try:
            if pdf_url:
                response = requests.get(pdf_url, timeout=30)
                if response.status_code == 200:
                    pdf_content = BytesIO(response.content)
                    text_content = extract_text(pdf_content, laparams=LAParams())
                    return text_content
                else:
                    logger.warning(f"Failed to download PDF from {pdf_url}")
            
            # If pdf_url is None, empty, or download failed, try arXiv
            arxiv_pdf_url = self._get_arxiv_pdf_url(locations)
            if arxiv_pdf_url:
                logger.info(f"Attempting to download PDF from arXiv: {arxiv_pdf_url}")
                response = requests.get(arxiv_pdf_url, timeout=30)
                if response.status_code == 200:
                    pdf_content = BytesIO(response.content)
                    text_content = extract_text(pdf_content, laparams=LAParams())
                    return text_content
                else:
                    logger.warning(f"Failed to download PDF from arXiv: {arxiv_pdf_url}")
            
            return None
        except Exception as e:
            logger.error(f"Error downloading or parsing PDF: {e}")
            return None

    def _get_arxiv_pdf_url(self, locations):
        for location in locations:
            landing_page_url = location.get('landing_page_url', '')
            if 'arxiv.org/abs/' in landing_page_url:
                return landing_page_url.replace('/abs/', '/pdf/') + '.pdf'
        return None

    def _filter_results(self, response):
        results = response.get('results', [])
        filtered_results = []

        for result in results:
            try:
                meta = {
                    'id': self._safe_get(result, 'id', ''),
                    'title': self._safe_get(result, 'title', ''),
                    'publication_date': self._safe_get(result, 'publication_date', ''),
                    'cited_by_count': self._safe_get(result, 'cited_by_count', 0),
                    'topics': self._safe_join(result, 'topics'),
                    'keywords': self._safe_join(result, 'keywords'),
                    'concepts': self._safe_join(result, 'concepts'),
                    'best_oa_location_pdf_url': self._safe_get(self._safe_get(result, 'best_oa_location', {}), 'pdf_url', ''),
                    'openalex_score': self._safe_get(result, 'relevance_score', 0),  # Add OpenAlex score
                }

                abstract = self._reconstruct_abstract(self._safe_get(result, 'abstract_inverted_index', {}))
                locations = self._safe_get(result, 'locations', [])

                filtered_results.append({"text": abstract, "meta": meta, "locations": locations})
            except Exception as e:
                logger.warning(f"Error processing result: {e}", exc_info=True)
                continue

        # Sort by OpenAlex score and add rank
        filtered_results.sort(key=lambda x: x['meta']['openalex_score'], reverse=True)
        for i, result in enumerate(filtered_results, 1):
            result['meta']['openalex_rank'] = i

        return filtered_results

    def _safe_get(self, obj, key, default=None):
        try:
            return obj.get(key, default) if isinstance(obj, dict) else default
        except Exception:
            return default

    def _safe_join(self, result, key):
        try:
            items = self._safe_get(result, key, [])
            return ', '.join([self._safe_get(item, 'display_name', '') for item in items if isinstance(item, dict)])
        except Exception:
            return ''

    def _reconstruct_abstract(self, abstract_inverted_index):
        try:
            if not isinstance(abstract_inverted_index, dict):
                return ""

            word_positions = []
            for word, positions in abstract_inverted_index.items():
                if isinstance(positions, list):
                    for pos in positions:
                        if isinstance(pos, int):
                            word_positions.append((pos, word))

            word_positions.sort()
            return " ".join(word for _, word in word_positions)
        except Exception as e:
            logger.warning(f"Error reconstructing abstract: {e}", exc_info=True)
            return ""

    def _process_result(self, result: Dict) -> List[Dict]:
        meta = result.get("meta", {})
        text = result.get("text", "")
        
        tokens = self._tokenize(text)
        num_tokens = len(tokens)
        
        if num_tokens <= self.max_document_size_tokens:
            return [self._format_text_as_json(text, meta=meta, num_tokens=num_tokens)]
        
        return self._chunk_text(text, meta, tokens)

    def _process_pdf_results(self, results):
        processed_results = []
        download_start_time = time.time()
        successful_downloads = 0
        failed_downloads = 0

        max_concurrent_downloads = 5  # Adjust this value based on your needs
        semaphore = Semaphore(max_concurrent_downloads)

        def download_and_parse_pdf_with_semaphore(result):
            with semaphore:
                return self._download_and_parse_pdf_wrapper(result)

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrent_downloads) as executor:
            future_to_result = {executor.submit(download_and_parse_pdf_with_semaphore, result): result for result in results}
            
            for future in concurrent.futures.as_completed(future_to_result):
                result = future_to_result[future]
                try:
                    pdf_text = future.result()
                    if pdf_text:
                        result['text'] = pdf_text
                        successful_downloads += 1
                    else:
                        failed_downloads += 1
                except Exception as exc:
                    logger.error(f"PDF processing generated an exception: {exc}")
                    failed_downloads += 1
                processed_results.append(result)

        download_end_time = time.time()
        total_download_time = download_end_time - download_start_time

        logger.info(f"PDF download summary:")
        logger.info(f"  Total download time: {total_download_time:.2f} seconds")
        logger.info(f"  Successful downloads: {successful_downloads}")
        logger.info(f"  Failed downloads: {failed_downloads}")

        return processed_results

    def _download_and_parse_pdf_wrapper(self, result):
        pdf_url = result['meta'].get('best_oa_location_pdf_url')
        locations = result.get('locations', [])
        
        if not pdf_url or not pdf_url.strip():
            pdf_url = None
        
        if pdf_url or locations:
            return self._download_and_parse_pdf(pdf_url, locations)
        return None

    def search(self, query: str, main_question: str = None, start_published_date: str = None, end_published_date: str = None, sort: str = None, **kwargs) -> dict:
        results = []
        total_count = 0
        page = 1
        total_retrieval_time = 0

        while len(results) < self.initial_top_to_retrieve:
            url = self._get_search_url(query, sort, page)
            
            if start_published_date and end_published_date:
                url += f"&filter=from_publication_date:{start_published_date},to_publication_date:{end_published_date}"

            logger.debug(f"Sending request to URL: {url}")

            headers = self._get_headers()
            
            cache_key = hashlib.md5(f"{url}{json.dumps(headers)}".encode()).hexdigest()
            
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
                total_retrieval_time += search_time
                
                logger.info(f"Retrieved {len(raw_results['results'])} raw results from search in {search_time:.2f} seconds")
                    
                start_time = time.time()
                page_results = self._filter_results(raw_results)
                results.extend(page_results)
                
                end_time = time.time()
                processing_time = end_time - start_time
                
                logger.info(f"Processed and chunked {len(page_results)} results (turned into {len(results)} results) in {processing_time:.2f} seconds")
                
                if page == 1:
                    total_count = raw_results['meta']['count']
                    if total_count <= self.per_page:
                        break

                if len(results) >= min(total_count, self.initial_top_to_retrieve):
                    break

                page += 1
            except requests.exceptions.HTTPError as e:
                logger.error(f"HTTP error occurred: {e}")
                logger.error(f"Response content: {e.response.content}")
                return {"error": str(e), "response_content": e.response.content.decode()}
            except Exception as e:
                logger.error(f"An error occurred during web search: {e}", exc_info=True)
                return {"error": str(e)}

        logger.info(f"Total time for all OpenAlex retrieval requests: {total_retrieval_time:.2f} seconds")

        # After filtering results but before processing and reranking
        results = self._process_pdf_results(results[:self.initial_top_to_retrieve])

        processed_results = []
        for result in results:
            processed_results.extend(self._process_result(result))

        reranked_results = self._rerank_results(query, processed_results, main_question)

        # Log final merged results
        logger.debug(f"Final merged results after reranking: {json.dumps(reranked_results, indent=2)}")

        return {"results": reranked_results, "total_count": total_count}

#%%
# Example usage
# web_search = BraveSearchClient()
# brave_results = web_search.search("""reated with 2 and 120 h later, expression of the SASP factors CCL2, CCL8, CXCL1PCR. In HCT116p53+/+, SW48 and SW48 cells a weak induction of IL8 and CCL2 (2-4-fold) was observed after exposure toiplatin. A weak induction of CCL2 in LoVo cells was observed at 120 h (3-fold), whereas a strong induction of IL8 (8-fold) was observed both at 96 and 120 h. Furthermore, LoVo cells also exhibited an upregulation of CCL8 and IL6 (4-8 fold); induction of IL""", 
#                              main_question="hey yo?")
# top_3_brave_results = {"results": brave_results["results"][:3]}  # Get only the top 3 results
# logger.info(f"Top 3 Brave search results: \n\n{json.dumps(top_3_brave_results, indent=2, sort_keys=False)}")

# OpenAlex example usage
openalex_search = OpenAlexSearchClient(rerank=True, caching=False, 
                                       reranking_threshold=0.2, 
                                       initial_top_to_retrieve=10,
                                       chunk_size=1024)

openalex_results_cited = openalex_search.search(
    "How can natural language rationales improve reasoning in language models?", 
    start_published_date="2020-01-01", end_published_date="2023-12-31")
# %%

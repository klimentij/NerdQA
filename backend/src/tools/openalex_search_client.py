import os
import sys
import time
import json
import hashlib
from typing import Dict, List
import urllib.parse
import asyncio
import aiohttp
import certifi
import ssl

os.chdir(__file__.split('src/')[0])
sys.path.append(os.getcwd())
from src.util.env_util import cfg
from src.db.local_cache import LocalCache

# Set up logger
from src.util.setup_logging import setup_logging
logger = setup_logging(__file__, log_level="DEBUG")

from src.util.setup_logging import setup_logging
from src.tools.search_client import SearchClient, get_common_headers
from src.tools.pdf_downloader import PDFDownloader

logger = setup_logging(__file__, log_level="DEBUG")

class OpenAlexSearchClient(SearchClient):
    def __init__(self, type: str = "neural", use_autoprompt: bool = True, reranking_threshold: float = 0.2, max_concurrent_downloads: int = 5, url_list_retry_rounds: int = 2, **kwargs):
        super().__init__(reranking_threshold=reranking_threshold, max_concurrent_downloads=max_concurrent_downloads, **kwargs)
        self.base_url = "https://api.openalex.org/works"
        self.api_key = os.environ.get("EXA_SEARCH_API_KEY")
        if not self.api_key:
            raise ValueError("EXA_SEARCH_API_KEY environment variable is not set")
        self.headers = {
            'Authorization': f"Bearer {self.api_key}",
            **get_common_headers()
        }
        self.per_page = min(self.initial_top_to_retrieve, 200)  # Adjust per_page based on initial_top_to_retrieve
        self.pdf_downloader = PDFDownloader(max_concurrent_downloads=self.max_concurrent_downloads, url_list_retry_rounds=url_list_retry_rounds)  # Set the number of concurrent downloads
        self.pdf_cache = LocalCache()  # New cache for PDF content

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

    async def search(self, query: str, main_question: str = None, start_published_date: str = None, end_published_date: str = None, sort: str = None, **kwargs) -> dict:
        results = []
        total_count = 0
        page = 1
        total_retrieval_time = 0

        # Create SSL context using certifi
        ssl_context = ssl.create_default_context(cafile=certifi.where())

        while len(results) < self.initial_top_to_retrieve:
            url = self._get_search_url(query, sort, page)
            
            if start_published_date and end_published_date:
                url += f"&filter=from_publication_date:{start_published_date},to_publication_date:{end_published_date}"

            logger.debug(f"Sending request to URL: {url}")

            headers = {}
            
            cache_key = hashlib.md5(f"{url}{json.dumps(headers)}".encode()).hexdigest()
            
            if self.cache:
                cached_response = self.cache.get(cache_key)
                if cached_response is not None:
                    logger.debug("Returning cached results")
                    return cached_response
            
            try:
                start_time = time.time()
                async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
                    async with session.get(url, headers=headers, allow_redirects=True) as response:
                        response.raise_for_status()
                        raw_results = await response.json()
            
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
            except aiohttp.ClientResponseError as e:
                logger.error(f"HTTP error occurred: {e}")
                return {"error": str(e)}
            except aiohttp.ContentTypeError as e:
                logger.error(f"Content Type error: {e}")
                return {"error": str(e)}
            except aiohttp.ClientError as e:
                logger.error(f"Client error occurred: {e}")
                return {"error": str(e)}
            except Exception as e:
                logger.error(f"An unexpected error occurred during web search: {e}", exc_info=True)
                return {"error": str(e)}

        logger.info(f"Total time for all OpenAlex retrieval requests: {total_retrieval_time:.2f} seconds")

        # Use the PDFDownloader to process paper downloads
        results = await self.pdf_downloader.process_papers(results[:self.initial_top_to_retrieve], self.pdf_cache)

        processed_results = []
        for result in results:
            processed_results.extend(self._process_result(result))

        reranked_results = self._rerank_results(query, processed_results, main_question)

        logger.debug(f"Reranked results:\n\n {json.dumps(reranked_results, indent=2)}")

        return {"results": reranked_results, "total_count": total_count}

    def _extract_prioritized_pdf_links(self, result):
        pdf_links = []
        seen = set()

        def add_unique(url):
            if url and url not in seen:
                seen.add(url)
                pdf_links.append(url)

        # 1. Extract open_access.oa_url
        open_access = self._safe_get(result, 'open_access', {})
        if self._safe_get(open_access, 'is_oa'):
            add_unique(self._safe_get(open_access, 'oa_url'))

        # 2. Extract best_oa_location.pdf_url
        best_oa_location = self._safe_get(result, 'best_oa_location', {})
        add_unique(self._safe_get(best_oa_location, 'pdf_url'))

        # 3. Extract pdf_url from locations
        locations = self._safe_get(result, 'locations', [])
        for location in locations:
            add_unique(self._safe_get(location, 'pdf_url'))

        # 4. Transform arXiv links
        for location in locations:
            landing_page_url = self._safe_get(location, 'landing_page_url', '')
            if landing_page_url.startswith('https://arxiv.org/abs/'):
                add_unique(self._transform_arxiv_link(landing_page_url))

        return pdf_links

    def _transform_arxiv_link(self, url):
        return url.replace('/abs/', '/pdf/').replace('.pdf', '')

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
                    'openalex_score': self._safe_get(result, 'relevance_score', 0),
                    'pdf_urls_by_priority': self._extract_prioritized_pdf_links(result),
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
    

# OpenAlex example usage
openalex_search = OpenAlexSearchClient(rerank=True, caching=False, 
                                       reranking_threshold=0.2, 
                                       initial_top_to_retrieve=20,
                                       chunk_size=1024,
                                       max_concurrent_downloads=20)  # Set the number of concurrent downloads

async def main():
    openalex_results_cited = await openalex_search.search(
        # "What are the ways to disrupt healthcare in the next 10 years?", 
        "How can natural language rationales improve reasoning in language models?",
        start_published_date="2022-01-01", end_published_date="2022-01-01")


if __name__ == "__main__":
    asyncio.run(main())
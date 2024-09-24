"""
2024-09-23 21:45:25,325 INFO: Total successful downloads: 121
2024-09-23 21:45:25,325 INFO: Total failed downloads: 59
2024-09-23 21:45:25,325 INFO: Total cache hits: 0
2024-09-23 21:45:25,325 INFO: Average time per query: 29.20 seconds
2024-09-23 21:45:25,325 INFO: Total time for all queries: 262.77 seconds
2024-09-23 21:45:25,325 INFO: Fail rate: 32.78%
"""

import os
import sys
import asyncio
import traceback
import aiohttp
from aiohttp import ClientSession
import json
from typing import List, Dict, Optional

os.chdir(__file__.split('src/')[0])
sys.path.append(os.getcwd())
from src.util.setup_logging import setup_logging
from src.db.local_cache import LocalCache
from src.util.env_util import cfg

logger = setup_logging(__file__, log_level="INFO")

class ExaDownloader:
    def __init__(self, max_concurrent_downloads: int = 50, url_list_retry_rounds: int = 1, use_cache: bool = True):
        self.semaphore = asyncio.Semaphore(max_concurrent_downloads)
        self.url_list_retry_rounds = url_list_retry_rounds
        self.successful_downloads = 0
        self.failed_downloads = 0
        self.cache_hits = 0
        self.use_cache = use_cache
        self.cache = LocalCache() if use_cache else None
        self.api_key = os.environ.get("EXA_SEARCH_API_KEY")
        if not self.api_key:
            raise ValueError("EXA_SEARCH_API_KEY environment variable is not set")
        self.headers = {
            'accept': 'application/json',
            'content-type': 'application/json',
            'x-api-key': self.api_key
        }
        self.exa_api_url = "https://api.exa.ai/contents"

    async def fetch_content_from_exa(self, session: ClientSession, pdf_urls: List[str], openalex_id: str, title: str) -> Optional[tuple]:
        async with self.semaphore:
            for round in range(1, self.url_list_retry_rounds + 1):
                for i, pdf_url in enumerate(pdf_urls, 1):
                    try:
                        payload = {
                            "text": {"maxCharacters": int(1e6)},
                            "ids": [pdf_url],
                            "livecrawl": "fallback",
                            "livecrawlTimeout": 10000
                        }
                        async with session.post(self.exa_api_url, headers=self.headers, json=payload, timeout=60) as response:
                            if response.status == 200:
                                data = await response.json()
                                if data.get('results') and data['results'][0].get('text'):
                                    self.successful_downloads += 1
                                    return data['results'][0]['text'], pdf_url  # Return the text and the successful URL
                            logger.debug(f"URL p{i} ({pdf_url}) failed, status code: {response.status}. Round {round}")
                    except Exception as e:
                        logger.debug(f"URL p{i} ({pdf_url}) failed: {str(e)}. Round {round}")
                    
                    if i < len(pdf_urls):
                        logger.debug(f"Trying URL p{i+1} ({pdf_urls[i]}) round {round}")
                    
            logger.debug(f"All download attempts failed for '{title}' (OpenAlex ID: {openalex_id}). URLs tried: {pdf_urls}")
            self.failed_downloads += 1
            return None, None  # Return None for both text and URL if all attempts fail

    async def process_papers(self, results: List[Dict], cache) -> List[Dict]:
        processed_results = []
        async with aiohttp.ClientSession() as session:
            tasks = []
            for result in results:
                openalex_id = result['meta'].get('id', 'Unknown ID')
                if self.use_cache and self.cache:
                    cached_text = self.cache.get(openalex_id)
                else:
                    cached_text = None

                if cached_text:
                    result['text'] = cached_text
                    result['meta']['text_type'] = 'full_text'  # Update text_type for cache hits
                    processed_results.append(result)
                    self.cache_hits += 1
                else:
                    tasks.append(self.process_single_paper(session, result))
            
            processed_results.extend(await asyncio.gather(*tasks))
        
        logger.debug(f"Exa download statistics: {self.successful_downloads} successful, {self.failed_downloads} failed, {self.cache_hits} cache hits")
        return processed_results

    async def process_single_paper(self, session: ClientSession, result: Dict) -> Dict:
        title = result['meta'].get('title', 'Unknown Title')
        openalex_id = result['meta'].get('id', 'Unknown ID')
        pdf_urls = result['meta'].get('pdf_urls_by_priority', [])

        exa_text, successful_url = await self.fetch_content_from_exa(session, pdf_urls, openalex_id, title)
        
        if exa_text:
            result['text'] = exa_text
            result['meta']['text_type'] = 'full_text'
            result['meta']['successful_pdf_url'] = successful_url  # Add the successful URL to meta
            if self.use_cache and self.cache:
                self.cache.set(openalex_id, exa_text)
        else:
            result['text'] = result.get('text', '')
            result['meta']['successful_pdf_url'] = None  # Set to None if download fails
        
        return result

async def main():
    pdf_url = "https://aclanthology.org/2022.findings-emnlp.508.pdf"
    openalex_id = "example_id"
    title = "Example Paper Title"
    
    exa_downloader = ExaDownloader(
        use_cache=False
    )
    
    results = [{
        'meta': {
            'id': openalex_id,
            'title': title,
            'pdf_urls_by_priority': [pdf_url]
        }
    }]
    
    processed_results = await exa_downloader.process_papers(results, None)
    logger.info(f"Processed results: {json.dumps(processed_results, indent=2)}")

if __name__ == "__main__":
    asyncio.run(main())
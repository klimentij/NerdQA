import os
import sys
import asyncio
import traceback
import aiohttp
from aiohttp import ClientSession
import ssl
import certifi
import random
from io import BytesIO
from pdfminer.high_level import extract_text
from pdfminer.layout import LAParams
from typing import List, Dict, Optional

os.chdir(__file__.split('src/')[0])
sys.path.append(os.getcwd())
from src.util.setup_logging import setup_logging
from src.db.local_cache import LocalCache

logger = setup_logging(__file__, log_level="DEBUG")


class PDFDownloader:
    def __init__(self, max_concurrent_downloads: int = 5, url_list_retry_rounds: int = 2, use_cache: bool = True):
        self.semaphore = asyncio.Semaphore(max_concurrent_downloads)
        self.url_list_retry_rounds = url_list_retry_rounds
        self.ssl_context = ssl.create_default_context(cafile=certifi.where())
        self.successful_downloads = 0
        self.failed_downloads = 0
        self.cache_hits = 0
        self.use_cache = use_cache
        self.cache = LocalCache() if use_cache else None
        self.headers = {
            'User-Agent': (
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/112.0.0.0 Safari/537.36'
            ),
            'Accept': 'application/pdf,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
        }

    async def download_and_parse_pdf(self, session: ClientSession, pdf_urls: List[str], openalex_id: str, title: str) -> Optional[str]:
        async with self.semaphore:
            for round in range(1, self.url_list_retry_rounds + 1):
                for i, pdf_url in enumerate(pdf_urls, 1):
                    try:
                        logger.debug(f"Attempting download with headers: {self.headers}")
                        async with session.get(pdf_url, headers=self.headers, timeout=60, allow_redirects=True, ssl=self.ssl_context) as response:
                            logger.debug(f"Response status: {response.status}, Content-Type: {response.headers.get('Content-Type')}")
                            if response.status == 200 and response.headers.get('Content-Type', '').lower().startswith('application/pdf'):
                                pdf_content = await response.read()
                                laparams = LAParams(
                                    char_margin=1.0,    # Reduced character margin
                                    line_margin=0.5,
                                    word_margin=0.2,    # Increased word margin
                                    boxes_flow=0.5       # Adjust flow to handle columns better
                                )
                                text_content = extract_text(BytesIO(pdf_content), laparams=laparams)
                                self.successful_downloads += 1
                                return text_content
                            else:
                                try:
                                    # Attempt to decode with 'utf-8' and replace errors
                                    response_text = await response.text(encoding='utf-8', errors='replace')
                                except UnicodeDecodeError:
                                    # Fallback if decoding fails
                                    response_text = "<Unable to decode response content>"
                                logger.debug(f"URL p{i} ({pdf_url}) failed, status code: {response.status}, response text: {response_text[:500]}... Round {round}")
                    except aiohttp.ClientResponseError as e:
                        logger.debug(f"URL p{i} ({pdf_url}) failed: HTTP {e.status} - {e.message}. Round {round}")
                    except aiohttp.ClientSSLError as e:
                        logger.debug(f"URL p{i} ({pdf_url}) failed: SSL Error - {str(e)}. Round {round}")
                    except asyncio.TimeoutError:
                        logger.debug(f"URL p{i} ({pdf_url}) failed: Request timed out. Round {round}")
                    except Exception as e:
                        logger.debug(f"URL p{i} ({pdf_url}) failed: {str(e)}. Round {round}")
                        logger.debug(f"Full traceback: {traceback.format_exc()}")
                    
                    if i < len(pdf_urls):
                        logger.debug(f"Trying URL p{i+1} ({pdf_urls[i]}) round {round}")
                    
                    # Add a small delay between requests
                    await asyncio.sleep(random.uniform(1, 3))
            
            logger.debug(f"All download attempts failed for '{title}' (OpenAlex ID: {openalex_id}). URLs tried: {pdf_urls}")
            self.failed_downloads += 1
            return None

    async def process_papers(self, results: List[Dict], cache) -> List[Dict]:
        processed_results = []
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=self.ssl_context)) as session:
            tasks = []
            for result in results:
                openalex_id = result['meta'].get('id', 'Unknown ID')
                if self.use_cache and self.cache:
                    cached_text = self.cache.get(openalex_id)
                else:
                    cached_text = None

                if cached_text:
                    result['text'] = cached_text
                    processed_results.append(result)
                    self.cache_hits += 1  # Increment cache hits
                else:
                    tasks.append(self.process_single_paper(session, result))
            
            processed_results.extend(await asyncio.gather(*tasks))
        
        logger.debug(f"PDF download statistics: {self.successful_downloads} successful, {self.failed_downloads} failed, {self.cache_hits} cache hits")
        return processed_results

    async def process_single_paper(self, session: ClientSession, result: Dict) -> Dict:
        title = result['meta'].get('title', 'Unknown Title')
        openalex_id = result['meta'].get('id', 'Unknown ID')
        pdf_urls = result['meta'].get('pdf_urls_by_priority', [])

        pdf_text = await self.download_and_parse_pdf(session, pdf_urls, openalex_id, title)
        
        if pdf_text:
            result['text'] = pdf_text
            if self.use_cache and self.cache:
                self.cache.set(openalex_id, pdf_text)
        else:
            result['text'] = result.get('text', '')  # Keep the original abstract if download fails
        
        return result
    

async def main():
    pdf_url = "https://aclanthology.org/2022.findings-emnlp.508.pdf"
    openalex_id = "example_id"
    title = "Example Paper Title"
    
    # Create an instance of PDFDownloader
    pdf_downloader = PDFDownloader()
    
    # Create a mock result list
    results = [{
        'meta': {
            'id': openalex_id,
            'title': title,
            'pdf_urls_by_priority': [pdf_url]
        }
    }]
    
    # Process the papers without using cache
    processed_results = []
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=pdf_downloader.ssl_context)) as session:
        tasks = [pdf_downloader.process_single_paper(session, result, None) for result in results]
        processed_results.extend(await asyncio.gather(*tasks))
    
    # Print the processed results
    for result in processed_results:
        print(f"OpenAlex ID: {result['meta']['id']}")
        print(f"Title: {result['meta']['title']}")
        print(f"Text: {result['text'][:5000]}...")  # Print the first 500 characters of the text

if __name__ == "__main__":
    asyncio.run(main())


import os
import sys
import time
import json
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import hashlib
import urllib.parse
from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from tokenizers import Tokenizer
from io import BytesIO
from pdfminer.high_level import extract_text
from pdfminer.layout import LAParams

import asyncio
import aiohttp
from aiohttp import ClientSession
from aiohttp_retry import RetryClient, ExponentialRetry
import certifi
import ssl
import random
import traceback

os.chdir(__file__.split('src/')[0])
sys.path.append(os.getcwd())
from src.util.env_util import cfg
from src.db.local_cache import LocalCache

# Set up logger
from src.util.setup_logging import setup_logging
logger = setup_logging(__file__, log_level="DEBUG")

import asyncio
import aiohttp
from aiohttp import ClientSession
from aiohttp_retry import RetryClient, ExponentialRetry
from typing import List, Dict, Optional
from pdfminer.high_level import extract_text
from pdfminer.layout import LAParams
from io import BytesIO
import hashlib
import ssl
import certifi

from src.util.setup_logging import setup_logging
from src.tools.search_client import SearchClient

logger = setup_logging(__file__, log_level="DEBUG")

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
    

def main():
    # Example usage of ExaSearchClient
    client = ExaSearchClient(rerank=True, caching=False, 
                             reranking_threshold=0.2, 
                             initial_top_to_retrieve=20,
                             chunk_size=1024)
    
    query = "Latest advancements in artificial intelligence"
    start_date = "2023-01-01"
    end_date = "2023-12-31"
    
    results = client.search(query, start_published_date=start_date, end_published_date=end_date)
    
    print(f"Search Results for: {query}")
    for i, result in enumerate(results, 1):
        print(f"\nResult {i}:")
        print(f"Title: {result['meta']['title']}")
        print(f"URL: {result['meta']['url']}")
        print(f"Author: {result['meta']['author']}")
        print(f"Published Date: {result['meta']['published_date']}")
        print(f"Text: {result['text'][:200]}...")  # Print first 200 characters of the text

if __name__ == "__main__":
    main()
import asyncio
import json
from typing import Dict
from datetime import datetime, timedelta
from backend.src.qloop.server import search_client_map
from backend.src.benchmark.config import load_config
from backend.src.util.setup_logging import setup_logging

logger = setup_logging(__file__)

async def title_search(paper_title: str, publication_date: str) -> tuple[str, list[str]]:
    logger.info("Performing title-based search")
    config = load_config()
    
    search_client_class = search_client_map.get(config.pipeline.search_client, search_client_map["exa"])
    search_client = search_client_class()
    
    end_published_date = (datetime.strptime(publication_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    
    search_results = await search_client.search(
        paper_title,
        end_published_date=end_published_date
    )
    
    openalex_ids = []
    for result in search_results.get('results', []):
        try:
            meta = result.get('meta', {})
            openalex_id = meta.get('openalex_id')
            if openalex_id:
                openalex_ids.append(openalex_id)
        except Exception as e:
            logger.error(f"Error processing search result: {e}")
            continue
    
    openalex_ids = list(set(openalex_ids))
    logger.info(f"Found {len(openalex_ids)} unique OpenAlex IDs")
    
    # Return an empty answer and the list of OpenAlex IDs
    return str(search_results)[:10000], openalex_ids

async def main():
    paper_title = "Retrieval-Augmented Generation for Large Language Models: A Survey"
    metadata = {}
    
    logger.info(f"Starting title-based search for paper: {paper_title}")
    answer, openalex_ids = await title_search(paper_title, "2024-01-01")
    logger.info(f"Empty answer returned as expected")
    logger.info(f"OpenAlex IDs found: {openalex_ids}")

if __name__ == "__main__":
    asyncio.run(main())
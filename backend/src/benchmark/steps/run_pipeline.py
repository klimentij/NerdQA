import asyncio
import aiohttp
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple

from backend.src.util.setup_logging import setup_logging
from backend.src.benchmark.config import PipelineConfig

logger = setup_logging(__file__, log_level="DEBUG")

async def run_pipeline_request(data: Dict[str, Any], config: PipelineConfig) -> Tuple[Any, Any]:
    url = "http://localhost:8000/run_pipeline"
    retries = 0
    max_retries = 3
    retry_delay = 5
    timeout = 12000

    params = {
        "question": data["question_generated"],
        "iterations": config.iterations,
        "num_queries": config.num_queries,
        "end_date": (datetime.strptime(data["meta"]["publication_date"], "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d"),
        "search_client": config.search_client
    }

    while retries < max_retries:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=timeout) as response:
                    if response.status == 200:
                        result = await response.json()
                        return result["answer"], result["full_citation_tree"]
                    else:
                        logger.error(f"Error response: {response.status}")
                        return None, None
        except aiohttp.ClientError as e:
            logger.error(f"Request error: {e}")
            retries += 1
            if retries < max_retries:
                logger.info(f"Retrying in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
            else:
                logger.error("Max retries reached. Giving up.")
                return None, None
        except asyncio.TimeoutError:
            logger.error(f"Timeout: No response received within {timeout} seconds")
            return None, None
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return None, None

    return None, None
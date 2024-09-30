import asyncio
import aiohttp
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple

from backend.src.util.setup_logging import setup_logging
from backend.src.benchmark.config import PipelineConfig

logger = setup_logging(__file__, log_level="DEBUG")

async def run_pipeline_request(data: Dict[str, Any], config: PipelineConfig) -> Tuple[Any, Any]:
    start_pipeline_url = "http://localhost:8000/start_pipeline"
    status_url = "http://localhost:8000/pipeline_status/"
    retries = 0
    max_retries = 3
    retry_delay = 5
    timeout = 12000

    params = {
        "question": data["question_generated"],
        "iterations": config.iterations,
        "num_queries": config.num_queries,
        "end_date": (datetime.strptime(data["publication_date"], "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d"),
        "search_client": config.search_client
    }

    async with aiohttp.ClientSession() as session:
        while retries < max_retries:
            try:
                # Start the pipeline
                async with session.post(start_pipeline_url, json=params, timeout=timeout) as response:
                    if response.status == 200:
                        result = await response.json()
                        session_id = result["session_id"]
                    else:
                        logger.error(f"Error starting pipeline: {response.status}")
                        return None, None

                # Poll for pipeline status
                while True:
                    async with session.get(status_url + session_id, timeout=timeout) as response:
                        if response.status == 200:
                            status = await response.json()
                            if status["status"] == "completed":
                                return status["final_answer"], status["full_citation_tree"]
                            elif status["status"] == "running":
                                await asyncio.sleep(1) 
                            else:
                                logger.error(f"Unexpected pipeline status: {status['status']}")
                                return None, None
                        else:
                            logger.error(f"Error checking pipeline status: {response.status}")
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
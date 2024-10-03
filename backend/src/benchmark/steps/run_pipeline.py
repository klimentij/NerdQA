import asyncio
import aiohttp
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple, List

from backend.src.util.setup_logging import setup_logging
from backend.src.benchmark.config import PipelineConfig, BenchmarkConfig
from backend.src.benchmark.steps.baselines.no_rag import generate_no_rag_answer
from backend.src.benchmark.steps.baselines.naive_rag import generate_naive_rag_answer
from backend.src.benchmark.steps.baselines.title import title_search
from backend.src.qnote.pipeline import run_pipeline as qnote_run_pipeline

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

def collect_openalex_ids(references: Dict[str, Any]) -> List[str]:
    """Recursively collect all openalex_id values from the references tree."""
    openalex_ids = []
    
    def traverse(node):
        if isinstance(node, dict):
            if 'openalex_id' in node:
                openalex_ids.append(node['openalex_id'])
            for value in node.values():
                traverse(value)
        elif isinstance(node, list):
            for item in node:
                traverse(item)
    
    traverse(references)
    return openalex_ids

async def run_pipeline_for_paper(paper: Dict[str, Any], config: BenchmarkConfig, metadata: Dict[str, str]) -> Dict[str, Any]:
    if config.system == "ade":
        answer, citation_tree = await run_pipeline_request(paper, config.pipeline)
        paper['pipeline_answer'] = answer
        paper['pipeline_references'] = citation_tree
        paper['pipeline_source_papers'] = list(set(collect_openalex_ids(citation_tree)))
    elif config.system == "qnote":
        result = await qnote_run_pipeline(
            main_question=paper["question_generated"],
            iterations=config.pipeline.iterations,
            num_queries=config.pipeline.num_queries,
            start_date=None,  # Adjust if needed
            end_date=(datetime.strptime(paper["publication_date"], "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d"),
            download_full_text=config.pipeline.download_full_text,
            search_caching=config.pipeline.search_caching,
            query_llm=config.pipeline.query_llm,
            initial_top_to_retrieve=config.pipeline.initial_top_to_retrieve
        )   
        paper['pipeline_answer'] = result['answer']
        paper['pipeline_references'] = result['citation_tree']
        paper['pipeline_source_papers'] = result['all_relevant_source_ids']
        # You can add more fields from the result if needed
    elif config.system == "baseline_no_rag":
        answer = await generate_no_rag_answer(paper["question_generated"], metadata)
        paper['pipeline_answer'] = answer
    elif config.system == "baseline_naive_rag":
        answer, openalex_ids = await generate_naive_rag_answer(paper["question_generated"], paper["publication_date"], metadata)
        paper['pipeline_answer'] = answer
        paper['pipeline_source_papers'] = openalex_ids
    elif config.system == "baseline_title":
        answer, openalex_ids = await title_search(paper["title"], paper["publication_date"])
        paper['pipeline_answer'] = answer
        paper['pipeline_source_papers'] = openalex_ids
    else:
        raise ValueError(f"Unknown system: {config.system}")
    return paper
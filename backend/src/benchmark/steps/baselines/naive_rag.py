import asyncio
from typing import Dict, Any
from datetime import datetime, timedelta
import re
import json
from backend.src.llm.completion import Completion
from backend.src.benchmark.config import load_config
from backend.src.qloop.server import search_client_map
from backend.src.util.setup_logging import setup_logging

logger = setup_logging(__file__)

async def generate_naive_rag_answer(question: str, publication_date: str, metadata: Dict[str, str]) -> str:
    logger.info("Generating naive RAG answer")
    config = load_config()
    
    # Initialize the search client based on the config
    search_client_class = search_client_map.get(config.pipeline.search_client, search_client_map["exa"])
    search_client = search_client_class()
    
    # Calculate end_date as one day before the paper's publication date
    end_published_date = (datetime.strptime(publication_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    
    # Perform the search
    search_results = await search_client.search(
        question,
        end_published_date=end_published_date
    )
    
    logger.info("Generating answer using the NaiveRAG skill")
    skill = Completion(('Benchmark', 'Baseline', 'NaiveRAG'))
    result = await asyncio.to_thread(skill.complete,
        prompt_inputs={
            "MAIN_QUESTION": question,
            "SEARCH_RESULTS": search_results,
        },
        completion_kwargs={
            "metadata": metadata,
        }
    )
    
    try:
        content_dict = json.loads(result.content)
        answer = content_dict["answer"]
    except (json.JSONDecodeError, KeyError):
        logger.error(f"Failed to parse result content: {result.content}")
        raise ValueError("Invalid response format from NaiveRAG skill")

    # Parse E.. ids from inline references
    evidence_ids = re.findall(r'E(\d+)', answer)
    evidence_ids = list(set([f'E{id}' for id in evidence_ids]))
    logger.info(f"Extracted evidence IDs: {evidence_ids}")

    # Convert E.. ids to openalex_ids
    openalex_ids = []
    for result in search_results.get('results', []):
        try:
            result_id = result.get('id', '')
            if result_id in evidence_ids:
                meta = result.get('meta', {})
                openalex_id = meta.get('openalex_id')
                if openalex_id:
                    openalex_ids.append(openalex_id)
        except Exception as e:
            logger.error(f"Error processing search result: {e}")
            continue
    
    openalex_ids = list(set(openalex_ids))
    logger.info(f"Generated answer with {len(openalex_ids)} evidence IDs")
    return answer, openalex_ids

async def main():
    question = "What is RAG in LLMs"
    metadata = {}
    
    logger.info(f"Starting naive RAG answer generation for question: {question}")
    answer, e_ids = await generate_naive_rag_answer(question, "2024-01-01", metadata)
    logger.info(f"Answer generated: {answer[:50]}...")  # Log first 50 characters of the answer
    logger.info(f"Evidence IDs found: {e_ids}")

if __name__ == "__main__":
    asyncio.run(main())
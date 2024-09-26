import asyncio
import websockets
import json
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
from typing import Dict, Any, Tuple, List

from backend.src.util.setup_logging import setup_logging
from backend.src.llm.completion import Completion
from backend.src.benchmark.config import BenchmarkConfig, EvaluationConfig
import time

logger = setup_logging(__file__, log_level="DEBUG")

class ScoreDetail(BaseModel):
    reasoning: str
    score: int = Field(..., ge=1, le=10)

class EvaluationScores(BaseModel):
    accuracy: ScoreDetail
    completeness: ScoreDetail
    relevance: ScoreDetail
    evidence_quality: ScoreDetail
    clarity: ScoreDetail
    logical_structure: ScoreDetail
    evidence_support: ScoreDetail
    depth_of_analysis: ScoreDetail
    objectivity: ScoreDetail
    synthesis: ScoreDetail

class EvaluationResponse(BaseModel):
    scores: EvaluationScores

async def connect_and_send(data: Dict[str, Any], config: EvaluationConfig) -> Tuple[Any, Any]:
    uri = "ws://localhost:8000/ws"
    retries = 0
    max_retries = 3
    retry_delay = 5
    timeout = 1200
    while retries < max_retries:
        try:
            async with websockets.connect(uri, ping_interval=None) as websocket:
                input_data = {
                    "question": data["question_generated"],
                    "iterations": config.iterations,
                    "num_queries": config.num_queries,
                    "end_date": (datetime.strptime(data["meta"]["publication_date"], "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d"),
                    "search_client": config.search_client
                }

                await websocket.send(json.dumps(input_data))
                logger.info(f"Sent: {input_data}")

                try:
                    async with asyncio.timeout(timeout):
                        while True:
                            response = await websocket.recv()
                            logger.info(f"Received: {str(response)[:1000]}")
                            response_data = json.loads(response)
                            if response_data.get("type") == "answer":
                                return response_data["data"], response_data.get("full_citation_tree", {})
                except asyncio.TimeoutError:
                    logger.error(f"Timeout: No response received within {timeout} seconds")
                    return None, None
        except websockets.exceptions.ConnectionClosedError as e:
            logger.error(f"Connection closed unexpectedly: {e}")
            retries += 1
            if retries < max_retries:
                logger.info(f"Retrying in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
            else:
                logger.error("Max retries reached. Giving up.")
                return None, None
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return None, None

    return None, None

async def evaluate_answer(paper: Dict[str, Any], config: BenchmarkConfig, metadata: Dict[str, str]) -> Tuple[EvaluationResponse, float]:
    logger.info("Evaluating answer using the Eval skill")
    skill = Completion(('BenchPaperCompress', 'Eval'))
    
    input_data = {
        "question_generated": paper["question_generated"],
        "golden_answer_generated": paper["golden_answer_generated"],
        "eval_answer": paper["eval_answer"],
        "eval_references": paper["eval_references"]
    }
    
    result = await asyncio.to_thread(skill.complete,
        prompt_inputs={"INPUT": json.dumps(input_data)},
        completion_kwargs={
            "metadata": metadata,
            "model": config.evaluation.eval_llm
        }
    )   
    
    try:
        content_dict = json.loads(result.content)
        evaluation_response = EvaluationResponse(**content_dict)
        
        scores = evaluation_response.scores
        total_score = sum(getattr(scores, field).score for field in scores.__fields__)
        average_score = total_score / len(scores.__fields__)
        
        return evaluation_response, average_score
    except json.JSONDecodeError:
        logger.error(f"Failed to parse result content: {result.content}")
        raise ValueError("Invalid response format from Eval skill")

async def evaluate_answers(papers_with_qa: List[Dict[str, Any]], config: BenchmarkConfig) -> List[Dict[str, Any]]:
    pipeline_start_ts = int(time.time())
    trace_name = f"BM EvalADE for {len(papers_with_qa)} papers"
    trace_id = f"T{pipeline_start_ts}"
    session_id = f"S{pipeline_start_ts}"

    metadata = create_metadata(trace_name, trace_id, session_id)

    async def process_paper(paper):
        answer, citation_tree = await connect_and_send(paper, config.evaluation)
        paper['eval_answer'] = answer
        paper['eval_references'] = citation_tree
        evaluation, average_score = await evaluate_answer(paper, config, metadata)
        paper['evaluation'] = evaluation.dict()
        paper['average_score'] = average_score
        return paper

    # Create tasks for processing each paper
    tasks = [process_paper(paper) for paper in papers_with_qa]
    
    # Run all tasks concurrently
    processed_papers = await asyncio.gather(*tasks)

    return processed_papers

def create_metadata(trace_name: str, trace_id: str, session_id: str) -> Dict[str, str]:
    return {
        "trace_name": trace_name,
        "trace_id": trace_id,
        "trace_user_id": "Benchmark",
        "session_id": session_id
    }
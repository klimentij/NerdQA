import asyncio
import websockets
import json
import os
import sys
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
from typing import Dict, Any, Tuple

os.chdir(__file__.split('src/')[0])
sys.path.append(os.getcwd())

from src.util.setup_logging import setup_logging
from src.llm.completion import Completion

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

async def connect_and_send(data, max_retries=3, retry_delay=5):
    uri = "ws://localhost:8000/ws"
    retries = 0
    while retries < max_retries:
        try:
            async with websockets.connect(uri, ping_interval=None) as websocket:
                input_data = {
                    "question": data["question_generated"] + "_",
                    "iterations": 1,
                    "num_queries": 1,
                    "end_date": (datetime.strptime(data["meta"]["publication_date"], "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d"),
                    "search_client": "openalex"
                }

                await websocket.send(json.dumps(input_data))
                logger.info(f"Sent: {input_data}")

                final_answer = None
                citation_tree = None
                try:
                    async with asyncio.timeout(1200):  # 20 minutes timeout
                        while True:
                            response = await websocket.recv()
                            logger.info(f"Received: {str(response)[:1000]}")
                            response_data = json.loads(response)
                            if response_data.get("type") == "answer":
                                final_answer = response_data["data"]
                                citation_tree = response_data.get("full_citation_tree", {})
                                return final_answer, citation_tree
                except asyncio.TimeoutError:
                    logger.error("Timeout: No response received within 20 minutes")
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

async def evaluate_answer(paper: Dict[str, Any]) -> Tuple[EvaluationResponse, float]:
    logger.info("Evaluating answer using the Eval skill")
    skill = Completion(('BenchPaperCompress', 'Eval'))
    
    input_data = {
        "question_generated": paper["question_generated"],
        "golden_answer_generated": paper["golden_answer_generated"],
        "used_snippets_with_context": paper["used_snippets_with_context"],
        "eval_answer": paper["eval_answer"],
        "eval_references": paper["eval_references"]
    }
    
    result = skill.complete(
        prompt_inputs={"INPUT": json.dumps(input_data)},
        completion_kwargs={"metadata": {}}  # Add appropriate metadata if needed
    )
    
    try:
        content_dict = json.loads(result.content)
        evaluation_response = EvaluationResponse(**content_dict)
        
        # Calculate average score
        scores = evaluation_response.scores
        total_score = sum(getattr(scores, field).score for field in scores.__fields__)
        average_score = total_score / len(scores.__fields__)
        
        return evaluation_response, average_score
    except json.JSONDecodeError:
        logger.error(f"Failed to parse result content: {result.content}")
        raise ValueError("Invalid response format from Eval skill")

async def main():
    # Load seed papers
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
    with open(os.path.join(data_dir, 'seed_papers_with_qa.json'), 'r') as f:
        seed_papers = json.load(f)

    # Take up to 2 records
    selected_papers = seed_papers[:2]

    # Process papers in parallel
    tasks = [connect_and_send(paper) for paper in selected_papers]
    results = await asyncio.gather(*tasks)

    # Add server answers and references to the dictionaries
    for paper, result in zip(selected_papers, results):
        answer, citation_tree = result
        paper['eval_answer'] = answer
        paper['eval_references'] = citation_tree

        # Evaluate the answer
        evaluation, average_score = await evaluate_answer(paper)
        paper['evaluation'] = evaluation.dict()
        paper['average_score'] = average_score

    # Save results
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'runs')
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    output_file = os.path.join(output_dir, f'{os.path.basename(__file__)}.json')
    with open(output_file, 'w') as f:
        json.dump(selected_papers, f, indent=2)

    logger.info(f"Results saved to {output_file}")

# Run the client
asyncio.get_event_loop().run_until_complete(main())
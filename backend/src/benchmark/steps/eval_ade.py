import asyncio
import json
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

def create_metadata(trace_name: str, trace_id: str, session_id: str) -> Dict[str, str]:
    return {
        "trace_name": trace_name,
        "trace_id": trace_id,
        "trace_user_id": "Benchmark",
        "session_id": session_id
    }
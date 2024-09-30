import json
import time
from typing import Dict, Any, List

from backend.src.benchmark.config import QuestionGenerationConfig
from backend.src.llm.completion import Completion
from backend.src.util.setup_logging import setup_logging

logger = setup_logging(__file__)

def create_metadata(trace_name: str, trace_id: str, session_id: str) -> Dict[str, str]:
    return {
        "trace_name": trace_name,
        "trace_id": trace_id,
        "trace_user_id": "Benchmark",
        "session_id": session_id
    }

def generate_question(paper_info: Dict[str, Any], metadata: Dict[str, str]) -> str:
    logger.info("Generating question using the Question skill")
    skill = Completion(('Benchmark', 'Question'))
    
    result = skill.complete(
        prompt_inputs={"PAPER": json.dumps(paper_info)},
        completion_kwargs={
            "metadata": metadata,
        }
    )
    
    try:
        content_dict = json.loads(result.content)
        return content_dict["question"]
    except (json.JSONDecodeError, KeyError):
        logger.error(f"Failed to parse result content: {result.content}")
        raise ValueError("Invalid response format from Question skill")

def generate_questions(seed_papers: List[Dict[str, Any]], config: QuestionGenerationConfig) -> List[Dict[str, Any]]:
    processed_papers = []
    for i, paper in enumerate(seed_papers[:config.max_papers_to_process]):
        pipeline_start_ts = int(time.time())
        trace_name = f"BM GenQuestion for {paper['title']}"
        trace_id = f"T{pipeline_start_ts}_{i+1}"
        session_id = f"S{pipeline_start_ts}_{i+1}"

        paper_info = {
            "title": paper['title'],
            "topic": paper.get('topic', ''),
            "keywords": paper.get('keywords', []),
            "concepts": paper.get('concepts', []),
            "text": paper['text']
        }

        metadata = create_metadata(trace_name, trace_id, session_id)
        question = generate_question(paper_info, metadata)

        paper['question_generated'] = question
        processed_papers.append(paper)

    return processed_papers
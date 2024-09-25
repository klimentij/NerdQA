import json
import time
import re
from typing import Dict, Any, List
from pydantic import BaseModel

from backend.src.llm.completion import Completion
from backend.src.util.setup_logging import setup_logging
from backend.src.util.chunking_util import Chunker
from backend.src.benchmark.config import BenchmarkConfig

logger = setup_logging(__file__)

class ReportGenerationOutput(BaseModel):
    reflection: str
    report: str

class QuestionGenerationOutput(BaseModel):
    reflection: str
    question: str

def create_metadata(trace_name: str, trace_id: str, session_id: str) -> Dict[str, str]:
    return {
        "trace_name": trace_name,
        "trace_id": trace_id,
        "trace_user_id": "Benchmark",
        "session_id": session_id
    }

def generate_report(formatted_snippets: str, metadata: Dict[str, str]) -> ReportGenerationOutput:
    logger.info("Generating report using the Report skill")
    skill = Completion(('BenchPaperCompress', 'Report'))
    
    result = skill.complete(
        prompt_inputs={"PAPER": formatted_snippets},
        completion_kwargs={
            "metadata": metadata,
        }
    )
    
    try:
        content_dict = json.loads(result.content)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse result content: {result.content}")
        raise ValueError("Invalid response format from Report skill")
    
    return ReportGenerationOutput(**content_dict)

def generate_question(report: str, metadata: Dict[str, str]) -> QuestionGenerationOutput:
    logger.info("Generating question using the Question skill")
    skill = Completion(('BenchPaperCompress', 'Question'))
    
    result = skill.complete(
        prompt_inputs={"REPORT": report},
        completion_kwargs={
            "metadata": metadata,
        }
    )
    
    try:
        content_dict = json.loads(result.content)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse result content: {result.content}")
        raise ValueError("Invalid response format from Question skill")
    
    return QuestionGenerationOutput(**content_dict)

def generate_qa_pairs(seed_papers: List[Dict[str, Any]], config) -> List[Dict[str, Any]]:
    chunker = Chunker(chunk_size=config.chunk_size, chunk_overlap=config.chunk_overlap)

    processed_papers = []
    for i, paper in enumerate(seed_papers[:config.max_papers_to_process]):
        pipeline_start_ts = int(time.time())
        trace_name = f"BM GenQA for {paper['meta']['title']}"
        trace_id = f"T{pipeline_start_ts}_{i+1}"
        session_id = f"S{pipeline_start_ts}_{i+1}"

        paper_text = paper['text']
        chunks = chunker.chunk_text(paper_text, {})
        snippets = {f"s{i+1}": chunk['text'] for i, chunk in enumerate(chunks)}
        
        paper_with_snippets_no_text = {k: v for k, v in paper.items() if k != 'text'}
        paper_with_snippets_no_text['formatted_snippets'] = json.dumps(snippets)
        paper['snippets'] = snippets

        metadata = create_metadata(trace_name, trace_id, session_id)
        report_result = generate_report(json.dumps(paper_with_snippets_no_text), metadata)
        question_result = generate_question(report_result.report, metadata)

        paper['question_generated'] = question_result.question
        paper['golden_answer_generated'] = report_result.report

        used_snippet_ids = set(map(int, re.findall(r'【s(\d+)】', report_result.report)))
        max_snippet_id = len(snippets)
        used_snippets_with_context = set()
        for snippet_id in used_snippet_ids:
            for context_id in range(max(1, snippet_id - 1), min(max_snippet_id, snippet_id + 2)):
                used_snippets_with_context.add(context_id)
        
        paper['used_snippets_with_context'] = {f"s{i}": snippets[f"s{i}"] for i in sorted(used_snippets_with_context)}
        processed_papers.append(paper)

    return processed_papers
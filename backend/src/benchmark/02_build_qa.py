import os
import sys
import time
import json
from typing import Dict, Any, List
from pydantic import BaseModel, Field

# Set up paths
os.chdir(__file__.split('src/')[0])
sys.path.append(os.getcwd())

from src.llm.completion import Completion
from src.util.setup_logging import setup_logging
from src.util.chunking_util import Chunker

logger = setup_logging(__file__)

# Pydantic models (unchanged)
class ReportGenerationOutput(BaseModel):
    reflection: str
    report: str

class QuestionGenerationOutput(BaseModel):
    reflection: str
    question: str

class Config(BaseModel):
    max_papers_to_process: int = 2
    chunk_size: int = 256
    chunk_overlap: int = 0

config = Config()

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
        completion_kwargs={"metadata": metadata}
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
        completion_kwargs={"metadata": metadata}
    )
    
    try:
        content_dict = json.loads(result.content)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse result content: {result.content}")
        raise ValueError("Invalid response format from Question skill")
    
    return QuestionGenerationOutput(**content_dict)

def main():
    # Load the seed papers JSON file
    input_file = os.path.join(os.path.dirname(__file__), "data", "seed_papers.json")
    with open(input_file, 'r') as f:
        seed_papers = json.load(f)

    # Initialize the Chunker with chunk size and overlap from config
    chunker = Chunker(chunk_size=config.chunk_size, chunk_overlap=config.chunk_overlap)

    # Process the first max_papers_to_process papers from the list
    for i, paper in enumerate(seed_papers[:config.max_papers_to_process]):
        # Create common metadata for the entire pipeline
        pipeline_start_ts = int(time.time())
        trace_name = f"BM GenQA for {paper['meta']['title']}"
        trace_id = f"T{pipeline_start_ts}" + f"_{i+1}"
        session_id = f"S{pipeline_start_ts}" + f"_{i+1}"

        # Use the pre-parsed text from the JSON file
        paper_text = paper['text']

        # Use the chunker to produce snippets
        chunks = chunker.chunk_text(paper_text, {})
        snippets = [f"s{i+1}: {chunk['text']}" for i, chunk in enumerate(chunks)]
        
        paper_with_snippets_no_text = {k: v for k, v in paper.items() if k != 'text'}
        paper_with_snippets_no_text['formatted_snippets'] = "\n".join(snippets)
        paper['snippets'] = snippets

        # Generate report using the Report skill
        metadata = create_metadata(trace_name, trace_id, session_id)
        report_result = generate_report(json.dumps(paper_with_snippets_no_text), metadata)

        # Generate question based on the report
        question_result = generate_question(report_result.report, metadata)

        # Add generated report and question to the paper data
        paper['question_generated'] = question_result.question
        paper['report_generated'] = report_result.report

    # Save the updated paper data to a new JSON file
    output_file = os.path.join(os.path.dirname(__file__), "data", "seed_papers_with_qa.json")
    with open(output_file, 'w') as f:
        json.dump(seed_papers[:config.max_papers_to_process], f, indent=2)

    logger.info("Generated report and question for the first two papers")
    logger.info(f"Results saved to: {output_file}")

if __name__ == "__main__":
    main()
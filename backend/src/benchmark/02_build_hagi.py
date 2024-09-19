import os
import sys
import requests
import io
import time
from PyPDF2 import PdfReader
from typing import Dict, Any, List
from pydantic import BaseModel, Field

# Set up paths
os.chdir(__file__.split('src/')[0])
sys.path.append(os.getcwd())

from src.llm.completion import Completion
from src.util.setup_logging import setup_logging

logger = setup_logging(__file__)

class QAOutput(BaseModel):
    reflection: str
    question: str
    answer: List[Dict[str, Any]]

def create_metadata(trace_name: str, trace_id: str, session_id: str) -> Dict[str, str]:
    return {
        "trace_name": trace_name,
        "trace_id": trace_id,
        "trace_user_id": "Benchmark",
        "session_id": session_id
    }

def download_pdf(url: str) -> bytes:
    logger.info(f"Downloading PDF from {url}")
    response = requests.get(url)
    response.raise_for_status()
    return response.content

def pdf_to_text(pdf_content: bytes) -> str:
    logger.info("Converting PDF to text")
    pdf_file = io.BytesIO(pdf_content)
    pdf_reader = PdfReader(pdf_file)
    text = ""
    for page in pdf_reader.pages:
        text += page.extract_text()
    return text

def generate_agi_level_qa(paper_text: str, metadata: Dict[str, str]) -> QAOutput:
    logger.info("Generating HypAGI QA using the QA skill")
    skill = Completion(('BenchGenHypAGI', 'QA'))
    
    result = skill.complete(
        prompt_inputs={"PAPER": paper_text},
        completion_kwargs={"metadata": metadata}
    )
    
    # Parse the result.content string into a dictionary
    import json
    try:
        content_dict = json.loads(result.content)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse result content: {result.content}")
        raise ValueError("Invalid response format from QA skill")
    
    return QAOutput(**content_dict)

def main():
    # 1. Download the PDF
    pdf_url = "https://arxiv.org/pdf/2203.11171"
    pdf_content = download_pdf(pdf_url)

    # Create common metadata for the entire pipeline
    pipeline_start_ts = int(time.time())
    trace_name = f"Build HypAGI QA from {pdf_url}"
    trace_id = f"T{pipeline_start_ts}"
    session_id = f"S{pipeline_start_ts}"

    # 2. Convert PDF to text
    paper_text = pdf_to_text(pdf_content)

    # 3. Generate AGI-level QA using the QA skill
    metadata = create_metadata(trace_name, trace_id, session_id)
    qa_result = generate_agi_level_qa(paper_text, metadata)

    # 4. Log the generated question and answer
    logger.info("Generated question:")
    logger.info(qa_result.question)
    
    logger.info("Generated answer:")
    for item in qa_result.answer:
        logger.info(f"Sentence: {item['sentence']}")
        logger.info(f"Supporting quotes: {item['supporting_quotes']}")

if __name__ == "__main__":
    main()
import os
import sys
import requests
import io
import time
from PyPDF2 import PdfReader
from typing import Dict, Any, List
from pydantic import BaseModel, Field
import re
import json

# Set up paths
os.chdir(__file__.split('src/')[0])
sys.path.append(os.getcwd())

from src.llm.completion import Completion
from src.util.setup_logging import setup_logging

logger = setup_logging(__file__)

# Pydantic model for report generation output
class ReportGenerationOutput(BaseModel):
    reflection: str
    report: str  # Updated field name to match the response format

# Pydantic model for question generation output
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

def split_into_sentences(text: str, min_length: int = 100) -> list:
    # Regular expression to split text into sentences
    sentence_endings = re.compile(r'(?<!\w\.\w.)(?<![A-Z][a-z]\.)(?<=\.|\?)\s')
    sentences = sentence_endings.split(text)
    # Filter sentences to ensure they meet the minimum length requirement
    return [sentence.strip() for sentence in sentences if sentence and len(sentence) >= min_length]

def generate_report(formatted_snippets: str, metadata: Dict[str, str]) -> ReportGenerationOutput:
    logger.info("Generating report using the Report skill")
    skill = Completion(('BenchPaperCompress', 'Report'))
    
    result = skill.complete(
        prompt_inputs={"PAPER": formatted_snippets},
        completion_kwargs={"metadata": metadata}
    )
    
    # Parse the result.content string into a dictionary
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
    
    # Parse the result.content string into a dictionary
    try:
        content_dict = json.loads(result.content)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse result content: {result.content}")
        raise ValueError("Invalid response format from Question skill")
    
    return QuestionGenerationOutput(**content_dict)

def main():
    # 1. Download the PDF
    # pdf_url = "https://arxiv.org/pdf/2201.11903"
    pdf_url = "https://arxiv.org/pdf/2408.06292"
    pdf_content = download_pdf(pdf_url)

    # Create common metadata for the entire pipeline
    pipeline_start_ts = int(time.time())
    trace_name = f"Paper Compress BM from {pdf_url}"
    trace_id = f"T{pipeline_start_ts}"
    session_id = f"S{pipeline_start_ts}"

    # 2. Convert PDF to text
    paper_text = pdf_to_text(pdf_content)

    # 3. Split paper text into indexed snippets
    snippets = split_into_sentences(paper_text)

    # Convert snippets to the desired string format
    formatted_snippets = "\n".join([f"s{i+1}: {snippet}" for i, snippet in enumerate(snippets)])

    # 4. Generate report using the Report skill
    metadata = create_metadata(trace_name, trace_id, session_id)
    report_result = generate_report(formatted_snippets, metadata)

    # 5. Log the resulting report
    logger.info("Generated report:")
    logger.info(report_result.report)

    # 6. Generate question based on the report
    question_result = generate_question(report_result.report, metadata)

    # 7. Log the resulting question
    logger.info("Generated question:")
    logger.info(question_result.question)

if __name__ == "__main__":
    main()
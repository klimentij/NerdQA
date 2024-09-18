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

# Pydantic models for quote generation output
class QuoteGenerationOutput(BaseModel):
    reflection: str
    quotes: List[str]
    references: List[str]

# Pydantic model for research question output
class ResearchQuestionOutput(BaseModel):
    reflection: str
    question: str

def create_metadata(trace_name: str) -> Dict[str, str]:
    pipeline_start_ts = int(time.time())
    return {
        "trace_name": trace_name,
        "trace_id": f"T{pipeline_start_ts}",
        "trace_user_id": "Benchmark",
        "session_id": f"S{pipeline_start_ts}"
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

def generate_quotes(paper_text: str, pdf_url: str) -> QuoteGenerationOutput:
    logger.info("Generating quotes using the Quotes skill")
    skill = Completion(('BenchGen', 'Quotes'))
    
    metadata = create_metadata(f"Generate quotes for {pdf_url}")
    
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
        raise ValueError("Invalid response format from Quotes skill")
    
    return QuoteGenerationOutput(**content_dict)

def generate_research_question(quotes: List[str]) -> ResearchQuestionOutput:
    logger.info("Generating research question using the Question skill")
    skill = Completion(('BenchGen', 'Question'))
    
    metadata = create_metadata("Generate research question")
    
    result = skill.complete(
        prompt_inputs={"QUOTES": "\n".join(quotes)},
        completion_kwargs={"metadata": metadata}
    )
    
    # Parse the result.content string into a dictionary
    import json
    try:
        content_dict = json.loads(result.content)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse result content: {result.content}")
        raise ValueError("Invalid response format from Question skill")
    
    return ResearchQuestionOutput(**content_dict)

def main():
    # 1. Download the PDF
    pdf_url = "https://arxiv.org/pdf/2212.13138"
    pdf_content = download_pdf(pdf_url)

    # 2. Convert PDF to text
    paper_text = pdf_to_text(pdf_content)

    # 3. Generate quotes using the Quotes skill
    quotes_result = generate_quotes(paper_text, pdf_url)

    # 4. Log the resulting quotes
    logger.info("Generated quotes:")
    logger.info(quotes_result.quotes)

    # 5. Generate research question using the Question skill
    question_result = generate_research_question(quotes_result.quotes)

    # 6. Log the generated question
    logger.info("Generated research question:")
    logger.info(question_result.question)

if __name__ == "__main__":
    main()
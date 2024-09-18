import os
import sys
import requests
import io
import time
from PyPDF2 import PdfReader
from typing import Dict, Any

# Set up paths
os.chdir(__file__.split('src/')[0])
sys.path.append(os.getcwd())

from src.llm.completion import Completion
from src.util.setup_logging import setup_logging

logger = setup_logging(__file__)

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

def generate_quotes(paper_text: str, pdf_url: str) -> Dict[str, Any]:
    logger.info("Generating quotes using the Quotes skill")
    skill = Completion(('BenchGen', 'Quotes'))
    
    # Generate metadata similar to pipeline.py
    pipeline_start_ts = int(time.time())
    trace_id = f"T{pipeline_start_ts}"
    session_id = f"S{pipeline_start_ts}"
    
    metadata = {
        "trace_name": f"Generate quotes for {pdf_url}",
        "trace_id": trace_id,
        "trace_user_id": "Benchmark",
        "session_id": session_id
    }
    
    result = skill.complete(
        prompt_inputs={"PAPER": paper_text},
        completion_kwargs={"metadata": metadata}
    )
    return result.content

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
    logger.info(quotes_result)

if __name__ == "__main__":
    main()
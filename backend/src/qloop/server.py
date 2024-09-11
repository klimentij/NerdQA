# uvicorn server:app --reload

import json
import os
import re
import sys
import datetime
import hashlib
import time
from typing import List, Tuple, Optional
import markdown
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Import necessary modules and set up paths
os.chdir(__file__.split('src/')[0])
sys.path.append(os.getcwd())

from src.qloop.pipeline import Pipeline
from src.util.setup_logging import setup_logging

logger = setup_logging(__file__)

app = FastAPI()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Add your Vercel URL when you deploy
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Question(BaseModel):
    content: str

pipeline = Pipeline()

@app.post("/api/run_pipeline")
async def run_pipeline(question: Question):
    main_question = question.content
    pipeline.run(main_question=main_question, iterations=1, num_queries=1)
    
    # Get the final answer
    final_answer = pipeline.latest_answer if pipeline.latest_answer else "No answer generated."
    
    return {
        "question": main_question,
        "answer": final_answer,
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
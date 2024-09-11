import asyncio
import json
import os
import sys
from typing import List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import time

# Import necessary modules and set up paths
os.chdir(__file__.split('src/')[0])
sys.path.append(os.getcwd())

from src.qloop.pipeline import StatementGenerator, QueryGenerator, AnswerGenerator
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

class PipelineOrchestrator:
    def __init__(self):
        self.statement_generator = StatementGenerator()
        self.query_generator = QueryGenerator()
        self.answer_generator = AnswerGenerator()
        self.pipeline_start_ts = int(time.time())
        self.trace_id = f"T{self.pipeline_start_ts}"
        self.session_id = f"S{self.pipeline_start_ts}"
        self.main_question = ""

    def get_metadata(self, iteration=None, query_index=None):
        metadata = {
            "trace_name": self.main_question[:],
            "trace_id": self.trace_id,
            "trace_user_id": "Klim",
            "session_id": self.session_id,
            "generation_name_suffix": ""
        }
        if iteration is not None:
            metadata['generation_name_suffix'] = f" [It{iteration+1}]"
            if query_index is not None:
                metadata['generation_name_suffix'] = f" [It{iteration+1} Q{query_index}]"
        return metadata

    async def generate_statements(self, main_question: str, current_query: str, previous_queries_and_statements: str, iteration: int, query_index: int):
        metadata = self.get_metadata(iteration, query_index)
        statements, search_results = await asyncio.to_thread(
            self.statement_generator.generate_statements,
            main_question, current_query, previous_queries_and_statements, metadata
        )
        return statements, search_results

    async def generate_next_queries(self, main_question: str, previous_queries_and_statements: str, current_best_answer: str, num_queries: int, iteration: int):
        metadata = self.get_metadata(iteration)
        next_queries = await asyncio.to_thread(
            self.query_generator.generate_next_queries,
            main_question, previous_queries_and_statements, current_best_answer, num_queries, metadata
        )
        return next_queries

    async def generate_answer(self, main_question: str, research_history: str, iteration: int):
        metadata = self.get_metadata(iteration)
        answer = await asyncio.to_thread(
            self.answer_generator.generate_answer,
            main_question, research_history, metadata
        )
        return answer

orchestrator = PipelineOrchestrator()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            main_question = data.get("question")
            iterations = data.get("iterations", 1)
            num_queries = data.get("num_queries", 1)

            if not main_question:
                await websocket.send_json({"error": "No question provided"})
                continue

            await run_pipeline(websocket, main_question, iterations, num_queries)

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")

async def run_pipeline(websocket: WebSocket, main_question: str, iterations: int, num_queries: int):
    previous_queries_and_statements = ""
    current_best_answer = ""
    orchestrator.main_question = main_question

    for iteration in range(iterations):
        # Generate queries
        next_queries = await orchestrator.generate_next_queries(
            main_question, previous_queries_and_statements, current_best_answer, num_queries, iteration
        )
        await websocket.send_json({"type": "queries", "data": next_queries})

        # Prepare tasks for parallel execution
        statement_tasks = []
        for query_index, query in enumerate(next_queries):
            task = asyncio.create_task(orchestrator.generate_statements(
                main_question, query, previous_queries_and_statements, iteration, query_index
            ))
            statement_tasks.append((query_index, query, task))

        # Wait for all tasks to complete
        for query_index, query, task in statement_tasks:
            statements, search_results = await task
            await websocket.send_json({"type": "statements", "data": statements})

            # Update previous_queries_and_statements
            previous_queries_and_statements += f"\nQuery {query_index + 1}: {query}\n"
            for stmt in statements:
                previous_queries_and_statements += f"Statement {stmt['id']}: {stmt['text']}\n"

        # Generate answer
        answer = await orchestrator.generate_answer(
            main_question, previous_queries_and_statements, iteration
        )
        current_best_answer = answer
        await websocket.send_json({"type": "answer", "data": answer})

    # Send final result
    await websocket.send_json({"type": "final_answer", "data": current_best_answer})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
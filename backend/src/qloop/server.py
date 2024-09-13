"""
To start the server, run:

uvicorn src.qloop.server:app --reload

"""

import asyncio
import json
import os
import sys
from typing import List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import time
import re

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

    def reset_ids(self):
        self.pipeline_start_ts = int(time.time())
        self.trace_id = f"T{self.pipeline_start_ts}"
        self.session_id = f"S{self.pipeline_start_ts}"

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

    async def generate_statements(self, main_question: str, current_query: str, history: str, iteration: int, query_index: int):
        metadata = self.get_metadata(iteration, query_index)
        statements, search_results = await asyncio.to_thread(
            self.statement_generator.generate_statements,
            main_question, current_query, history, metadata
        )
        return statements, search_results

    async def generate_next_queries(self, main_question: str, history: str, current_best_answer: str, num_queries: int, iteration: int):
        metadata = self.get_metadata(iteration)
        next_queries = await asyncio.to_thread(
            self.query_generator.generate_next_queries,
            main_question, history, current_best_answer, num_queries, metadata
        )
        return next_queries

    async def generate_answer(self, main_question: str, history: str, iteration: int):
        metadata = self.get_metadata(iteration)
        answer = await asyncio.to_thread(
            self.answer_generator.generate_answer,
            main_question, history, metadata
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

            orchestrator.reset_ids()  # Reset trace and session IDs for new question
            await run_pipeline(websocket, main_question, iterations, num_queries)

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")

async def run_pipeline(websocket: WebSocket, main_question: str, iterations: int, num_queries: int):
    history = ""
    orchestrator.main_question = main_question
    all_statements = {}
    all_evidence = {}
    all_evidence_ids = set()
    used_evidence_ids = set()
    total_statements = 0

    for iteration in range(iterations):
        # Generate queries
        next_queries = await orchestrator.generate_next_queries(
            main_question, history, "", num_queries, iteration
        )
        await websocket.send_json({
            "type": "queries",
            "data": next_queries,
            "iteration": iteration + 1
        })

        new_evidence_found = 0
        new_evidence_used = 0
        new_statements = 0
        iteration_evidence_ids = set()

        # Process queries and generate statements
        for query_index, current_query in enumerate(next_queries, 1):
            statements, search_results = await orchestrator.generate_statements(
                main_question, current_query, history, iteration, query_index
            )
            
            # Process search results and statements
            if isinstance(search_results, list):
                results = search_results
            elif isinstance(search_results, dict):
                results = search_results.get('results', [])
            else:
                results = []

            for result in results:
                evidence_id = result.get('id')
                if evidence_id and evidence_id not in all_evidence_ids:
                    new_evidence_found += 1
                    all_evidence_ids.add(evidence_id)

            for stmt in statements:
                new_statements += 1
                total_statements += 1
                all_statements[stmt['id']] = stmt
                for evidence in stmt['evidence']:
                    if evidence.startswith('E'):
                        if evidence not in used_evidence_ids:
                            new_evidence_used += 1
                            used_evidence_ids.add(evidence)
                        iteration_evidence_ids.add(evidence)
                        evidence_data = next((result for result in results if result.get('id') == evidence), None)
                        if evidence_data:
                            all_evidence[evidence] = evidence_data

            await websocket.send_json({
                "type": "statements",
                "data": statements,
                "iteration": iteration + 1,
                "query_index": query_index
            })

            history += f"\nQuery: {current_query}\n"
            for stmt in statements:
                history += f"Statement {stmt['id']}: {stmt['text']}\n"

        # Generate answer
        answer = await orchestrator.generate_answer(
            main_question, history, iteration
        )

        # Extract cited statements from the answer
        cited_statements = set(re.findall(r'\[(S\d+)\]', answer))

        # Generate full citation tree for cited statements
        full_citation_tree = generate_full_citation_tree(all_statements, all_evidence, cited_statements)

        # Prepare iteration summary
        iteration_summary = {
            "iteration": iteration + 1,
            "new_evidence_found": new_evidence_found,
            "new_evidence_used": new_evidence_used,
            "new_statements": new_statements,
            "total_evidence_found": len(all_evidence_ids),
            "total_evidence_used": len(used_evidence_ids),
            "total_statements": total_statements
        }

        # Send answer with full citation tree
        await websocket.send_json({
            "type": "answer",
            "data": answer,
            "iteration": iteration + 1,
            "summary": iteration_summary,
            "full_citation_tree": full_citation_tree
        })

def generate_citation_tree_data(all_statements, all_evidence, max_depth=5):
    def build_tree(node_id, depth=0, visited=None):
        if visited is None:
            visited = set()
        
        if depth >= max_depth or node_id in visited:
            return None
        
        visited.add(node_id)
        
        if node_id.startswith('S'):
            statement = all_statements.get(node_id)
            if isinstance(statement, dict):
                children = [build_tree(e, depth + 1, visited.copy()) for e in statement.get('evidence', [])]
                children = [child for child in children if child is not None]
                return {
                    'id': node_id,
                    'text': statement['text'],
                    'children': children
                }
        elif node_id.startswith('E'):
            evidence = all_evidence.get(node_id, "Evidence text not found")
            url = ""
            if isinstance(evidence, dict):
                url = evidence.get('meta', {}).get('url', '')
                evidence = evidence.get('text', "Evidence text not found")
            return {
                'id': node_id,
                'text': evidence,
                'url': url,
                'children': []
            }
        return None

    trees = {}
    for stmt_id in all_statements.keys():
        tree = build_tree(stmt_id)
        if tree:
            trees[stmt_id] = tree

    return trees

def generate_full_citation_tree(all_statements, all_evidence, cited_statements, max_depth=5):
    def build_tree(node_id, depth=0, visited=None):
        if visited is None:
            visited = set()
        
        if depth >= max_depth or node_id in visited:
            return None
        
        visited.add(node_id)
        
        if node_id.startswith('S'):
            statement = all_statements.get(node_id)
            if isinstance(statement, dict):
                children = [build_tree(e, depth + 1, visited.copy()) for e in statement.get('evidence', [])]
                children = [child for child in children if child is not None]
                return {
                    'id': node_id,
                    'text': statement['text'],
                    'children': children
                }
        elif node_id.startswith('E'):
            evidence = all_evidence.get(node_id, {})
            return {
                'id': node_id,
                'text': evidence.get('text', "Evidence text not found"),
                'url': evidence.get('meta', {}).get('url', ''),
                'children': []
            }
        return None

    trees = {}
    for stmt_id in cited_statements:
        tree = build_tree(stmt_id)
        if tree:
            trees[stmt_id] = tree

    return trees

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
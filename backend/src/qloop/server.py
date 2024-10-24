"""
To start the server, run:

uvicorn src.qloop.server:app --reload

"""

import asyncio
import json
import os
import random
import sys
from typing import List, Dict, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import time
import re
from inspect import iscoroutinefunction
import hashlib
from fastapi.responses import JSONResponse
import uuid
from datetime import datetime
import markdown

# Import necessary modules and set up paths
os.chdir(__file__.split('src/')[0])
sys.path.append(os.getcwd())

from src.qloop.pipeline import StatementGenerator, QueryGenerator, AnswerGenerator
from src.tools.search_client import SearchClient
from src.tools.brave_search_client import BraveSearchClient
from src.tools.exa_search_client import ExaSearchClient
from src.tools.openalex_search_client import OpenAlexSearchClient
from src.util.setup_logging import setup_logging

logger = setup_logging(__file__, "DEBUG")

app = FastAPI()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for now. In production, specify your frontend URL.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory storage for session data
sessions: Dict[str, Dict] = {}

# Add this new dictionary to store WebSocket connections
websocket_connections: Dict[str, WebSocket] = {}

class QuestionRequest(BaseModel):
    question: str
    iterations: int = 1
    num_queries: int = 1
    start_date: str = "1900-01-20"
    end_date: Optional[str] = None
    search_client: Optional[str] = None

class FeedbackRequest(BaseModel):
    session_id: str
    feedback: str

class PipelineOrchestrator:
    def __init__(self, web_search: SearchClient = None):
        self.statement_generator = StatementGenerator(web_search=web_search)
        self.query_generator = QueryGenerator()
        self.answer_generator = AnswerGenerator()
        self.main_question = ""
        self.user_feedback = []
        self.current_history = ""
        self.reset_ids()

    def reset_ids(self):
        self.pipeline_uuid = str(uuid.uuid4())
        self.trace_id = f"T{self.pipeline_uuid}"
        self.session_id = f"S{self.pipeline_uuid}"

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

    def add_user_feedback(self, feedback: str):
        self.user_feedback.append(feedback)
        self.current_history += f"\nUser feedback: {feedback}\n"
        logger.info(f"Feedback added to history: {feedback}")
        logger.info(f"Current history: {self.current_history}")

    def get_current_history(self) -> str:
        return self.current_history

    async def generate_statements(self, main_question: str, current_query: str, iteration: int, query_index: int, start_date: str, end_date: str):
        logger.info(f"Generating statements with current history: {self.current_history}")
        metadata = self.get_metadata(iteration, query_index)
        
        if iscoroutinefunction(self.statement_generator.generate_statements):
            statements, search_results = await self.statement_generator.generate_statements(
                main_question, current_query, self.current_history, metadata, start_date, end_date
            )
        else:
            statements, search_results = await asyncio.to_thread(
                self.statement_generator.generate_statements,
                main_question, current_query, self.current_history, metadata, start_date, end_date
            )
        
        return statements, search_results

    async def generate_next_queries(self, main_question: str, num_queries: int, iteration: int):
        logger.info(f"Generating queries with current history: {self.current_history}")
        metadata = self.get_metadata(iteration)
        next_queries = await asyncio.to_thread(
            self.query_generator.generate_next_queries,
            main_question, self.current_history, num_queries, metadata
        )
        return next_queries

    async def generate_answer(self, main_question: str, iteration: int):
        logger.info(f"Generating answer with current history: {self.current_history}")
        metadata = self.get_metadata(iteration)
        answer = await asyncio.to_thread(
            self.answer_generator.generate_answer,
            main_question, self.current_history, metadata
        )
        return answer

search_client_map = {
    "brave": BraveSearchClient,
    "exa": ExaSearchClient,
    "openalex": OpenAlexSearchClient
}

@app.options("/start_pipeline")
async def options_start_pipeline():
    return {"message": "OK"}

@app.post("/start_pipeline")
async def start_pipeline(request: QuestionRequest, background_tasks: BackgroundTasks):
    session_id = str(uuid.uuid4())
    web_search = search_client_map.get(request.search_client, ExaSearchClient)()
    orchestrator = PipelineOrchestrator(web_search=web_search)
    orchestrator.main_question = request.question
    
    sessions[session_id] = {
        "orchestrator": orchestrator,
        "status": "running",
        "current_iteration": 0,
        "total_iterations": request.iterations,
        "messages": [],
        "final_answer": "",
        "full_citation_tree": {},
        "summary": {}
    }
    
    background_tasks.add_task(
        run_pipeline,
        session_id,
        request.question,
        request.iterations,
        request.num_queries,
        request.start_date,
        request.end_date or time.strftime("%Y-%m-%d"),
        web_search
    )
    
    return {"session_id": session_id}

@app.get("/pipeline_status/{session_id}")
async def pipeline_status(session_id: str):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = sessions[session_id]
    return {
        "status": session["status"],
        "current_iteration": session["current_iteration"],
        "total_iterations": session["total_iterations"],
        "messages": session["messages"],
        "final_answer": session["final_answer"],
        "full_citation_tree": session["full_citation_tree"],
        "summary": session["summary"]
    }

@app.post("/send_feedback")
async def send_feedback(request: FeedbackRequest):
    if request.session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    orchestrator = sessions[request.session_id]["orchestrator"]
    orchestrator.add_user_feedback(request.feedback)
    return {"message": "Feedback received"}

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    websocket_connections[session_id] = websocket
    try:
        while True:
            # Keep the connection open
            await websocket.receive_text()
    except WebSocketDisconnect:
        del websocket_connections[session_id]

# Add this new function to generate the HTML export
def generate_html_export(main_question: str, final_answer: str, citation_trees: dict, summary: dict, session_id: str):
    md = markdown.Markdown()
    
    def process_answer(answer):
        html = md.convert(answer)
        html = re.sub(r'\[(S\d+)\]', r'<a href="#tree-\1" class="citation" id="cite-\1">[\1]</a>', html)
        return html
    
    def render_tree(node):
        if not node:
            return ""
        
        html = f'<li id="tree-{node["id"]}"><strong>{node["id"]}:</strong> {node["text"]}'
        if node['id'].startswith('E'):
            url = node.get('url', '')
            if url:
                html += f'<br><a href="{url}" target="_blank">{url}</a>'
        if node.get('children'):
            html += '<ul>'
            for child in node['children']:
                html += render_tree(child)
            html += '</ul>'
        html += '</li>'
        return html

    processed_answer = process_answer(final_answer)
    
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{main_question[:100]}</title>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; padding: 20px; }}
            h1, h2, h3 {{ color: #333; }}
            .citation-tree {{ margin-top: 20px; }}
            .citation-tree ul {{ list-style-type: none; }}
            .citation-tree li {{ margin: 10px 0; }}
            .back-to-top {{ text-decoration: none; color: #0066cc; }}
        </style>
    </head>
    <body>
        <h1>{main_question}</h1>
        <h2>Answer</h2>
        <div id="answer-content">
            {processed_answer}
        </div>
        <h3>Summary</h3>
        <ul>
            <li>Total evidence found: {summary['total_evidence_found']}</li>
            <li>Total evidence used: {summary['total_evidence_used']}</li>
            <li>Total statements: {summary['total_statements']}</li>
        </ul>
        <h2>Citation Trees</h2>
        <div class="citation-tree">
    """
    
    for stmt_id, tree in citation_trees.items():
        html_content += f'<div id="tree-{stmt_id}">'
        html_content += f'<h3>Citation Tree for Statement {stmt_id}</h3>'
        html_content += '<ul>'
        html_content += render_tree(tree)
        html_content += '</ul>'
        html_content += f'<a href="#cite-{stmt_id}" class="back-to-top">↑ Back to citation</a>'
        html_content += '</div>'
    
    html_content += """
        </div>
    </body>
    </html>
    """

    # Create the export directory
    current_date = datetime.now().strftime("%Y-%m-%d")
    export_dir = os.path.join("export", current_date)
    os.makedirs(export_dir, exist_ok=True)

    # Generate the filename
    safe_question = re.sub(r'[^\w\s-]', '', main_question[:100])
    filename = f"{safe_question}_{session_id}.html"
    file_path = os.path.join(export_dir, filename)

    # Write the HTML content to the file
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    return file_path

# Modify the run_pipeline function to call the new export function
async def run_pipeline(session_id: str, main_question: str, iterations: int, num_queries: int, start_date: str, end_date: str, web_search: SearchClient):
    session = sessions[session_id]
    orchestrator = session["orchestrator"]
    
    orchestrator.statement_generator = StatementGenerator(web_search=web_search)

    all_statements = {}
    all_evidence = {}
    all_evidence_ids = set()
    used_evidence_ids = set()
    total_statements = 0

    for iteration in range(iterations):
        session["current_iteration"] = iteration + 1
        
        if iteration == 0:
            next_queries = [main_question]
        else:
            next_queries = await orchestrator.generate_next_queries(
            main_question, num_queries, iteration
        )

        new_message = {
            "type": "queries",
            "data": next_queries[:num_queries],
            "iteration": iteration + 1
        }
        session["messages"].append(new_message)
        await send_update(session_id, new_message)

        new_evidence_found = 0
        new_evidence_used = 0
        new_statements = 0
        iteration_evidence_ids = set()

        async def process_query(query_index, current_query):
            logger.debug(f"Processing query {query_index}: {current_query}")
            statements, search_results = await orchestrator.generate_statements(
                main_question, current_query, iteration, query_index, start_date, end_date
            )
            return statements, search_results, query_index

        tasks = [process_query(i+1, query) for i, query in enumerate(next_queries[:num_queries])]
        results = await asyncio.gather(*tasks)

        for statements, search_results, query_index in results:
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

            new_message = {
                "type": "statements",
                "data": statements,
                "iteration": iteration + 1,
                "query_index": query_index
            }
            session["messages"].append(new_message)
            await send_update(session_id, new_message)

            orchestrator.current_history += f"\nQuery: {next_queries[query_index-1]}\n"
            for stmt in statements:
                orchestrator.current_history += f"Statement {stmt['id']}: {stmt['text']}\n"

        # Check if any statements have been created
        if total_statements == 0:
            predefined_answer = "I apologize, but I haven't found sufficient support for answering your question yet. A few more iterations might be needed to gather relevant information. Please allow the process to continue or try rephrasing your question."
            
            new_message = {
                "type": "answer",
                "data": predefined_answer,
                "iteration": iteration + 1,
                "summary": {
                    "iteration": iteration + 1,
                    "new_evidence_found": new_evidence_found,
                    "new_evidence_used": new_evidence_used,
                    "new_statements": new_statements,
                    "total_evidence_found": len(all_evidence_ids),
                    "total_evidence_used": len(used_evidence_ids),
                    "total_statements": total_statements
                },
                "citation_trees": {}
            }
        else:
            if iteration == iterations - 1:
                # Generate the answer only on the last iteration
                answer = await orchestrator.generate_answer(main_question, iteration)

                # Normalize citation format
                def normalize_citations(text):
                    def process_bracket_content(match):
                        content = match.group(1)
                        if re.search(r'S\d+', content):
                            # This is a citation group
                            citations = re.findall(r'S\d+', content)
                            return '[' + '], ['.join(citations) + ']'
                        else:
                            # This is not a citation, return it unchanged
                            return f'[{content}]'

                    # Process all bracket contents
                    normalized = re.sub(r'\[([^\]]+)\]', process_bracket_content, text)
                    return normalized

                normalized_answer = normalize_citations(answer)
                
                cited_statements = set(re.findall(r'S\d+', normalized_answer))
                full_citation_tree = generate_full_citation_tree(all_statements, all_evidence, cited_statements)

                # Create a mapping of original S ids to sequential ids
                s_id_mapping = {s_id: f'S{i+1}' for i, s_id in enumerate(cited_statements)}

                # Replace S ids in the answer
                for original_id, seq_id in s_id_mapping.items():
                    normalized_answer = normalized_answer.replace(original_id, seq_id)

                # Replace S ids in the citation tree
                updated_citation_tree = {}
                for original_id, tree in full_citation_tree.items():
                    new_id = s_id_mapping.get(original_id, original_id)
                    updated_tree = replace_ids_in_tree(tree, s_id_mapping)
                    updated_citation_tree[new_id] = updated_tree

                iteration_summary = {
                    "iteration": iteration + 1,
                    "new_evidence_found": new_evidence_found,
                    "new_evidence_used": new_evidence_used,
                    "new_statements": new_statements,
                    "total_evidence_found": len(all_evidence_ids),
                    "total_evidence_used": len(used_evidence_ids),
                    "total_statements": total_statements
                }

                new_message = {
                    "type": "answer",
                    "data": normalized_answer,
                    "iteration": iteration + 1,
                    "summary": iteration_summary,
                    "citation_trees": updated_citation_tree
                }

                # After generating the final answer and updating the session, call the export function
                export_path = generate_html_export(
                    main_question,
                    normalized_answer,
                    updated_citation_tree,
                    iteration_summary,
                    session_id
                )
                logger.info(f"HTML export generated: {export_path}")
            else:
                # Submit fixed text for non-final iterations
                new_message = {
                    "type": "answer",
                    "data": "I am discovering new knowledge and researching to support the answer as best as I can.",
                    "iteration": iteration + 1,
                    "summary": {
                        "iteration": iteration + 1,
                        "new_evidence_found": new_evidence_found,
                        "new_evidence_used": new_evidence_used,
                        "new_statements": new_statements,
                        "total_evidence_found": len(all_evidence_ids),
                        "total_evidence_used": len(used_evidence_ids),
                        "total_statements": total_statements
                    },
                    "citation_trees": {}
                }
        
        session["messages"].append(new_message)
        await send_update(session_id, new_message)

        session["final_answer"] = new_message["data"]
        session["citation_trees"] = new_message.get("citation_trees", {})
        session["summary"] = new_message["summary"]

    session["status"] = "completed"
    await send_update(session_id, {"type": "status", "data": "completed"})

async def send_update(session_id: str, message: dict):
    if session_id in websocket_connections:
        try:
            await websocket_connections[session_id].send_json(message)
        except WebSocketDisconnect:
            del websocket_connections[session_id]

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
            reference = {
                'id': node_id,
                'text': evidence.get('text', "Evidence text not found"),
                'url': evidence.get('meta', {}).get('url', ""),
                'openalex_id': evidence.get('meta', {}).get('openalex_id', "")
            }
            if reference['url'] == "":
                reference['url'] = evidence.get('meta', {}).get('id', '')
                reference['title'] = evidence.get('meta', {}).get('title', "")
                reference['publication_date'] = evidence.get('meta', {}).get('publication_date', "")

            return reference

        return None

    trees = {}
    for stmt_id in cited_statements:
        tree = build_tree(stmt_id)
        if tree:
            trees[stmt_id] = tree

    return trees

@app.get("/citation/{session_id}/{citation_id}")
async def get_citation(session_id: str, citation_id: str):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = sessions[session_id]
    orchestrator = session["orchestrator"]
    
    if citation_id.startswith('S'):
        # Look for the statement in all_statements
        for iteration in session["messages"]:
            if iteration["type"] == "statements":
                for statement in iteration["data"]:
                    if statement["id"] == citation_id:
                        return statement
    elif citation_id.startswith('E'):
        # Look for the evidence in all_evidence
        for iteration in session["messages"]:
            if iteration["type"] == "answer":
                full_citation_tree = iteration.get("full_citation_tree", {})
                for tree in full_citation_tree.values():
                    evidence = find_evidence_in_tree(tree, citation_id)
                    if evidence:
                        return evidence

    raise HTTPException(status_code=404, detail="Citation not found")

def find_evidence_in_tree(node, target_id):
    if node["id"] == target_id:
        return node
    for child in node.get("children", []):
        result = find_evidence_in_tree(child, target_id)
        if result:
            return result
    return None

# Add this new function to replace ids in the tree
def replace_ids_in_tree(node, id_mapping):
    if isinstance(node, dict):
        new_node = node.copy()
        if 'id' in new_node and new_node['id'] in id_mapping:
            new_node['id'] = id_mapping[new_node['id']]
        if 'children' in new_node:
            new_node['children'] = [replace_ids_in_tree(child, id_mapping) for child in new_node['children']]
        return new_node
    return node

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

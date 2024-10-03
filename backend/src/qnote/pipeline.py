# uvicorn server:app --reload

import json
import os
import sys
import hashlib
import asyncio
from inspect import iscoroutinefunction
from typing import List, Tuple, Optional
import uuid
from pydantic import BaseModel, Field
import traceback
import re

# Import necessary modules and set up paths
os.chdir(__file__.split('src/')[0])
sys.path.append(os.getcwd())

from src.llm.completion import Completion
from src.tools.search_client import SearchClient
from src.tools.openalex_search_client import OpenAlexSearchClient
from src.util.setup_logging import setup_logging

logger = setup_logging(__file__, "DEBUG")

STATEMENT_ID_DIGITS = 10

class QueryOutput(BaseModel):
    reflection: str = Field(..., description="A summary of the current state of research and suggested direction for the next step")
    queries: List[str] = Field(..., description="New, concise queries for a Google-like search engine")

class Statement(BaseModel):
    id: Optional[str] = Field(None, description="The unique identifier for the statement")
    text: str = Field(..., description="The statement text")
    evidence: List[str] = Field(..., description="A list of evidence IDs that directly support the statement")

class StatementsOutput(BaseModel):
    reflection: str = Field(..., description="A comprehensive paragraph containing strategic reflection and analysis on the research process")
    statements: List[Statement] = Field(..., description="An array of generated statements with their supporting evidence")
    relevant_sources: List[str] = Field(..., description="A list of E.. IDs representing relevant sources from the search results")

class StatementGenerator:
    def __init__(self, web_search: SearchClient = OpenAlexSearchClient()):
        self.web_search = web_search
        self.skill = Completion(('QueryNoteLoop', 'Statements'))

    async def search(self, current_query, main_question, start_date, end_date):
        if self.web_search:
            if iscoroutinefunction(self.web_search.search):
                search_results = await self.web_search.search(current_query, main_question, start_date, end_date)
            else:
                search_results = await asyncio.to_thread(self.web_search.search, current_query, main_question, start_date, end_date)
        return search_results.get('results', [])

    async def generate_statements(self, main_question, current_query, current_history, metadata, filtered_results) -> StatementsOutput:
        logger.info(f"Generating statements for query: {current_query}")
        
        # Use only limited_meta for each result
        limited_results = [
            {
                "id": result.get("id"),
                "meta": result.get("limited_meta", result.get("meta", {})),
                "text": result.get("text", "")
            }
            for result in filtered_results
        ]
        

        try:
            result = self.skill.complete(
                prompt_inputs={
                    "MAIN_QUESTION": main_question,
                    "QUERIES": current_query,
                    "SEARCH_RESULTS": json.dumps(limited_results),
                    "HISTORY": current_history
                },
                completion_kwargs={"metadata": metadata}
            )
            response_data = json.loads(result.content)
            
            statements_output = StatementsOutput(**response_data)
            
            # Generate and set IDs for statements
            for statement in statements_output.statements:
                statement_hash = int(hashlib.md5(statement.text.encode()).hexdigest(), 16)
                statement.id = f"S{statement_hash % 10**STATEMENT_ID_DIGITS:0{STATEMENT_ID_DIGITS}d}"
            
            logger.info(f"Generated {len(statements_output.statements)} statements")
            logger.debug(f"Statements output: {statements_output.dict()}")
            return statements_output
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error in generate_statements: {e}")
            logger.error(f"Raw content that failed to decode: {result.content}")
            return StatementsOutput(reflection="", statements=[], relevant_sources=[])
        except Exception as e:
            logger.error(f"Error in generate_statements: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return StatementsOutput(reflection="", statements=[], relevant_sources=[])

class QueryGenerator:
    def __init__(self):
        self.skill = Completion(('QueryNoteLoop', 'Query'))

    def generate_next_queries(self, main_question: str, research_history: str, num_queries: int, metadata: dict) -> QueryOutput:
        logger.info(f"Generating next {num_queries} queries")
        
        result = self.skill.complete(
            prompt_inputs={
                "MAIN_QUESTION": main_question,
                "RESEARCH_HISTORY": research_history,
                "NUM_QUERIES": num_queries
            },
            completion_kwargs={"metadata": metadata}
        )

        try:
            response_data = json.loads(result.content)
            query_output = QueryOutput(**response_data)
            
            if len(query_output.queries) != num_queries:
                logger.warning(f"Expected {num_queries} queries, but got {len(query_output.queries)}")
            
            logger.info(f"Generated reflection and {len(query_output.queries)} next queries")
            return query_output
        except Exception as e:
            logger.error(f"Error in generate_next_queries: {e}")
            return QueryOutput(reflection="", queries=[])

class AnswerGenerator:
    def __init__(self):
        self.skill = Completion(('QLoop', 'Answer'))

    def generate_answer(self, main_question: str, history: str, metadata: dict) -> str:
        logger.info("Generating research answer")
        
        result = self.skill.complete(
            prompt_inputs={
                "MAIN_QUESTION": main_question,
                "HISTORY": history
            },
            completion_kwargs={"metadata": metadata}
        )

        try:
            response_data = json.loads(result.content)
            answer = response_data.get('answer', '')
            logger.info("Generated research answer")
            return answer
        except Exception as e:
            logger.error(f"Error in generate_answer: {e}")
            return ""

async def run_pipeline(main_question: str, iterations: int, num_queries: int, start_date: str, end_date: str):
    web_search = OpenAlexSearchClient()
    statement_generator = StatementGenerator(web_search=web_search)
    query_generator = QueryGenerator()
    answer_generator = AnswerGenerator()
    
    history_list = []
    all_statements = {}
    all_evidence = {}
    all_relevant_source_ids = set()

    # Generate metadata
    pipeline_uuid = str(uuid.uuid4())
    trace_id = f"T{pipeline_uuid}"
    session_id = f"S{pipeline_uuid}"

    def get_metadata(iteration=None, query_index=None):
        metadata = {
            "trace_name": main_question[:],
            "trace_id": trace_id,
            "trace_user_id": "Klim",
            "session_id": session_id,
            "generation_name_suffix": ""
        }
        if iteration is not None:
            metadata['generation_name_suffix'] = f" [It{iteration+1}]"
            if query_index is not None:
                metadata['generation_name_suffix'] = f" [It{iteration+1} Q{query_index}]"
        return metadata

    for iteration in range(iterations):
        logger.info(f"Starting iteration {iteration + 1}")
        
        iteration_data = {
            "iteration": iteration + 1,
            "query_reflection": "",
            "queries": [],
            "search_results": [],
            "statements": [],
            "selected_references": []
        }
        
        if iteration == 0:
            next_queries = [main_question]
        else:
            query_output = query_generator.generate_next_queries(
                main_question, get_history_string(history_list), num_queries, get_metadata(iteration)
            )
            iteration_data["query_reflection"] = query_output.reflection
            next_queries = query_output.queries

        iteration_data["queries"] = next_queries[:num_queries]

        # Search queries in parallel
        search_tasks = [statement_generator.search(query, main_question, start_date, end_date) 
                        for query in iteration_data["queries"]]
        search_results = await asyncio.gather(*search_tasks)

        # Merge and deduplicate search results
        merged_results = []
        seen_ids = set()
        for results in search_results:
            for result in results:
                if result['id'] not in seen_ids:
                    merged_results.append(result)
                    seen_ids.add(result['id'])

        iteration_data["search_results"] = merged_results

        statements_output = await statement_generator.generate_statements(
            main_question, ", ".join(iteration_data["queries"]), get_history_string(history_list),
            get_metadata(iteration),
            merged_results
        )
        
        iteration_data["statement_reflection"] = statements_output.reflection
        iteration_data["statements"] = [stmt.dict() for stmt in statements_output.statements]
        iteration_data["relevant_sources"] = statements_output.relevant_sources
        iteration_data["relevant_source_ids"] = []
        
        for evidence_id in statements_output.relevant_sources:
            evidence_data = next((result for result in merged_results if result.get('id') == evidence_id), None)
            if evidence_data:
                openalex_id = evidence_data.get('meta', {}).get('openalex_id')
                if openalex_id:
                    iteration_data["relevant_source_ids"].append(openalex_id)
                    all_relevant_source_ids.add(openalex_id)

        for stmt in statements_output.statements:
            all_statements[stmt.id] = stmt.dict()
            for evidence in stmt.evidence:
                if evidence.startswith('E'):
                    evidence_data = next((result for result in merged_results if result.get('id') == evidence), None)
                    if evidence_data:
                        all_evidence[evidence] = evidence_data
                        iteration_data["selected_references"].append(evidence)

        history_list.append(iteration_data)

    # Generate the final answer after all iterations
    answer = answer_generator.generate_answer(
        main_question, get_history_string(history_list), get_metadata(iterations)
    )

    # Extract citation tree, answer_source_ids, and OpenAlex IDs
    citation_tree, answer_source_ids, answer_openalex_ids = extract_citation_info(answer, all_statements, all_evidence)

    # Add answer_openalex_ids to all_relevant_source_ids
    all_relevant_source_ids.update(answer_openalex_ids)

    return {
        "answer": answer,
        "citation_tree": citation_tree,
        "answer_source_ids": answer_source_ids,
        "answer_openalex_ids": answer_openalex_ids,
        "all_relevant_source_ids": list(all_relevant_source_ids),
        "history": history_list,
        "all_statements": all_statements,
        "all_evidence": all_evidence
    }

def extract_citation_info(answer, all_statements, all_evidence):
    cited_statements = set(re.findall(r'\[(S\d+)\]', answer))
    citation_tree = generate_full_citation_tree(all_statements, all_evidence, cited_statements)
    answer_source_ids = list(cited_statements)
    
    # Collect OpenAlex IDs from the citation tree
    openalex_ids = collect_openalex_ids(citation_tree)
    
    return citation_tree, answer_source_ids, openalex_ids

def collect_openalex_ids(citation_tree):
    openalex_ids = []
    
    def traverse(node):
        if isinstance(node, dict):
            if 'openalex_id' in node and node['openalex_id']:
                openalex_ids.append(node['openalex_id'])
            for child in node.get('children', []):
                traverse(child)
    
    for tree in citation_tree.values():
        traverse(tree)
    
    return list(set(openalex_ids))  # Remove duplicates

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
                # possibly a paper
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

def get_history_string(history_list, include_answer=None):
    simplified_history = []
    for item in history_list:
        simplified_item = {
            "iteration": item["iteration"],
            "query_reflection": item.get("query_reflection", ""),
            "queries": item.get("queries", []),
            "statement_reflection": item.get("reflection", ""),  # Use "reflection" but name it "statement_reflection" in history
            "statements": [
                {
                    "id": stmt["id"],
                    "text": stmt["text"]
                }
                for stmt in item.get("statements", [])
            ],
            "relevant_source_ids": item.get("relevant_source_ids", [])
        }
        simplified_history.append(simplified_item)
    
    if include_answer:
        simplified_history.append({"final_answer": include_answer})
    
    return json.dumps(simplified_history, indent=2)

if __name__ == "__main__":
    main_question = "What are the latest advancements in quantum computing?"
    iterations = 2
    num_queries = 2
    start_date = "2022-01-01"
    end_date = "2023-12-31"

    result = asyncio.run(run_pipeline(main_question, iterations, num_queries, start_date, end_date))
    
    # Remove search_results from each history iteration
    for iteration in result['history']:
        iteration.pop('search_results', None)
    
    logger.info(json.dumps(result, indent=2))
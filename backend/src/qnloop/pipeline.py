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
import asyncio
from inspect import iscoroutinefunction

# Import necessary modules and set up paths
os.chdir(__file__.split('src/')[0])
sys.path.append(os.getcwd())

from src.llm.completion import Completion
from src.tools.search_client import SearchClient
from src.tools.exa_search_client import ExaSearchClient
from src.util.setup_logging import setup_logging

logger = setup_logging(__file__, "DEBUG")

STATEMENT_ID_DIGITS = 10

class StatementGenerator:
    def __init__(self, web_search: SearchClient = ExaSearchClient()):
        self.web_search = web_search or ExaSearchClient()
        self.skill = Completion(('QLoop', 'Statements'))

    async def generate_statements(self, main_question, current_query, current_history, metadata, start_date, end_date):
        logger.info(f"Generating statements for query: {current_query} from {start_date} to {end_date}")
        
        if self.web_search:
            if iscoroutinefunction(self.web_search.search):
                search_results = await self.web_search.search(current_query, main_question, start_date, end_date)
            else:
                search_results = await asyncio.to_thread(self.web_search.search, current_query, main_question, start_date, end_date)
        
        filtered_results = search_results.get('results', [])

        # Use only limited_meta for each result
        limited_results = [
            {
                "id": result.get("id"),
                "meta": result.get("limited_meta", result.get("meta", {})),
                "text": result.get("text", "")
            }
            for result in filtered_results
        ]

        result = self.skill.complete(
            prompt_inputs={
                "MAIN_QUESTION": main_question,
                "QUERY": current_query,
                "SEARCH_RESULTS": json.dumps(limited_results),
                "HISTORY": current_history
            },
            completion_kwargs={"metadata": metadata}
        )

        try:
            response_data = json.loads(result.content)
            statements = response_data['statements']
            
            for statement in statements:
                statement_hash = int(hashlib.md5(statement['text'].encode()).hexdigest(), 16)
                statement['id'] = f"S{statement_hash % 10**STATEMENT_ID_DIGITS:0{STATEMENT_ID_DIGITS}d}"
            
            logger.info(f"Generated {len(statements)} statements")
            return statements, filtered_results
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            return [], {}
        except KeyError as e:
            logger.error(f"Invalid response format: missing key {e}")
            return [], {}
        except Exception as e:
            logger.error(f"Unexpected error in generate_statements: {e}")
            return [], {}

class QueryGenerator:
    def __init__(self):
        self.skill = Completion(('QueryNoteLoop', 'Query'))

    def generate_next_queries(self, main_question: str, research_history: str, num_queries: int, metadata: dict) -> Tuple[str, List[str]]:
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
            reflection = response_data['reflection']
            queries = response_data['queries']
            
            if len(queries) != num_queries:
                logger.warning(f"Expected {num_queries} queries, but got {len(queries)}")
            
            logger.info(f"Generated reflection and {len(queries)} next queries")
            return reflection, queries
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            return "", []
        except KeyError as e:
            logger.error(f"Invalid response format: missing key {e}")
            return "", []
        except Exception as e:
            logger.error(f"Unexpected error in generate_next_queries: {e}")
            return "", []

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
            if not result.content:
                logger.error("Empty response from LLM")
                return ""

            response_data = json.loads(result.content)
            answer = response_data.get('answer', '')
            logger.info("Generated research answer")
            return answer
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            return ""
        except Exception as e:
            logger.error(f"Unexpected error in generate_answer: {e}")
            return ""


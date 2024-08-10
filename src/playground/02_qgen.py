import json
import os
import re
import time
import sys
from typing import List
from abc import ABC, abstractmethod
from pydantic import BaseModel

os.chdir(__file__.split('src/')[0])
sys.path.append(os.getcwd())

from src.llm.completion import Completion
from src.util.env_util import cfg, litellm_cfg
from src.tools.web_search import BraveSearchClient

from src.util.setup_logging import setup_logging
from tqdm import tqdm

logger = setup_logging(__file__)

class Renderer(ABC):
    @abstractmethod
    def render(self, content: str):
        pass

class MarkdownRenderer(Renderer):
    def __init__(self, filepath: str):
        self.filepath = filepath
        with open(self.filepath, 'w') as f:
            f.write("# Queries\n\n")

    def render(self, content: str):
        with open(self.filepath, 'a') as f:
            f.write(content + '\n')

class Step(BaseModel):
    explanation: str
    output: str

class MathReasoning(BaseModel):
    steps: list[Step]
    final_answer: str


class QueryGenerator:
    def __init__(self, renderer: Renderer, num_queries: int = 3, depth: int = 3):
        self.num_queries = num_queries
        self.depth = depth
        self.web_search = BraveSearchClient()
        self.skill = Completion(
            ('Forward', 'SubQuestions'),
            user_id="KB",
            completion_kwargs={"response_format": MathReasoning}
            )
        self.total_queries_generated = 0
        self.renderer = renderer
        self.requests_sent_to_search = 0
        self.requests_sent_to_llm = 0
        self.cache_retrievals = 0
        self.total_steps = 0
        self.query_tree = {}
        self.initial_question = None

    def generate_queries(self, current_query: str, query_subtree: dict) -> str:
        logger.debug(f"Generating queries for: {current_query}")
        self.requests_sent_to_search += 1
        search_results = self.web_search.search(current_query)
        logger.debug(f"Search returned {len(search_results.get('web', {}).get('results', []))} results")

        self.requests_sent_to_llm += 1
        result = self.skill.complete(
            prompt_inputs={
                "ORIGINAL_QUESTION": self.initial_question,
                "SUBQUESTION_TREE": json.dumps(self.query_tree),
                "CURRENT_SUBQUESTION": current_query,
                "SEARCH_RESULTS": json.dumps(search_results),
                "NUM_QUERIES": str(self.num_queries)
            }
        )
        logger.debug(f"Queries result: {result.content}")
        return result.content

    def parse_queries(self, text: str) -> List[str]:
        pattern = re.compile(r'<query>(.*?)<\/query>', re.DOTALL)
        queries = pattern.findall(text)
        logger.debug(f"Parsed queries: {queries}")
        if len(queries) == 0:
            logger.warning("No queries found")
            return []
        queries = [query.strip() for query in queries][:self.num_queries]
        return queries

    def build_query_list(self, question: str, query_subtree: dict, current_depth: int = 0, pbar=None):
        logger.debug(f"Building query list for: {question} at depth {current_depth}")
        if current_depth >= self.depth:
            self.renderer.render(f"{'    ' * current_depth}- {question}")
            if pbar:
                pbar.update(1)
            return

        queries_text = self.generate_queries(question, query_subtree)
        queries = self.parse_queries(queries_text)
        self.total_queries_generated += 1
        self.total_steps += len(queries) + 1

        self.renderer.render(f"{'    ' * current_depth}- {question}")

        query_subtree[question] = {}
        for query in queries:
            query_subtree[question][query] = {}
            self.build_query_list(query, query_subtree[question], current_depth + 1, pbar)
            if pbar:
                pbar.update(1)
            self.total_steps += 1

    def save_to_markdown(self, initial_question: str):
        self.initial_question = initial_question  # Set the initial question here
        start_time = time.time()
        total_progress_steps = self.num_queries ** self.depth
        logger.info(f"Starting query generation for: {initial_question}")
        with tqdm(total=total_progress_steps, desc="Generating Queries") as pbar:
            self.query_tree = {}
            self.build_query_list(initial_question, self.query_tree, pbar=pbar)
        elapsed_time = time.time() - start_time
        logger.info(f"Total queries generated: {self.total_queries_generated}")
        logger.info(f"Requests sent to search: {self.requests_sent_to_search}")
        logger.info(f"Requests sent to LLM: {self.requests_sent_to_llm}")
        logger.info(f"Cache retrievals: {self.cache_retrievals}")
        logger.info(f"Completed in {elapsed_time:.2f} seconds")
        logger.info(f"Overall progress: 100%")

if __name__ == "__main__":
    initial_question = "What are the fundamental properties of two-dimensional materials like graphene, and how can they be harnessed to develop next-generation electronic and photonic devices?"
    initial_question = "What are the long-term economic impacts of implementing universal basic income in developed countries, considering both macroeconomic stability and income inequality"
    initial_question = "What are the key feedback mechanisms in the Earth's climate system that drive tipping points, and how can we model and predict their occurrence to inform global climate policy?"
    initial_question = "Looking for AI-powered research tools for in-depth research and complex questions"

    output_folder = os.path.join(os.getcwd(), "output")
    os.makedirs(output_folder, exist_ok=True)

    safe_question = re.sub(r'[^\w\s-]', '', initial_question[:100])
    output_filename = f"{safe_question}.md"
    output_path = os.path.join(output_folder, output_filename)

    renderer = MarkdownRenderer(output_path)
    generator = QueryGenerator(renderer, num_queries=2, depth=2)
    generator.save_to_markdown(initial_question)

    print(f"Queries saved to {output_path}")

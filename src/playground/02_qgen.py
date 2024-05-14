import json
import os
import re
import time
import sys
from typing import List
from abc import ABC, abstractmethod

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
            f.write("# Subquestions\n\n")

    def render(self, content: str):
        with open(self.filepath, 'a') as f:
            f.write(content + '\n')

class SubQuestionGenerator:
    def __init__(self, renderer: Renderer, num_subquestions: int = 3, depth: int = 3):
        self.num_subquestions = num_subquestions
        self.depth = depth
        self.web_search = BraveSearchClient()
        self.skill = Completion(('Forward', 'SubQuestions'))
        self.total_questions_generated = 0
        self.renderer = renderer
        self.requests_sent_to_search = 0
        self.requests_sent_to_llm = 0
        self.cache_retrievals = 0
        self.total_steps = 0

    def generate_subquestions(self, question: str) -> str:
        logger.debug(f"Generating subquestions for: {question}")
        self.requests_sent_to_search += 1
        search_results = self.web_search.search(question)
        logger.debug(f"Search returned {len(search_results.get('web', {}).get('results', []))} results")

        self.requests_sent_to_llm += 1
        result = self.skill.complete(
            prompt_inputs={
                "ORIGINAL_QUESTION": question,
                "SEARCH_RESULTS": str(search_results),
                "NUM_SUBQUESTIONS": str(self.num_subquestions)
            }
        )
        logger.debug(f"Subquestions result: {result.content}")
        return result.content

    @staticmethod
    def parse_subquestions(text: str) -> List[str]:
        pattern = re.compile(r'<subquestion>(.*?)<\/subquestion>', re.DOTALL)
        subquestions = pattern.findall(text)
        logger.debug(f"Parsed subquestions: {subquestions}")
        return subquestions

    def build_subquestion_list(self, question: str, current_depth: int = 0):
        logger.debug(f"Building subquestion list for: {question} at depth {current_depth}")
        if current_depth >= self.depth:
            return

        subquestions_text = self.generate_subquestions(question)
        subquestions = self.parse_subquestions(subquestions_text)
        self.total_questions_generated += 1
        self.total_steps += len(subquestions) + 1

        self.renderer.render(f"{'    ' * current_depth}- {question}")

        for subquestion in subquestions:
            self.build_subquestion_list(subquestion, current_depth + 1)
            self.total_steps += 1

    def save_to_markdown(self, initial_question: str):
        start_time = time.time()
        with tqdm(total=self.num_subquestions ** self.depth, desc="Generating Subquestions") as pbar:
            self.build_subquestion_list(initial_question)
            pbar.update(self.total_steps)
        elapsed_time = time.time() - start_time
        logger.debug(f"Total questions generated: {self.total_questions_generated}")
        logger.debug(f"Requests sent to search: {self.requests_sent_to_search}")
        logger.debug(f"Requests sent to LLM: {self.requests_sent_to_llm}")
        logger.debug(f"Cache retrievals: {self.cache_retrievals}")
        logger.debug(f"Completed in {elapsed_time:.2f} seconds")
        logger.debug(f"Overall progress: 100%")

if __name__ == "__main__":
    initial_question = "What are the long-term economic impacts of implementing universal basic income in developed countries, considering both macroeconomic stability and income inequality?"

    output_folder = os.path.join(os.getcwd(), "output")
    os.makedirs(output_folder, exist_ok=True)

    safe_question = re.sub(r'[^\w\s-]', '', initial_question[:100])
    output_filename = f"{safe_question}.md"
    output_path = os.path.join(output_folder, output_filename)

    renderer = MarkdownRenderer(output_path)
    generator = SubQuestionGenerator(renderer, num_subquestions=1, depth=10)
    generator.save_to_markdown(initial_question)

    print(f"Subquestions saved to {output_path}")

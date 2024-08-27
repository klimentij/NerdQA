import json
import os
import re
import sys
from typing import List
from pydantic import BaseModel

os.chdir(__file__.split('src/')[0])
sys.path.append(os.getcwd())

from src.llm.completion import Completion
from src.tools.web_search import BraveSearchClient
from src.util.setup_logging import setup_logging

logger = setup_logging(__file__)

class Statement(BaseModel):
    text: str
    evidence: List[str]
    support_score: float
    explanation: str

class StatementGenerator:
    def __init__(self):
        self.web_search = BraveSearchClient()
        self.skill = Completion(('QLoop', 'Statements'))

    def generate_statements(self, main_question: str, current_query: str) -> tuple[List[Statement], dict]:
        logger.info(f"Generating statements for query: {current_query}")
        
        search_results = self.web_search.search(current_query)
        logger.debug(f"Search returned {len(search_results.get('web', {}).get('results', []))} results")

        result = self.skill.complete(
            prompt_inputs={
                "MAIN_QUESTION": main_question,
                "QUERY": current_query,
                "SEARCH_RESULTS": json.dumps(search_results),
                "PREVIOUS_STATEMENTS": ""  # Empty for now, as we're doing a single step
            }
        )

        try:
            response_data = json.loads(result.content)
            statements = [Statement(**stmt) for stmt in response_data['statements']]
            logger.info(f"Generated {len(statements)} statements")
            return statements, search_results
        except json.JSONDecodeError:
            logger.error("Failed to parse JSON response")
            return [], {}
        except KeyError:
            logger.error("Invalid response format")
            return [], {}

def save_to_markdown(statements: List[Statement], search_results: dict, filepath: str):
    def get_snippet_text(snippet_id: str) -> str:
        for result in search_results.get('web', {}).get('results', []):
            if result['description']['id'] == snippet_id:
                return result['description']['text']
            for snippet in result.get('extra_snippets', []):
                if snippet['id'] == snippet_id:
                    return snippet['text']
        return f"Snippet text not found for ID: {snippet_id}"

    with open(filepath, 'w') as f:
        f.write("# Generated Statements\n\n")
        for idx, statement in enumerate(statements, 1):
            f.write(f"## Statement {idx}\n\n")
            f.write(f"**Statement:** {statement.text}\n\n")
            f.write(f"**Evidence:**\n")
            for evidence in statement.evidence:
                snippet_text = get_snippet_text(evidence)
                f.write(f"- {evidence}: {snippet_text}\n")
            f.write(f"\n**Support Score:** {statement.support_score}\n\n")
            f.write(f"**Explanation:** {statement.explanation}\n\n")
            f.write("---\n\n")

if __name__ == "__main__":
    main_question = "How LLMs affect the freedom of speech in Russia?"
    current_query = main_question  # Use main_question as the initial current_query

    output_folder = os.path.join(os.getcwd(), "output")
    os.makedirs(output_folder, exist_ok=True)

    safe_query = re.sub(r'[^\w\s-]', '', current_query[:30])
    output_filename = f"{safe_query}.md"
    output_path = os.path.join(output_folder, output_filename)

    generator = StatementGenerator()
    statements, search_results = generator.generate_statements(main_question, current_query)
    save_to_markdown(statements, search_results, output_path)

    print(f"Statements saved to {output_path}")
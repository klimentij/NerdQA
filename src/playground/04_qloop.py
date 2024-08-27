import json
import os
import re
import sys
from typing import List

os.chdir(__file__.split('src/')[0])
sys.path.append(os.getcwd())

from src.llm.completion import Completion
from src.tools.web_search import BraveSearchClient
from src.util.setup_logging import setup_logging

logger = setup_logging(__file__)

class StatementGenerator:
    def __init__(self):
        self.web_search = BraveSearchClient()
        self.skill = Completion(('QLoop', 'Statements'))

    def generate_statements(self, main_question: str, current_query: str) -> tuple[List[dict], dict]:
        logger.info(f"Generating statements for query: {current_query}")
        
        search_results = self.web_search.search(current_query)

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
            statements = response_data['statements']  # No need to create Statement objects
            logger.info(f"Generated {len(statements)} statements")
            return statements, search_results
        except json.JSONDecodeError:
            logger.error("Failed to parse JSON response")
            return [], {}
        except KeyError:
            logger.error("Invalid response format")
            return [], {}

class QueryGenerator:
    def __init__(self):
        self.skill = Completion(('QLoop', 'Query'))

    def generate_next_query(self, main_question: str, previous_queries_and_statements: str) -> str:
        logger.info("Generating next query")
        
        result = self.skill.complete(
            prompt_inputs={
                "MAIN_QUESTION": main_question,
                "PREVIOUS_QUERIES_AND_STATEMENTS": previous_queries_and_statements,
            }
        )

        try:
            response_data = json.loads(result.content)
            next_query = response_data['next_query']
            logger.info(f"Generated next query: {next_query}")
            return next_query
        except json.JSONDecodeError:
            logger.error("Failed to parse JSON response")
            return ""
        except KeyError:
            logger.error("Invalid response format")
            return ""

class Pipeline:
    def __init__(self):
        self.statement_generator = StatementGenerator()
        self.query_generator = QueryGenerator()

    def run(self, main_question: str, iterations: int):
        current_query = main_question
        previous_queries_and_statements = ""

        output_folder = os.path.join(os.getcwd(), "output")
        os.makedirs(output_folder, exist_ok=True)

        safe_question = re.sub(r'[^\w\s-]', '', main_question[:30])
        output_filename = f"{safe_question}_report.md"
        output_path = os.path.join(output_folder, output_filename)

        with open(output_path, 'w') as f:
            f.write(f"# {main_question}\n\n")

        for iteration in range(iterations):
            # Generate statements
            statements, search_results = self.statement_generator.generate_statements(main_question, current_query)
            self.append_to_markdown(current_query, statements, search_results, output_path, iteration + 1)
            print(f"Iteration {iteration + 1} appended to {output_path}")

            # Update previous_queries_and_statements
            previous_queries_and_statements += f"\nQuery: {current_query}\n"
            for stmt in statements:
                previous_queries_and_statements += f"Statement: {stmt['text']}\n"

            # Generate next query
            current_query = self.query_generator.generate_next_query(main_question, previous_queries_and_statements)

            # Append next query to the report
            with open(output_path, 'a') as f:
                f.write(f"\n## Next Query\n\n{current_query}\n\n")

        print("Query loop completed.")

    @staticmethod
    def append_to_markdown(query: str, statements: List[dict], search_results: dict, filepath: str, iteration: int):
        def get_snippet_text(snippet_id: str) -> str:
            for result in search_results.get('web', {}).get('results', []):
                if result['description']['id'] == snippet_id:
                    return result['description']['text']
                for snippet in result.get('extra_snippets', []):
                    if snippet['id'] == snippet_id:
                        return snippet['text']
            return f"Snippet text not found for ID: {snippet_id}"

        with open(filepath, 'a') as f:
            f.write(f"\n## Iteration {iteration}\n\n")
            f.write(f"### Query\n\n{query}\n\n")
            f.write("### Generated Statements\n\n")
            for idx, statement in enumerate(statements, 1):
                f.write(f"#### Statement {idx}\n\n")
                f.write(f"**Statement:** {statement['text']}\n\n")
                f.write(f"**Evidence:**\n")
                for evidence in statement['evidence']:
                    snippet_text = get_snippet_text(evidence)
                    f.write(f"- {evidence}: {snippet_text}\n")
                f.write(f"\n**Support Score:** {statement['support_score']}\n\n")
                f.write(f"**Explanation:** {statement['explanation']}\n\n")
                f.write("---\n\n")

if __name__ == "__main__":
    main_question = "How LLMs affect the freedom of speech in Russia?"
    pipeline = Pipeline()
    pipeline.run(main_question=main_question, iterations=3)
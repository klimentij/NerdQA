import json
import os
import re
import sys
import hashlib
from typing import List, Tuple, Optional

os.chdir(__file__.split('src/')[0])
sys.path.append(os.getcwd())

from src.llm.completion import Completion
from src.tools.web_search import BraveSearchClient
from src.util.setup_logging import setup_logging

logger = setup_logging(__file__)

STATEMENT_ID_DIGITS = 10

class StatementGenerator:
    def __init__(self):
        self.web_search = BraveSearchClient()
        self.skill = Completion(('QLoop', 'Statements'))

    def generate_statements(self, main_question: str, current_query: str, previous_queries_and_statements: str) -> Tuple[List[dict], dict]:
        logger.info(f"Generating statements for query: {current_query}")
        
        search_results = self.web_search.search(current_query)

        result = self.skill.complete(
            prompt_inputs={
                "MAIN_QUESTION": main_question,
                "QUERY": current_query,
                "SEARCH_RESULTS": json.dumps(search_results),
                "PREVIOUS_QUERIES_AND_STATEMENTS": previous_queries_and_statements
            }
        )

        try:
            response_data = json.loads(result.content)
            statements = response_data['statements']
            
            for statement in statements:
                statement_hash = int(hashlib.md5(statement['text'].encode()).hexdigest(), 16)
                statement['id'] = f"S{statement_hash % 10**STATEMENT_ID_DIGITS:0{STATEMENT_ID_DIGITS}d}"
            
            logger.info(f"Generated {len(statements)} statements")
            return statements, search_results
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
        self.skill = Completion(('QLoop', 'Query'))

    def generate_next_queries(self, main_question: str, previous_queries_and_statements: str, num_queries: int) -> List[str]:
        logger.info(f"Generating next {num_queries} queries")
        
        result = self.skill.complete(
            prompt_inputs={
                "MAIN_QUESTION": main_question,
                "PREVIOUS_QUERIES_AND_STATEMENTS": previous_queries_and_statements,
                "NUM_QUERIES": num_queries
            }
        )

        try:
            response_data = json.loads(result.content)
            next_queries = response_data['next_queries']
            logger.info(f"Generated {len(next_queries)} next queries")
            return next_queries
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            return []
        except KeyError as e:
            logger.error(f"Invalid response format: missing key {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error in generate_next_queries: {e}")
            return []

class Pipeline:
    def __init__(self):
        self.statement_generator = StatementGenerator()
        self.query_generator = QueryGenerator()
        self.all_statements = {}  # New dictionary to store all statements

    def run(self, main_question: str, iterations: int, num_queries: int) -> None:
        current_queries = [main_question]
        previous_queries_and_statements = ""

        output_folder = os.path.join(os.getcwd(), "output")
        os.makedirs(output_folder, exist_ok=True)

        safe_question = re.sub(r'[^\w\s-]', '', main_question[:30])
        output_filename = f"{safe_question}_report.md"
        output_path = os.path.join(output_folder, output_filename)

        with open(output_path, 'w') as f:
            f.write(f"# {main_question}\n\n")

        for iteration in range(iterations):
            # Process only num_queries queries
            for current_query in current_queries[:num_queries]:
                statements, search_results = self.statement_generator.generate_statements(main_question, current_query, previous_queries_and_statements)
                
                # Store all generated statements
                for stmt in statements:
                    self.all_statements[stmt['id']] = stmt['text']

                previous_queries_and_statements += f"\nQuery: {current_query}\n"
                for stmt in statements:
                    previous_queries_and_statements += f"Statement {stmt['id']}: {stmt['text']}\n"
                
                if not statements:
                    previous_queries_and_statements += f"\nNo relevant evidence was found for this query\n"

                self.append_to_markdown(current_query, statements, search_results, output_path, iteration + 1, self.all_statements)
                print(f"Iteration {iteration + 1}, Query '{current_query}' appended to {output_path}")

            next_queries = self.query_generator.generate_next_queries(main_question, previous_queries_and_statements, num_queries)
            if not next_queries:
                logger.error("Failed to generate next queries. Stopping the pipeline.")
                break

            current_queries = next_queries
            self.append_next_queries_to_markdown(next_queries[:num_queries], output_path)

        print("Query loop completed.")

    @staticmethod
    def append_next_queries_to_markdown(next_queries: List[str], filepath: str) -> None:
        with open(filepath, 'a') as f:
            f.write("\n## Next Queries\n\n")
            for idx, query in enumerate(next_queries, 1):
                f.write(f"{idx}. {query}\n")
            f.write("\n")

    @staticmethod
    def append_to_markdown(query: str, statements: List[dict], search_results: dict, filepath: str, iteration: int, all_statements: dict) -> None:
        def get_snippet_text(snippet_id: str) -> str:
            if snippet_id.startswith('S'):
                statement_text = all_statements.get(snippet_id, "Statement text not found")
                return f"[Previous statement {snippet_id}]: {statement_text}"
            web_results = search_results.get('web', {}).get('results', [])
            for result in web_results:
                if result.get('description', {}).get('id') == snippet_id:
                    return result['description'].get('text', '')
                for snippet in result.get('extra_snippets', []):
                    if snippet.get('id') == snippet_id:
                        return snippet.get('text', '')
            return f"Snippet text not found for ID: {snippet_id}"

        with open(filepath, 'a') as f:
            f.write(f"\n## Iteration {iteration}\n\n")
            f.write(f"### Query\n\n{query}\n\n")
            f.write("### Generated Statements\n\n")
            for idx, statement in enumerate(statements, 1):
                f.write(f"#### Statement {idx} (ID: {statement['id']})\n\n")
                f.write(f"**Statement:** {statement['text']}\n\n")
                f.write(f"**Evidence:**\n")
                for evidence in statement['evidence']:
                    snippet_text = get_snippet_text(evidence)
                    f.write(f"- {evidence}: {snippet_text}\n")
                f.write(f"\n**Support Score:** {statement['support_score']}\n\n")
                f.write(f"**Explanation:** {statement['explanation']}\n\n")
                f.write("---\n\n")

            if not statements:
                f.write(f"\n### Note\n\nNo relevant evidence was found for this query. The research will continue with the next iteration.\n\n")

if __name__ == "__main__":
    main_question = "How LLMs affect the freedom of speech in Russia?"
    pipeline = Pipeline()
    pipeline.run(main_question=main_question, iterations=3, num_queries=2)
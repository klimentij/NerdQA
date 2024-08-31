import json
import os
import re
import sys
import datetime
import hashlib
import time
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

    def generate_statements(self, main_question: str, current_query: str, previous_queries_and_statements: str, metadata: dict) -> Tuple[List[dict], dict]:
        logger.info(f"Generating statements for query: {current_query}")
        
        search_results = self.web_search.search(current_query)

        result = self.skill.complete(
            prompt_inputs={
                "MAIN_QUESTION": main_question,
                "QUERY": current_query,
                "SEARCH_RESULTS": json.dumps(search_results),
                "PREVIOUS_QUERIES_AND_STATEMENTS": previous_queries_and_statements
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

    def generate_next_queries(self, main_question: str, previous_queries_and_statements: str, previous_analysis: str, num_queries: int, metadata: dict) -> List[str]:
        logger.info(f"Generating next {num_queries} queries")
        
        result = self.skill.complete(
            prompt_inputs={
                "MAIN_QUESTION": main_question,
                "PREVIOUS_QUERIES_AND_STATEMENTS": previous_queries_and_statements,
                "PREVIOUS_ANALYSIS": previous_analysis,
                "NUM_QUERIES": num_queries
            },
            completion_kwargs={"metadata": metadata}
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

class AnswerGenerator:
    def __init__(self):
        self.skill = Completion(('QLoop', 'Answer'))

    def generate_analysis_and_synthesis(self, main_question: str, research_history: str, metadata: dict) -> dict:
        logger.info("Generating research analysis and synthesis")
        
        result = self.skill.complete(
            prompt_inputs={
                "MAIN_QUESTION": main_question,
                "RESEARCH_HISTORY": research_history
            },
            completion_kwargs={"metadata": metadata}
        )

        try:
            # Check if the result has the expected structure
            if not result.content:
                logger.error("Empty response from LLM")
                return {}

            response_data = json.loads(result.content)
            logger.info("Generated research analysis and synthesis")
            return response_data
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            return {}
        except AttributeError as e:
            logger.error(f"Unexpected response structure: {e}")
            return {}
        except Exception as e:
            logger.error(f"Unexpected error in generate_analysis_and_synthesis: {e}")
            return {}

class Pipeline:
    def __init__(self):
        self.statement_generator = StatementGenerator()
        self.query_generator = QueryGenerator()
        self.answer_generator = AnswerGenerator()
        self.all_statements = {}  # Dictionary to store all statements
        self.all_evidence = {}  # Dictionary to store all evidence
        self.pipeline_start_ts = int(time.time())
        self.trace_id = f"T{self.pipeline_start_ts}"
        self.session_id = f"S{self.pipeline_start_ts}"
        self.main_question = ""
        self.metadata = {}
        self.latest_answer = []

    def run(self, main_question: str, iterations: int, num_queries: int) -> None:
        self.main_question = main_question
        self.metadata = self.get_metadata()
        current_queries = [main_question]
        previous_queries_and_statements = ""
        previous_analysis = ""

        output_folder = os.path.join(os.getcwd(), "output")
        os.makedirs(output_folder, exist_ok=True)

        safe_question = re.sub(r'[^\w\s-]', '', main_question[:30])
        output_filename = f"{safe_question}_report.html"
        self.output_path = os.path.join(output_folder, output_filename)

        for iteration in range(iterations):
            # Process only num_queries queries
            for query_index, current_query in enumerate(current_queries[:num_queries], 1):
                # Update metadata with iteration and query indices
                metadata = self.get_metadata()
                metadata['generation_name_suffix'] = f" [It{iteration+1} Q{query_index}]"

                statements, search_results = self.statement_generator.generate_statements(
                    main_question, current_query, previous_queries_and_statements, metadata
                )
                
                # Store all generated statements and evidence
                for stmt in statements:
                    self.all_statements[stmt['id']] = stmt  # Store the entire statement dictionary
                    for evidence in stmt['evidence']:
                        if evidence.startswith('E'):
                            self.all_evidence[evidence] = self.get_snippet_text(evidence, search_results)

                previous_queries_and_statements += f"\nQuery: {current_query}\n"
                if statements:
                    for stmt in statements:
                        previous_queries_and_statements += f"Statement {stmt['id']}: {stmt['text']}\n"
                else:
                    previous_queries_and_statements += "No relevant evidence was found for this query, so no statements were generated.\n"

                print(f"Iteration {iteration + 1}, Query '{current_query}' processed")

            # Update metadata for analysis and synthesis
            metadata = self.get_metadata()
            metadata['generation_name_suffix'] = f" [It{iteration+1}]"

            # Generate research analysis and synthesis
            analysis_and_synthesis = self.answer_generator.generate_analysis_and_synthesis(
                main_question, previous_queries_and_statements, metadata
            )
            if analysis_and_synthesis:
                self.latest_answer = analysis_and_synthesis.get('synthesized_answer', [])
                previous_analysis = json.dumps(analysis_and_synthesis)
            else:
                logger.warning(f"Failed to generate analysis and synthesis for iteration {iteration + 1}")
                previous_analysis = ""

            # Update metadata for generating next queries
            metadata = self.get_metadata()
            metadata['generation_name_suffix'] = f" [It{iteration+1}]"

            next_queries = self.query_generator.generate_next_queries(
                main_question, previous_queries_and_statements, previous_analysis, num_queries, metadata
            )
            if not next_queries:
                logger.error("Failed to generate next queries. Stopping the pipeline.")
                break

            current_queries = next_queries

            # Generate the HTML report after each iteration
            self.generate_html_report()

        print("Query loop completed.")

    def get_metadata(self) -> dict:
        return {
            "trace_name": self.main_question[:],
            "trace_id": self.trace_id,
            "trace_user_id": "Klim",
            "session_id": self.session_id,
            "generation_name_suffix": ""
        }

    def get_snippet_text(self, snippet_id: str, search_results: dict) -> str:
        if snippet_id.startswith('S'):
            return self.all_statements.get(snippet_id, "Statement text not found")
        for result in search_results.get('results', []):
            if result.get('id') == snippet_id:
                return result.get('text', '')
        return f"Snippet text not found for ID: {snippet_id}"

    def generate_html_report(self) -> None:
        html_content = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{self.main_question}</title>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; padding: 20px; }}
                h1 {{ color: #333; }}
                table {{ border-collapse: collapse; width: 100%; }}
                th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                th {{ background-color: #f2f2f2; }}
            </style>
        </head>
        <body>
            <h1>{self.main_question}</h1>
            <h2>Latest Available Answer</h2>
            {self.generate_latest_answer_html()}
            <h2>Support Table</h2>
            {self.generate_support_table_html()}
        </body>
        </html>
        """

        with open(self.output_path, 'w') as f:
            f.write(html_content)

    def generate_latest_answer_html(self) -> str:
        answer_html = "<p>"
        for sentence in self.latest_answer:
            support_links = ' '.join([f'<a href="#{s}">[{s}]</a>' for s in sentence['support']])
            answer_html += f"{sentence['sentence']} {support_links}<br>"
        answer_html += "</p>"
        return answer_html

    def generate_support_table_html(self) -> str:
        table_html = """
        <table>
            <tr>
                <th>ID</th>
                <th>Text</th>
                <th>Support</th>
            </tr>
        """
        for stmt_id, stmt_text in self.all_statements.items():
            table_html += f"""
            <tr id="{stmt_id}">
                <td>{stmt_id}</td>
                <td>{stmt_text}</td>
                <td>{self.get_statement_support(stmt_id)}</td>
            </tr>
            """
        for evidence_id, evidence_text in self.all_evidence.items():
            table_html += f"""
            <tr id="{evidence_id}">
                <td>{evidence_id}</td>
                <td>{evidence_text}</td>
                <td>External evidence</td>
            </tr>
            """
        table_html += "</table>"
        return table_html

    def get_statement_support(self, stmt_id: str) -> str:
        statement = self.all_statements.get(stmt_id)
        if isinstance(statement, dict):
            return ', '.join([f'<a href="#{e}">{e}</a>' for e in statement.get('evidence', [])])
        return "No support found"

if __name__ == "__main__":
    main_question = "How do LLMs affect the freedom of speech in Russia?"
    main_question = "What is the impact of AI on the job market in Guatemala?"

    pipeline = Pipeline()
    pipeline.run(main_question=main_question, iterations=2, num_queries=2)

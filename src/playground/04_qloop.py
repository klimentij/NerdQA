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
        self.pipeline_start_ts = int(time.time())
        self.trace_id = f"T{self.pipeline_start_ts}"
        self.session_id = f"S{self.pipeline_start_ts}"
        self.main_question = ""
        self.metadata = {}

    def run(self, main_question: str, iterations: int, num_queries: int) -> None:
        self.main_question = main_question
        self.metadata = self.get_metadata()
        current_queries = [main_question]
        previous_queries_and_statements = ""
        previous_analysis = ""

        output_folder = os.path.join(os.getcwd(), "output")
        os.makedirs(output_folder, exist_ok=True)

        safe_question = re.sub(r'[^\w\s-]', '', main_question[:30])
        output_filename = f"{safe_question}_report.md"
        output_path = os.path.join(output_folder, output_filename)

        with open(output_path, 'w') as f:
            f.write(f"# {main_question}\n\n")

        for iteration in range(iterations):
            # Process only num_queries queries
            for query_index, current_query in enumerate(current_queries[:num_queries], 1):
                # Update metadata with iteration and query indices
                metadata = self.get_metadata()
                metadata['generation_name_suffix'] = f" [It{iteration+1} Q{query_index}]"

                statements, search_results = self.statement_generator.generate_statements(
                    main_question, current_query, previous_queries_and_statements, metadata
                )
                
                # Store all generated statements
                for stmt in statements:
                    self.all_statements[stmt['id']] = stmt['text']

                previous_queries_and_statements += f"\nQuery: {current_query}\n"
                if statements:
                    for stmt in statements:
                        previous_queries_and_statements += f"Statement {stmt['id']}: {stmt['text']}\n"
                else:
                    previous_queries_and_statements += "No relevant evidence was found for this query, so no statements were generated.\n"

                self.append_to_markdown(current_query, statements, search_results, output_path, iteration + 1, self.all_statements)
                print(f"Iteration {iteration + 1}, Query '{current_query}' appended to {output_path}")

            # Update metadata for analysis and synthesis
            metadata = self.get_metadata()
            metadata['generation_name_suffix'] = f" [It{iteration+1}]"

            # Generate research analysis and synthesis
            analysis_and_synthesis = self.answer_generator.generate_analysis_and_synthesis(
                main_question, previous_queries_and_statements, metadata
            )
            if analysis_and_synthesis:
                self.append_analysis_and_synthesis_to_markdown(analysis_and_synthesis, output_path, iteration + 1)
                previous_analysis = json.dumps(analysis_and_synthesis)
            else:
                logger.warning(f"Failed to generate analysis and synthesis for iteration {iteration + 1}")
                self.append_error_to_markdown(output_path, iteration + 1)
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
            self.append_next_queries_to_markdown(next_queries[:num_queries], output_path)

        print("Query loop completed.")

    def get_metadata(self) -> dict:
        return {
            "trace_name": self.main_question[:],
            "trace_id": self.trace_id,
            "trace_user_id": "Klim",
            "session_id": self.session_id,
            "generation_name_suffix": ""  # Add this line
        }

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
            for result in search_results.get('results', []):
                if result.get('id') == snippet_id:
                    return result.get('text', '')
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

    @staticmethod
    def append_analysis_and_synthesis_to_markdown(analysis_and_synthesis: dict, filepath: str, iteration: int) -> None:
        with open(filepath, 'a') as f:
            f.write(f"\n## Research Analysis and Synthesis (Iteration {iteration})\n\n")
            
            f.write("### Critical Analysis\n\n")
            critical_analysis = analysis_and_synthesis.get('critical_analysis', {})
            f.write(f"**Overall Assessment:** {critical_analysis.get('overall_assessment', 'N/A')}\n\n")
            
            f.write("**Over-explored Areas:**\n")
            for area in critical_analysis.get('over_explored_areas', []):
                f.write(f"- {area}\n")
            f.write("\n")
            
            f.write("**Under-explored Areas:**\n")
            for area in critical_analysis.get('under_explored_areas', []):
                f.write(f"- {area}\n")
            f.write("\n")
            
            f.write(f"**Evidence Quality:** {critical_analysis.get('evidence_quality', 'N/A')}\n\n")
            f.write(f"**Next Directions:** {critical_analysis.get('next_directions', 'N/A')}\n\n")
            f.write(f"**Limitations:** {critical_analysis.get('limitations', 'N/A')}\n\n")
            
            f.write("### Best Possible Answer Synthesis\n\n")
            synthesis = analysis_and_synthesis.get('synthesized_answer', [])
            for sentence in synthesis:
                f.write(f"- {sentence['sentence']}\n")
                f.write(f"  Support: {', '.join(sentence['support'])}\n\n")

    @staticmethod
    def append_error_to_markdown(filepath: str, iteration: int) -> None:
        with open(filepath, 'a') as f:
            f.write(f"\n## Research Analysis and Synthesis (Iteration {iteration})\n\n")
            f.write("Error: Failed to generate research analysis and synthesis for this iteration.\n\n")

if __name__ == "__main__":
    main_question = "Hodw LLMs affect the freedom of speech in Russia?????!"
    # main_question = "Can you refer me to  research that adapts the concept of Word Mover's Distance to sentences, addressing the limitations of bag-of-words approaches and considering the order of words for text similarity?"
    # main_question = "What psychological biases and cognitive mechanisms make people more susceptible to political polarization on social media??"

    pipeline = Pipeline()
    pipeline.run(main_question=main_question, iterations=2, num_queries=2)

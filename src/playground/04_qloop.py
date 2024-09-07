import json
import os
import re
import sys
import datetime
import hashlib
import time
from typing import List, Tuple, Optional
import markdown

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

    def generate_next_queries(self, main_question: str, previous_queries_and_statements: str, current_best_answer: str, num_queries: int, metadata: dict) -> List[str]:
        logger.info(f"Generating next {num_queries} queries")
        
        result = self.skill.complete(
            prompt_inputs={
                "MAIN_QUESTION": main_question,
                "PREVIOUS_QUERIES_AND_STATEMENTS": previous_queries_and_statements,
                "CURRENT_BEST_ANSWER": current_best_answer,
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

    def generate_answer(self, main_question: str, research_history: str, metadata: dict) -> str:
        logger.info("Generating research answer")
        
        result = self.skill.complete(
            prompt_inputs={
                "MAIN_QUESTION": main_question,
                "RESEARCH_HISTORY": research_history
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

class Pipeline:
    def __init__(self):
        self.statement_generator = StatementGenerator()
        self.query_generator = QueryGenerator()
        self.answer_generator = AnswerGenerator()
        self.all_statements = {}
        self.all_evidence = {}
        self.pipeline_start_ts = int(time.time())
        self.trace_id = f"T{self.pipeline_start_ts}"
        self.session_id = f"S{self.pipeline_start_ts}"
        self.main_question = ""
        self.metadata = {}
        self.latest_answer = ""
        self.all_answers = []  # Store all generated answers

    def run(self, main_question: str, iterations: int, num_queries: int) -> None:
        self.main_question = main_question
        self.metadata = self.get_metadata()
        previous_queries_and_statements = ""

        output_folder = os.path.join(os.getcwd(), "output")
        os.makedirs(output_folder, exist_ok=True)

        safe_question = re.sub(r'[^\w\s-]', '', main_question[:30])
        output_filename = f"{safe_question}_report.html"
        self.output_path = os.path.join(output_folder, output_filename)

        current_queries = []

        for iteration in range(iterations):
            metadata = self.get_metadata()
            metadata['generation_name_suffix'] = f" [It{iteration+1}]"

            # Generate queries (for the first iteration or using previous data)
            if iteration == 0:
                current_queries = self.query_generator.generate_next_queries(
                    main_question, "", "", num_queries, metadata
                )
            else:
                current_queries = self.query_generator.generate_next_queries(
                    main_question, previous_queries_and_statements, self.latest_answer, num_queries, metadata
                )

            # Process queries and generate statements
            for query_index, current_query in enumerate(current_queries[:num_queries], 1):
                metadata = self.get_metadata()
                metadata['generation_name_suffix'] = f" [It{iteration+1} Q{query_index}]"

                statements, search_results = self.statement_generator.generate_statements(
                    main_question, current_query, previous_queries_and_statements, metadata
                )
                
                # Store all generated statements and evidence
                for stmt in statements:
                    self.all_statements[stmt['id']] = stmt
                    for evidence in stmt['evidence']:
                        if evidence.startswith('E'):
                            evidence_data = self.get_snippet_text(evidence, search_results)
                            self.all_evidence[evidence] = evidence_data

                previous_queries_and_statements += f"\nQuery: {current_query}\n"
                if statements:
                    for stmt in statements:
                        previous_queries_and_statements += f"Statement {stmt['id']}: {stmt['text']}\n"
                else:
                    previous_queries_and_statements += "No relevant evidence was found for this query, so no statements were generated.\n"

                print(f"Iteration {iteration + 1}, Query '{current_query}' processed")

            # Generate research answer
            metadata = self.get_metadata()
            metadata['generation_name_suffix'] = f" [It{iteration+1}]"
            answer = self.answer_generator.generate_answer(
                main_question, previous_queries_and_statements, metadata
            )
            if answer:
                self.latest_answer = answer
                self.all_answers.append(answer)
            else:
                logger.warning(f"Failed to generate answer for iteration {iteration + 1}")

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

    def get_snippet_text(self, snippet_id: str, search_results: dict) -> dict:
        if snippet_id.startswith('S'):
            return self.all_statements.get(snippet_id, {"text": "Statement text not found", "meta": {}})
        for result in search_results.get('results', []):
            if result.get('id') == snippet_id:
                return {
                    "text": result.get('text', ''),
                    "meta": {
                        "url": result.get('meta', {}).get('url', ''),
                        "title": result.get('meta', {}).get('title', ''),
                        "page_age": result.get('meta', {}).get('page_age', '')
                    }
                }
        return {"text": f"Snippet text not found for ID: {snippet_id}", "meta": {}}

    def generate_html_report(self) -> None:
        md = markdown.Markdown()
        
        def process_answer(answer):
            html = md.convert(answer)
            citations = re.findall(r'\[(S\d+|E\d+)\]', html)
            html = re.sub(r'\[(S\d+|E\d+)\]', r'<a href="#tree-\1" class="citation" id="cite-\1">[\1]</a>', html)
            return html, citations
        
        processed_answers = [process_answer(answer) for answer in self.all_answers]
        html_answers = [answer[0] for answer in processed_answers]
        answer_citations = [answer[1] for answer in processed_answers]
        
        html_content = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{self.main_question}</title>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; padding: 20px; }}
                h1, h2, h3 {{ color: #333; }}
                .nav-buttons {{ margin-bottom: 20px; }}
                .nav-buttons button {{ margin-right: 10px; }}
                .citation-tree {{ margin-top: 20px; }}
                .citation-tree ul {{ list-style-type: none; }}
                .citation-tree li {{ margin: 10px 0; }}
                .back-to-top {{ text-decoration: none; color: #0066cc; }}
            </style>
            <script>
                const answers = {json.dumps(html_answers)};
                const answerCitations = {json.dumps(answer_citations)};
                let currentIndex = {len(html_answers) - 1};

                function showAnswer(index) {{
                    if (index >= 0 && index < answers.length) {{
                        document.getElementById('answer-content').innerHTML = answers[index];
                        document.getElementById('current-answer-index').textContent = `Answer ${{index + 1}} of ${{answers.length}}`;
                        
                        document.getElementById('prev-btn').disabled = (index === 0);
                        document.getElementById('next-btn').disabled = (index === answers.length - 1);
                        currentIndex = index;

                        // Update citation trees
                        const citationTrees = document.querySelectorAll('.citation-tree');
                        citationTrees.forEach(tree => {{
                            const treeId = tree.id.replace('tree-', '');
                            if (answerCitations[index].includes(treeId)) {{
                                tree.style.display = 'block';
                            }} else {{
                                tree.style.display = 'none';
                            }}
                        }});
                    }}
                }}

                window.onload = function() {{
                    showAnswer(currentIndex);
                }};
            </script>
        </head>
        <body>
            <h1>{self.main_question}</h1>
            <h2>Generated Answers</h2>
            <div class="nav-buttons">
                <button id="prev-btn" onclick="showAnswer(currentIndex - 1)">Previous</button>
                <span id="current-answer-index">Answer {len(html_answers)} of {len(html_answers)}</span>
                <button id="next-btn" onclick="showAnswer(currentIndex + 1)">Next</button>
            </div>
            <div id="answer-content"></div>
            <h2>Citation Trees</h2>
            {self.generate_citation_tree_html()}
        </body>
        </html>
        """

        with open(self.output_path, 'w') as f:
            f.write(html_content)

    def generate_citation_tree_html(self) -> str:
        def build_tree(node_id, depth=0, max_depth=5, visited=None):
            if visited is None:
                visited = set()
            
            if depth >= max_depth or node_id in visited:
                return None
            
            visited.add(node_id)
            
            if node_id.startswith('S'):
                statement = self.all_statements.get(node_id)
                if isinstance(statement, dict):
                    children = [build_tree(e, depth + 1, max_depth, visited.copy()) for e in statement.get('evidence', [])]
                    children = [child for child in children if child is not None]
                    return {
                        'id': node_id,
                        'text': statement['text'],
                        'children': children
                    }
            elif node_id.startswith('E'):
                evidence = self.all_evidence.get(node_id, "Evidence text not found")
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

        def render_tree(node):
            if not node:
                return ""
            
            html = f'<li id="tree-{node["id"]}"><strong>{node["id"]}:</strong> {node["text"]}'
            if node['id'].startswith('E'):
                evidence = self.all_evidence.get(node['id'], {})
                url = evidence.get('meta', {}).get('url', '')
                if url:
                    html += f'<br><a href="{url}" target="_blank">{url}</a>'
            if node['children']:
                html += '<ul>'
                for child in node['children']:
                    html += render_tree(child)
                html += '</ul>'
            html += '</li>'
            return html

        # Build and render trees for each top-level statement
        trees_html = ""
        for stmt_id in self.all_statements.keys():
            tree = build_tree(stmt_id)
            if tree:
                trees_html += f'<div class="citation-tree" id="tree-{stmt_id}">'
                trees_html += f'<h3>Citation Tree for Statement {stmt_id}</h3>'
                trees_html += '<ul>'
                trees_html += render_tree(tree)
                trees_html += '</ul>'
                trees_html += f'<a href="#cite-{stmt_id}" class="back-to-top">↑ Back to citation</a>'
                trees_html += '</div>'

        return trees_html

if __name__ == "__main__":
    main_question = "How do LLMs affect the freedom of speech in Russia?"
    main_question = "What is the impact of AI on the job market in Guatemala?"
    main_question = "Do I really have to learn JS before learning node.js?"
    main_question = "How to work up to 10 hrs a week while travelling and living in a van, and earn more and more?"
    main_question = "How can we develop an efficient and scalable method for performing k-NN search with cross-encoders that significantly reduces computational costs and resource demands while maintaining high recall accuracy in large-scale datasets?"
    main_question = "what search engine has indexed full body research papers? so i could search by phrase from the body (not abstract) and find this paper"
    main_question = "I need to find an optimal number of meals a day based on scientific evidence. Weight 80 kg, 34 y.o., 180 cm, train 3 times a week with some weights. I'd prefer less time on the kitchen, but more time for life and fun"
    main_question = "Who is right in the Ukraine-Russia war"
    main_question = "Who is right in the Israel-Gaza conflict?"
    main_question = "how to make pgvector hnsw work with proper pre-filter  and how to select from this if I want to pre filter by 3-4 categories? example queries"
    main_question = "What psychological biases and cognitive mechanisms make people more susceptible to political polarization on social media?"
    main_question = "what people think about Company called 'voyage ai', can i trust my data to it"
    

    pipeline = Pipeline()
    pipeline.run(main_question=main_question, iterations=3, num_queries=2)

import json
import os
import sys
import hashlib
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime

os.chdir(__file__.split('src/')[0])
sys.path.append(os.getcwd())

from src.llm.completion import Completion
from src.tools.web_search import BraveSearchClient
from src.util.setup_logging import setup_logging

logger = setup_logging(__file__)

STATEMENT_ID_DIGITS = 10

# Pydantic models
class Statement(BaseModel):
    id: str
    text: str
    evidence: List[str]
    support_score: float
    explanation: str

class SearchResult(BaseModel):
    id: str
    text: str
    meta: Dict[str, Any] = Field(default_factory=dict)

class CriticalAnalysis(BaseModel):
    overall_assessment: str
    over_explored_areas: List[str]
    under_explored_areas: List[str]
    evidence_quality: str
    next_directions: List[str]
    limitations: List[str]

class SynthesizedAnswer(BaseModel):
    sentence: str
    support: List[str]

class ResearchAnalysisAndSynthesis(BaseModel):
    critical_analysis: CriticalAnalysis
    synthesized_answer: List[SynthesizedAnswer]

class NextQueryGeneration(BaseModel):
    progress_assessment: str
    strategy: str
    next_queries: List[str]

class StatementGeneration(BaseModel):
    reflection: str
    statements: List[Statement]

class PipelineState(BaseModel):
    main_question: str
    iterations: List[Dict[str, Any]] = Field(default_factory=list)
    all_statements: Dict[str, Statement] = Field(default_factory=dict)

class PipelineConfig(BaseModel):
    main_question: str
    iterations: int = 2
    queries_per_iteration: int = 1
    output_folder: str = Field(default_factory=lambda: os.path.join(os.getcwd(), "output"))
    statement_threshold: float = 0.9

# Pipeline step functions
def retrieval_step(input: str, web_search: BraveSearchClient) -> List[SearchResult]:
    logger.info(f"Performing web search for query: {input}")
    try:
        search_results = web_search.search(input)
        results = search_results.get('results', [])
        return [SearchResult(
            id=result.get('id', str(i)),
            text=result.get('text', ''),
            meta=result.get('meta', {})
        ) for i, result in enumerate(results) if isinstance(result, dict)]
    except Exception as e:
        logger.error(f"Error during web search: {str(e)}", exc_info=True)
        return []

def generate_statements_step(
    input: Dict[str, Any],
    skill: Completion
) -> StatementGeneration:
    logger.info(f"Generating statements for query: {input['current_query']}")
    
    previous_queries_and_statements = "\n".join([
        f"Statement {stmt.id}: {stmt.text}" for stmt in input['previous_statements']
    ])

    result = skill.complete(
        prompt_inputs={
            "MAIN_QUESTION": input['main_question'],
            "QUERY": input['current_query'],
            "SEARCH_RESULTS": json.dumps([sr.dict() for sr in input['search_results']]),
            "PREVIOUS_QUERIES_AND_STATEMENTS": previous_queries_and_statements
        }
    )

    content = json.loads(result.content)
    
    for statement in content.get('statements', []):
        statement_hash = int(hashlib.md5(statement['text'].encode()).hexdigest(), 16)
        statement['id'] = f"S{statement_hash % 10**STATEMENT_ID_DIGITS:0{STATEMENT_ID_DIGITS}d}"

    return StatementGeneration(**content)

def critical_assessment_step(input: List[Statement]) -> List[float]:
    # Placeholder implementation
    return [statement.support_score for statement in input]

def filter_statements_step(
    input: Dict[str, Any]
) -> List[Statement]:
    # Placeholder implementation: passthrough all statements
    return input['statements']

def analysis_step(
    input: Dict[str, Any],
    skill: Completion
) -> ResearchAnalysisAndSynthesis:
    logger.info("Generating research analysis and synthesis")

    research_history = "\n".join([f"Statement {stmt.id}: {stmt.text}" for stmt in input['all_statements']])

    result = skill.complete(
        prompt_inputs={
            "MAIN_QUESTION": input['main_question'],
            "RESEARCH_HISTORY": research_history
        }
    )

    return ResearchAnalysisAndSynthesis.parse_raw(result.content)

def next_query_step(
    input: Dict[str, Any],
    skill: Completion
) -> NextQueryGeneration:
    logger.info(f"Generating next queries")

    previous_queries_and_statements = "\n".join([f"Statement {stmt.id}: {stmt.text}" for stmt in input['all_statements']])
    previous_analysis_json = input['previous_analysis'].json() if input['previous_analysis'] else ""

    result = skill.complete(
        prompt_inputs={
            "MAIN_QUESTION": input['main_question'],
            "PREVIOUS_QUERIES_AND_STATEMENTS": previous_queries_and_statements,
            "PREVIOUS_ANALYSIS": previous_analysis_json,
            "NUM_QUERIES": str(input['num_queries'])
        }
    )

    return NextQueryGeneration.parse_raw(result.content)

# Pipeline runner
def run_pipeline(config: PipelineConfig):
    state = PipelineState(main_question=config.main_question)
    web_search = BraveSearchClient()
    statement_skill = Completion(('QLoop', 'Statements'))
    query_skill = Completion(('QLoop', 'Query'))
    answer_skill = Completion(('QLoop', 'Answer'))

    current_query = config.main_question

    for iteration in range(config.iterations):
        # Retrieval step
        search_results = retrieval_step(
            input=current_query,
            web_search=web_search
        )

        # Generate statements step
        statement_generation = generate_statements_step(
            input={
                'main_question': config.main_question,
                'current_query': current_query,
                'search_results': search_results,
                'previous_statements': list(state.all_statements.values())
            },
            skill=statement_skill
        )

        # Critical assessment step
        scores = critical_assessment_step(
            input=statement_generation.statements
        )

        # Filter statements step
        filtered_statements = filter_statements_step(
            input={
                'statements': statement_generation.statements,
                'scores': scores,
                'threshold': config.statement_threshold
            }
        )

        # Update all_statements
        for statement in filtered_statements:
            state.all_statements[statement.id] = statement

        # Analysis step
        analysis_result = analysis_step(
            input={
                'main_question': config.main_question,
                'all_statements': list(state.all_statements.values())
            },
            skill=answer_skill
        )

        # Next query step
        next_query_generation = next_query_step(
            input={
                'main_question': config.main_question,
                'all_statements': list(state.all_statements.values()),
                'previous_analysis': analysis_result,
                'num_queries': config.queries_per_iteration
            },
            skill=query_skill
        )

        # Update current_query for next iteration
        if next_query_generation.next_queries:
            current_query = next_query_generation.next_queries[0]
        else:
            logger.warning("No next query generated. Stopping the pipeline.")
            break

        # Store iteration results
        iteration_results = {
            'retrieval_step': search_results,
            'generate_statements_step': statement_generation,
            'critical_assessment_step': scores,
            'filter_statements_step': filtered_statements,
            'analysis_step': analysis_result,
            'next_query_step': next_query_generation
        }
        state.iterations.append(iteration_results)

        generate_report(state, config)

    logger.info("Pipeline completed.")

def generate_report(state: PipelineState, config: PipelineConfig):
    safe_question = "".join(c for c in state.main_question[:30] if c.isalnum() or c.isspace()).rstrip().replace(" ", "_")
    output_filename = f"{safe_question}_report.md"
    output_path = os.path.join(config.output_folder, output_filename)
    
    def json_serializer(obj):
        if isinstance(obj, BaseModel):
            return obj.dict()
        return str(obj)

    with open(output_path, 'w') as f:
        f.write(f"# Research Report: {state.main_question}\n\n")
        f.write(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        for iteration, steps in enumerate(state.iterations, 1):
            f.write(f"## Iteration {iteration}\n\n")
            for step_name, step_result in steps.items():
                f.write(f"### {step_name}\n\n")
                f.write("#### Result\n")
                if step_name == 'filter_statements_step':
                    f.write("Placeholder step - no filtering applied\n\n")
                elif isinstance(step_result, (list, dict, BaseModel)):
                    f.write("```json\n" + json.dumps(step_result, indent=2, default=json_serializer) + "\n```\n\n")
                else:
                    f.write(f"{step_result}\n\n")
        
        f.write("## All Statements\n\n")
        for statement_id, statement in state.all_statements.items():
            f.write(f"- <a id='{statement_id}'></a>[{statement_id}]: {statement.text}\n")
    
    logger.info(f"Report generated: {output_path}")

def main():
    config = PipelineConfig(
        main_question="How do LLMs affect freedom of speech in Russia",
        iterations=3,
        queries_per_iteration=1,
    )
    
    run_pipeline(config)

if __name__ == "__main__":
    main()
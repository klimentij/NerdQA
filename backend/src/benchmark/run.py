# python -m backend.src.benchmark.run
import asyncio
import os
import json
import time
import wandb
from typing import Dict, Any, List
from pathlib import Path

from backend.src.benchmark.steps.seed_papers import fetch_and_process_papers
from backend.src.benchmark.steps.build_qa import generate_qa_pairs
from backend.src.benchmark.steps.eval_ade import evaluate_answer, create_metadata
from backend.src.benchmark.steps.run_pipeline import run_pipeline_request
from backend.src.llm.completion import Completion
from backend.src.benchmark.config import load_config, BenchmarkConfig
from backend.src.util.setup_logging import setup_logging
from backend.src.benchmark.steps.baselines.no_rag import generate_no_rag_answer

logger = setup_logging(__name__)

def log_completion_skill_config(skill: Completion):
    """Save Completion skill configuration as a wandb artifact."""
    skill_name = '_'.join(skill.skill)  # Use underscore instead of slash
    
    # Create a dictionary with the skill configuration
    skill_config = {
        "skill_config": skill.skill_config,
        "prompt": skill.prompt,
        "response_format": skill.response_format if hasattr(skill, 'response_format') else None
    }
    
    # Create a wandb artifact with a valid name
    artifact = wandb.Artifact(f"{skill_name}_config", type="skill_config")
    
    # Save the configuration as a JSON file within the artifact
    with artifact.new_file(f"{skill_name}_config.json", mode="w") as f:
        json.dump(skill_config, f, indent=2)
    
    # Log the artifact
    wandb.log_artifact(artifact)

async def process_paper(paper: Dict[str, Any], config: BenchmarkConfig, metadata: Dict[str, str]) -> Dict[str, Any]:
    if config.system == "ade":
        answer, citation_tree = await run_pipeline_request(paper, config.pipeline)
        paper['eval_answer'] = answer
        paper['eval_references'] = citation_tree
    elif config.system == "baseline_no_rag":
        answer = await generate_no_rag_answer(paper["question_generated"], metadata)
        paper['eval_answer'] = answer
        paper['eval_references'] = []  # No references for baseline
    else:
        raise ValueError(f"Unknown system: {config.system}")

    evaluation, average_score = await evaluate_answer(paper, config, metadata)
    paper['evaluation'] = evaluation.dict()
    paper['average_score'] = average_score
    return paper

async def run_benchmark(config: BenchmarkConfig):
    """Run the entire benchmark process."""
    # Initialize W&B
    wandb.init(project=config.project_name, config=config)

    # Log Completion skill configurations
    report_skill = Completion(('BenchPaperCompress', 'Report'))
    question_skill = Completion(('BenchPaperCompress', 'Question'))
    eval_skill = Completion(('BenchPaperCompress', 'Eval'))

    log_completion_skill_config(report_skill)
    log_completion_skill_config(question_skill)
    log_completion_skill_config(eval_skill)

    # Fetch seed papers
    seed_papers = await fetch_and_process_papers(config.seed_papers)
    logger.info(f"Fetched {len(seed_papers)} seed papers")

    # # Generate QA pairs
    # papers_with_qa = generate_qa_pairs(seed_papers, config.qa_generation)
    # logger.info(f"Generated QA pairs for {len(papers_with_qa)} papers")

    # # Create metadata
    # pipeline_start_ts = int(time.time())
    # trace_name = f"BM EvalADE for {len(papers_with_qa)} papers"
    # trace_id = f"T{pipeline_start_ts}"
    # session_id = f"S{pipeline_start_ts}"
    # metadata = create_metadata(trace_name, trace_id, session_id)

    # # Process each paper
    # tasks = [process_paper(paper, config, metadata) for paper in papers_with_qa]
    # evaluation_results = await asyncio.gather(*tasks)

    # # Log evaluation results
    # for result in evaluation_results:
    #     log_data = {
    #         "paper_average_score": result['average_score']
    #     }
        
    #     # Add individual scores to the log_data dictionary
    #     for score_name, score_detail in result['evaluation']['scores'].items():
    #         log_data[score_name] = score_detail['score']
        
    #     # Log all scores in a single call
    #     wandb.log(log_data)

    # # Calculate and log overall average score
    # overall_average = sum(r['average_score'] for r in evaluation_results) / len(evaluation_results)
    # wandb.log({"overall_average_score": overall_average})
    # logger.info(f"Overall average score: {overall_average}")

    # # Save results as wandb artifact
    # results_artifact = wandb.Artifact("evaluation_results", type="benchmark_results")
    # with results_artifact.new_file("evaluation_results.json", mode="w") as f:
    #     json.dump(evaluation_results, f, indent=2)
    # wandb.log_artifact(results_artifact)

    # # Save results to static filename
    # runs_dir = os.path.join(os.path.dirname(__file__), "runs")
    # os.makedirs(runs_dir, exist_ok=True)
    # static_output_file = os.path.join(runs_dir, "last_run.json")
    # with open(static_output_file, 'w') as f:
    #     json.dump(evaluation_results, f, indent=2)

    # logger.info(f"Results saved to {static_output_file}")
    # wandb.finish()

if __name__ == "__main__":
    config = load_config()
    asyncio.run(run_benchmark(config))
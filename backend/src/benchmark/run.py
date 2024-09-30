# python -m backend.src.benchmark.run
import asyncio
import os
import json
import time
import wandb
from typing import Dict, Any, List
from pathlib import Path

from backend.src.benchmark.steps.seed_papers import fetch_and_process_papers
from backend.src.benchmark.steps.build_questions import generate_questions
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
    
    skill_config = {
        "skill_config": skill.skill_config,
        "prompt": skill.prompt,
        "response_format": skill.response_format if hasattr(skill, 'response_format') else None
    }
    
    artifact = wandb.Artifact(f"{skill_name}_config", type="skill_config")
    
    with artifact.new_file(f"{skill_name}_config.json", mode="w") as f:
        json.dump(skill_config, f, indent=2)
    
    wandb.log_artifact(artifact)

async def run_pipeline_for_paper(paper: Dict[str, Any], config: BenchmarkConfig, metadata: Dict[str, str]) -> Dict[str, Any]:
    if config.system == "ade":
        answer, citation_tree = await run_pipeline_request(paper, config.pipeline)
        paper['pipeline_answer'] = answer
        paper['pipeline_references'] = citation_tree
    elif config.system == "baseline_no_rag":
        answer = await generate_no_rag_answer(paper["question_generated"], metadata)
        paper['pipeline_answer'] = answer
        paper['pipeline_references'] = []  # No references for baseline
    else:
        raise ValueError(f"Unknown system: {config.system}")
    return paper

async def run_benchmark(config: BenchmarkConfig):
    """Run the entire benchmark process."""
    wandb.init(project=config.project_name, config=config)

    question_skill = Completion(('Benchmark', 'Question'))
    log_completion_skill_config(question_skill)

    seed_papers = await fetch_and_process_papers(config.seed_papers)
    logger.info(f"Fetched {len(seed_papers)} seed papers")

    papers_with_questions = generate_questions(seed_papers, config.question_generation)
    logger.info(f"Generated questions for {len(papers_with_questions)} papers")

    pipeline_start_ts = int(time.time())
    trace_name = f"BM Pipeline for {len(papers_with_questions)} papers"
    trace_id = f"T{pipeline_start_ts}"
    session_id = f"S{pipeline_start_ts}"
    metadata = create_metadata(trace_name, trace_id, session_id)

    # Run pipeline in parallel for each paper
    tasks = [run_pipeline_for_paper(paper, config, metadata) for paper in papers_with_questions]
    papers_with_answers = await asyncio.gather(*tasks)

    # Save results to last_run.json
    runs_dir = os.path.join(os.path.dirname(__file__), "runs")
    os.makedirs(runs_dir, exist_ok=True)
    static_output_file = os.path.join(runs_dir, "last_run.json")
    with open(static_output_file, 'w') as f:
        json.dump(papers_with_answers, f, indent=2)

    logger.info(f"Results saved to {static_output_file}")
    wandb.finish()

if __name__ == "__main__":
    config = load_config()
    asyncio.run(run_benchmark(config))
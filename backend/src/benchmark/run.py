# python -m backend.src.benchmark.run
import asyncio
import os
import json
import time
import wandb
from typing import Dict, Any, List
from pydantic import BaseModel
from nltk.tokenize import word_tokenize
from nltk.translate.bleu_score import sentence_bleu
from rouge import Rouge
import numpy as np
import re

from backend.src.benchmark.steps.seed_papers import fetch_and_process_papers
from backend.src.benchmark.steps.build_questions import generate_questions
from backend.src.benchmark.steps.eval_ade import evaluate_answer, create_metadata
from backend.src.benchmark.steps.run_pipeline import run_pipeline_request, run_pipeline_for_paper
from backend.src.llm.completion import Completion
from backend.src.benchmark.config import load_config, BenchmarkConfig
from backend.src.util.setup_logging import setup_logging
from backend.src.benchmark.steps.eval_ade import evaluate_papers

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

def flatten_config(config: BenchmarkConfig) -> dict:
    """Flatten the config object into a dictionary with dot notation keys."""
    flat_config = {}
    
    def flatten(obj, prefix=''):
        if isinstance(obj, BaseModel):
            for field, value in obj:
                flatten(value, f"{prefix}{field}.")
        elif isinstance(obj, (list, tuple)):
            for i, value in enumerate(obj):
                flatten(value, f"{prefix}{i}.")
        else:
            flat_config[prefix[:-1]] = obj

    flatten(config)
    return flat_config

async def run_benchmark(config: BenchmarkConfig):
    """Run the entire benchmark process."""
    # Flatten the config
    flat_config = flatten_config(config)
    
    # Initialize wandb with flattened config
    wandb.init(project=config.project_name, config=flat_config)

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

    # Evaluate results
    papers_with_answers, avg_metrics = evaluate_papers(papers_with_answers, config.evaluation.retrieval_k)

    # Log average metrics to wandb summary
    for k, v in avg_metrics.items():
        wandb.run.summary[f"avg_{k}"] = v

    # Prepare the final output dictionary
    final_output = {
        "average_metrics": avg_metrics,
        "papers": papers_with_answers
    }

    # Save results to last_run.json
    runs_dir = os.path.join(os.path.dirname(__file__), "runs")
    os.makedirs(runs_dir, exist_ok=True)
    static_output_file = os.path.join(runs_dir, "last_run.json")
    with open(static_output_file, 'w') as f:
        json.dump(final_output, f, indent=2)

    logger.info(f"Results saved to {static_output_file}")

    # Save last_run.json as a wandb artifact
    artifact = wandb.Artifact("last_run", type="benchmark_results")
    artifact.add_file(static_output_file)
    wandb.log_artifact(artifact)

    wandb.finish()


if __name__ == "__main__":
    config = load_config()
    asyncio.run(run_benchmark(config))
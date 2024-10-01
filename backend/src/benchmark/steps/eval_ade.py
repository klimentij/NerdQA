import asyncio
import json
from pydantic import BaseModel, Field
from typing import Dict, Any, Tuple, List

from backend.src.util.setup_logging import setup_logging
from backend.src.llm.completion import Completion
from backend.src.benchmark.config import BenchmarkConfig, EvaluationConfig
import time
import numpy as np
from nltk.tokenize import word_tokenize
from rouge_score import rouge_scorer
import re
import wandb
import multiprocessing
from functools import partial
from sklearn.metrics import precision_score, recall_score, f1_score

logger = setup_logging(__file__, log_level="DEBUG")

class ScoreDetail(BaseModel):
    reasoning: str
    score: int = Field(..., ge=1, le=10)

class EvaluationScores(BaseModel):
    accuracy: ScoreDetail
    completeness: ScoreDetail
    relevance: ScoreDetail
    evidence_quality: ScoreDetail
    clarity: ScoreDetail
    logical_structure: ScoreDetail
    evidence_support: ScoreDetail
    depth_of_analysis: ScoreDetail
    objectivity: ScoreDetail
    synthesis: ScoreDetail

class EvaluationResponse(BaseModel):
    scores: EvaluationScores

async def evaluate_answer(paper: Dict[str, Any], config: BenchmarkConfig, metadata: Dict[str, str]) -> Tuple[EvaluationResponse, float]:
    logger.info("Evaluating answer using the Eval skill")
    skill = Completion(('BenchPaperCompress', 'Eval'))
    
    input_data = {
        "question_generated": paper["question_generated"],
        "golden_answer_generated": paper["golden_answer_generated"],
        "eval_answer": paper["eval_answer"],
        "eval_references": paper["eval_references"]
    }
    
    result = await asyncio.to_thread(skill.complete,
        prompt_inputs={"INPUT": json.dumps(input_data)},
        completion_kwargs={
            "metadata": metadata,
            "model": config.evaluation.eval_llm
        }
    )   
    
    try:
        content_dict = json.loads(result.content)
        evaluation_response = EvaluationResponse(**content_dict)
        
        scores = evaluation_response.scores
        total_score = sum(getattr(scores, field).score for field in scores.__fields__)
        average_score = total_score / len(scores.__fields__)
        
        return evaluation_response, average_score
    except json.JSONDecodeError:
        logger.error(f"Failed to parse result content: {result.content}")
        raise ValueError("Invalid response format from Eval skill")

def create_metadata(trace_name: str, trace_id: str, session_id: str) -> Dict[str, str]:
    return {
        "trace_name": trace_name,
        "trace_id": trace_id,
        "trace_user_id": "Benchmark",
        "session_id": session_id
    }

def calculate_retrieval_metrics(referenced_works, pipeline_source_papers, k):
    """Calculate precision@k, recall@k, and f1@k for retrieval using sklearn."""
    all_papers = set(referenced_works) | set(pipeline_source_papers[:k])
    y_true = [1 if paper in referenced_works else 0 for paper in all_papers]
    y_pred = [1 if paper in pipeline_source_papers[:k] else 0 for paper in all_papers]

    precision = precision_score(y_true, y_pred, zero_division=0)
    recall = recall_score(y_true, y_pred, zero_division=0)
    f1 = f1_score(y_true, y_pred, zero_division=0)

    return precision, recall, f1

def preprocess_text(text):
    """Preprocess text for tokenization."""
    text = text.lower()
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'([^\w\s])', r' \1 ', text)
    return text.strip()

def calculate_text_similarity_metrics(reference, hypothesis):
    """Calculate ROUGE and F1 scores for text similarity."""
    logger.info(f"Preprocessing reference and hypothesis")
    reference_processed = preprocess_text(reference)
    hypothesis_processed = preprocess_text(hypothesis)
    
    logger.info(f"Tokenizing reference and hypothesis")
    reference_tokens = word_tokenize(reference_processed)
    hypothesis_tokens = word_tokenize(hypothesis_processed)
    
    logger.info(f"Calculating ROUGE score")
    scorer = rouge_scorer.RougeScorer(['rouge1', 'rouge2', 'rougeL'], use_stemmer=True)
    rouge_scores = scorer.score(reference_processed, hypothesis_processed)
    
    logger.info(f"Calculating F1 score")
    reference_set = set(reference_tokens)
    hypothesis_set = set(hypothesis_tokens)
    true_positives = len(reference_set & hypothesis_set)
    precision = true_positives / len(hypothesis_set) if hypothesis_set else 0
    recall = true_positives / len(reference_set) if reference_set else 0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
    
    return rouge_scores, f1

def evaluate_single_paper(paper, retrieval_k):
    """Evaluate a single paper and calculate metrics."""
    logger.info(f"Evaluating paper: {paper.get('title')}")
    precision, recall, f1 = calculate_retrieval_metrics(
        paper.get('referenced_works', []),
        paper.get('pipeline_source_papers', []),
        retrieval_k
    )

    logger.info(f"Calculating text similarity metrics for paper: {paper.get('title')}")
    rouge_scores, text_f1 = calculate_text_similarity_metrics(
        paper.get('text', ''),
        paper.get('pipeline_answer', '')
    )

    evaluation = {
        f'precision@{retrieval_k}': precision, 
        f'recall@{retrieval_k}': recall, 
        f'f1@{retrieval_k}': f1,
        'rouge_1': rouge_scores['rouge1'].fmeasure,
        'rouge_2': rouge_scores['rouge2'].fmeasure, 
        'rouge_l': rouge_scores['rougeL'].fmeasure,
        'text_f1': text_f1,
        'num_source_papers': len(paper.get('pipeline_source_papers', []))
    }

    paper['evaluation'] = evaluation
    return paper, evaluation

def evaluate_papers(papers_with_answers, retrieval_k):
    """Evaluate papers and calculate metrics in parallel."""
    logger.info(f"Starting parallel evaluation of {len(papers_with_answers)} papers")
    
    # Create a partial function with fixed retrieval_k
    evaluate_paper_partial = partial(evaluate_single_paper, retrieval_k=retrieval_k)

    # Use multiprocessing to evaluate papers in parallel
    with multiprocessing.Pool() as pool:
        results = pool.map(evaluate_paper_partial, papers_with_answers)

    # Unpack results
    evaluated_papers, all_evaluations = zip(*results)

    # Calculate average metrics and log to wandb
    all_metrics = {
        f'precision@{retrieval_k}': [], f'recall@{retrieval_k}': [], f'f1@{retrieval_k}': [],
        'rouge_1': [], 'rouge_2': [], 'rouge_l': [], 'text_f1': []
    }

    for evaluation in all_evaluations:
        for key in all_metrics.keys():
            all_metrics[key].append(evaluation[key])
        # Log individual paper metrics to wandb
        wandb.log({f"{k}": v for k, v in evaluation.items()})

    avg_metrics = {k: np.mean(v) for k, v in all_metrics.items()}
    
    # Log average metrics as summary metrics to wandb
    for k, v in avg_metrics.items():
        wandb.run.summary[f"avg_{k}"] = v

    return list(evaluated_papers), avg_metrics

def main():
    # Example usage of calculate_retrieval_metrics
    referenced_works = ['A', 'B', 'C', 'D']
    pipeline_source_papers = ['B', 'C', 'E', 'F', 'A']
    k = 3

    precision, recall, f1 = calculate_retrieval_metrics(referenced_works, pipeline_source_papers, k)

    print(f"Precision@{k}: {precision:.2f}")
    print(f"Recall@{k}: {recall:.2f}")
    print(f"F1@{k}: {f1:.2f}")

if __name__ == "__main__":
    main()
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
from nltk.translate.bleu_score import sentence_bleu
from rouge import Rouge
import re
import wandb

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

def calculate_retrieval_metrics(referenced_works, pipeline_source_papers):
    """Calculate precision and recall for retrieval."""
    true_positives = set(referenced_works) & set(pipeline_source_papers)
    precision = len(true_positives) / len(pipeline_source_papers) if pipeline_source_papers else 0
    recall = len(true_positives) / len(referenced_works) if referenced_works else 0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
    return precision, recall, f1

def preprocess_text(text):
    """Preprocess text for tokenization."""
    text = text.lower()
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'([^\w\s])', r' \1 ', text)
    return text.strip()

def calculate_text_similarity_metrics(reference, hypothesis):
    """Calculate BLEU, ROUGE, and F1 scores for text similarity."""
    reference_processed = preprocess_text(reference)
    hypothesis_processed = preprocess_text(hypothesis)
    
    reference_tokens = word_tokenize(reference_processed)
    hypothesis_tokens = word_tokenize(hypothesis_processed)
    
    bleu = sentence_bleu([reference_tokens], hypothesis_tokens)
    
    rouge = Rouge()
    rouge_scores = rouge.get_scores(hypothesis_processed, reference_processed)[0]
    
    reference_set = set(reference_tokens)
    hypothesis_set = set(hypothesis_tokens)
    true_positives = len(reference_set & hypothesis_set)
    precision = true_positives / len(hypothesis_set) if hypothesis_set else 0
    recall = true_positives / len(reference_set) if reference_set else 0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
    
    return bleu, rouge_scores, f1

def evaluate_papers(papers_with_answers):
    """Evaluate papers and calculate metrics."""
    all_metrics = {
        'retrieval_precision': [], 'retrieval_recall': [], 'retrieval_f1': [],
        'bleu': [], 'rouge_1': [], 'rouge_2': [], 'rouge_l': [], 'text_f1': []
    }

    for paper in papers_with_answers:
        precision, recall, f1 = calculate_retrieval_metrics(
            paper.get('referenced_works', []),
            paper.get('pipeline_source_papers', [])
        )
        all_metrics['retrieval_precision'].append(precision)
        all_metrics['retrieval_recall'].append(recall)
        all_metrics['retrieval_f1'].append(f1)

        bleu, rouge_scores, text_f1 = calculate_text_similarity_metrics(
            paper.get('text', ''),
            paper.get('pipeline_answer', '')
        )
        all_metrics['bleu'].append(bleu)
        all_metrics['rouge_1'].append(rouge_scores['rouge-1']['f'])
        all_metrics['rouge_2'].append(rouge_scores['rouge-2']['f'])
        all_metrics['rouge_l'].append(rouge_scores['rouge-l']['f'])
        all_metrics['text_f1'].append(text_f1)

        paper['evaluation'] = {
            'retrieval_precision': precision, 'retrieval_recall': recall, 'retrieval_f1': f1,
            'bleu': bleu, 'rouge_1': rouge_scores['rouge-1']['f'],
            'rouge_2': rouge_scores['rouge-2']['f'], 'rouge_l': rouge_scores['rouge-l']['f'],
            'text_f1': text_f1,
            'num_source_papers': len(paper.get('pipeline_source_papers', []))  # Add this line
        }

        wandb.log({f"{k}": v for k, v in paper['evaluation'].items()})

    avg_metrics = {k: np.mean(v) for k, v in all_metrics.items()}

    return papers_with_answers, avg_metrics
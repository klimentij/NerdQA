from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import date

class SeedPapersConfig(BaseModel):
    query: str = ""
    title_search: str = "survey"
    sort: str = "cited_by_count:desc"
    start_published_date: date = Field(default_factory=lambda: date(2024, 1, 1))
    end_published_date: date = Field(default_factory=lambda: date(2024, 9, 1))
    caching: bool = True
    use_pdf_cache: bool = True
    initial_top_to_retrieve: int = 100
    num_tokens_min: int = 7000
    num_tokens_max: int = 500000
    cited_by_count_min: int = 20
    max_papers_to_seed: int = 10
    min_reference_count: int = 200

class QuestionGenerationConfig(BaseModel):
    max_papers_to_process: int = 5
    chunk_size: int = 256
    chunk_overlap: int = 0

class PipelineConfig(BaseModel):
    iterations: int = 2
    num_queries: int = 2
    search_client: str = "openalex"

class EvaluationConfig(BaseModel):
    # eval_llm: str = "gpt-4o-2024-08-06"
    eval_llm: str = "gpt-4o-mini"

class BenchmarkConfig(BaseModel):
    project_name: str = "ADE_ResearchArena"
    seed_papers: SeedPapersConfig = Field(default_factory=SeedPapersConfig)
    question_generation: QuestionGenerationConfig = Field(default_factory=QuestionGenerationConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    evaluation: EvaluationConfig = Field(default_factory=EvaluationConfig)
    output_dir: str = "benchmark/runs"
    # system: str = "baseline_no_rag"
    # system: str = "ade"
    system: str = "baseline_naive_rag"

# Create a default configuration
default_config = BenchmarkConfig()

# Function to load configuration (you can expand this to load from a file if needed)
def load_config() -> BenchmarkConfig:
    return default_config

# If you want to allow overriding config values:
def override_config(config: BenchmarkConfig, **kwargs) -> BenchmarkConfig:
    return config.copy(update=kwargs)
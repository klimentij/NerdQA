from pydantic import BaseModel, Field
from typing import Optional
from datetime import date

class SeedPapersConfig(BaseModel):
    query: str = "Large language models"
    sort: str = "cited_by_count:desc"
    start_published_date: date = Field(default_factory=lambda: date(2024, 1, 1))
    end_published_date: date = Field(default_factory=lambda: date(2024, 9, 1))
    caching: bool = True
    use_pdf_cache: bool = True
    initial_top_to_retrieve: int = 200
    num_tokens_min: int = 7000
    num_tokens_max: int = 20000
    cited_by_count_min: int = 50
    max_papers_to_seed: int = 50

class QAGenerationConfig(BaseModel):
    max_papers_to_process: int = 5
    chunk_size: int = 256
    chunk_overlap: int = 0

class EvaluationConfig(BaseModel):
    eval_llm: str = "gpt-4o-mini"
    iterations: int = 1
    num_queries: int = 1
    search_client: str = "openalex"

class BenchmarkConfig(BaseModel):
    project_name: str = "ADE"
    seed_papers: SeedPapersConfig = Field(default_factory=SeedPapersConfig)
    qa_generation: QAGenerationConfig = Field(default_factory=QAGenerationConfig)
    evaluation: EvaluationConfig = Field(default_factory=EvaluationConfig)
    output_dir: str = "benchmark/runs"

# Create a default configuration
default_config = BenchmarkConfig()

# Function to load configuration (you can expand this to load from a file if needed)
def load_config() -> BenchmarkConfig:
    return default_config

# If you want to allow overriding config values:
def override_config(config: BenchmarkConfig, **kwargs) -> BenchmarkConfig:
    return config.copy(update=kwargs)
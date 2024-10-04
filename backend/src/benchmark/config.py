from pydantic import BaseModel, Field
from typing import Any, List, Optional, Union, Generic, TypeVar
from datetime import date

T = TypeVar('T')

class Probe(BaseModel, Generic[T]):
    """A wrapper class for parameters that should be tested in the grid search."""
    values: List[T]

    def __iter__(self):
        return iter(self.values)

    def __getitem__(self, index):
        return self.values[index]

    def __len__(self):
        return len(self.values)

class SeedPapersConfig(BaseModel):
    query: str = ""
    title_search: str = "survey"
    sort: str = "cited_by_count:desc"
    start_published_date: date = Field(default_factory=lambda: date(2024, 1, 1))
    end_published_date: date = Field(default_factory=lambda: date(2024, 10, 1))
    caching: bool = True
    use_pdf_cache: bool = True
    initial_top_to_retrieve: int = 200
    num_tokens_min: int = 7000
    num_tokens_max: int = 500000
    cited_by_count_min: int = 10
    max_papers_to_seed: int = 5
    min_reference_count: int = 200

class QuestionGenerationConfig(BaseModel):
    max_papers_to_process: int = 5
    
class PipelineConfig(BaseModel):
    iterations: int = 10
    num_queries: int = 3
    search_client: str = "openalex"
    download_full_text: bool = False
    search_caching: bool = True
    query_llm: str = "gpt-4o-2024-08-06"
    initial_top_to_retrieve: int = 100

class EvaluationConfig(BaseModel):
    retrieval_k: int = 10

class BenchmarkConfig(BaseModel):
    project_name: str = "ADE_ResearchArena4"
    seed_papers: SeedPapersConfig = Field(default_factory=SeedPapersConfig)
    question_generation: QuestionGenerationConfig = Field(default_factory=QuestionGenerationConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    evaluation: EvaluationConfig = Field(default_factory=EvaluationConfig)
    output_dir: str = "benchmark/runs"
    system: Union[str, Probe[str]] = Probe(
        values=[
            # "baseline_no_rag", 
            # "baseline_title", 
            # "baseline_naive_rag",
            # "ade"
            "qnote"
        ]
    )
# Create a default configuration
default_config = BenchmarkConfig()

# Function to load configuration (you can expand this to load from a file if needed)
def load_config() -> BenchmarkConfig:
    return default_config

# If you want to allow overriding config values:
def override_config(config: BenchmarkConfig, **kwargs) -> BenchmarkConfig:
    return config.copy(update=kwargs)
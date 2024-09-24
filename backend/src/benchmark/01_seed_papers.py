import asyncio
import json
import os
import sys
from dataclasses import dataclass
import pandas as pd

os.chdir(__file__.split('src/')[0])
sys.path.append(os.getcwd())

from src.tools.openalex_search_client import OpenAlexSearchClient
from src.util.setup_logging import setup_logging

@dataclass
class Config:
    """Configuration parameters for fetching and processing seed papers."""
    # Search parameters
    query: str = "Large language models"
    sort: str = "cited_by_count:desc"
    start_published_date: str = "2024-01-01"
    end_published_date: str = "2024-09-01"

    # OpenAlexSearchClient parameters
    caching: bool = False
    use_pdf_cache: bool = False
    initial_top_to_retrieve: int = 200

    # Output parameters
    num_tokens_min: int = 7000
    num_tokens_max: int = 20000
    cited_by_count_min: int = 50
    max_papers_to_seed: int = 50
    output_filename: str = "seed_papers.json"
    data_directory: str = "data"

async def fetch_and_process_papers(config: Config):
    logger = setup_logging(__file__, log_level="INFO")
    
    openalex_search = OpenAlexSearchClient(
        rerank=False,
        use_chunking=False,
        caching=config.caching,
        use_pdf_cache=config.use_pdf_cache,
        initial_top_to_retrieve=config.initial_top_to_retrieve,
    )

    logger.info(f"Fetching papers for query: {config.query}")
    openalex_results = await openalex_search.search(
        query=config.query,
        sort=config.sort,
        start_published_date=config.start_published_date,
        end_published_date=config.end_published_date,

    )

    df = pd.DataFrame(openalex_results['results'])
    df = pd.concat([df, df.meta.apply(pd.Series)], axis=1)
    logger.info(f"Got {len(df)} papers from OpenAlex. df: ")
    logger.info(df)

    filtered_df = df[
        (df.text_type == 'full_text') &
        (df.num_tokens > config.num_tokens_min) &
        (df.num_tokens < config.num_tokens_max) &
        (df.cited_by_count > config.cited_by_count_min)
    ].head(config.max_papers_to_seed)
    
    logger.info(f"Filtered to {len(filtered_df)} papers")
    export_data = filtered_df.iloc[:, :3].to_dict(orient='records')

    full_data_dir = os.path.join(os.path.dirname(__file__), config.data_directory)
    os.makedirs(full_data_dir, exist_ok=True)
    output_file = os.path.join(full_data_dir, config.output_filename)

    with open(output_file, 'w') as f:
        json.dump(export_data, f, indent=2)

    logger.info(f"Exported {len(export_data)} papers to {output_file}")

if __name__ == "__main__":
    config = Config()
    asyncio.run(fetch_and_process_papers(config))
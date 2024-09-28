import asyncio
import pandas as pd
import json
import os
from backend.src.tools.openalex_search_client import OpenAlexSearchClient
from backend.src.util.setup_logging import setup_logging
from backend.src.db.local_cache import LocalCache

logger = setup_logging(__name__)
cache = LocalCache()

@cache
async def fetch_and_process_papers(config):
    openalex_search = OpenAlexSearchClient(
        rerank=False,
        use_chunking=False,
        caching=config.caching,
        use_pdf_cache=config.use_pdf_cache,
        initial_top_to_retrieve=config.initial_top_to_retrieve,
    )

    openalex_results = await openalex_search.search(
        query=config.query,
        sort=config.sort,
        start_published_date=config.start_published_date,
        end_published_date=config.end_published_date,
        min_reference_count=config.min_reference_count,
        title_search=config.title_search
    )

    df = pd.DataFrame(openalex_results['results'])
    df = pd.concat([df, df.meta.apply(pd.Series)], axis=1)

    filtered_df = df[
        (df.text_type == 'full_text') &
        (df.num_tokens > config.num_tokens_min) &
        (df.num_tokens < config.num_tokens_max) &
        (df.cited_by_count > config.cited_by_count_min)
    ].head(config.max_papers_to_seed)

    cols_to_drop = ['meta']
    filtered_df = filtered_df.drop(columns=cols_to_drop)
    
    logger.info(f"Fetched and processed {len(filtered_df)} papers")
    
    # Convert the DataFrame to a list of dictionaries
    papers = filtered_df.to_dict(orient='records')
    
    # Create 'data' directory in the parent directory of the script if it doesn't exist
    script_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(script_dir)
    data_dir = os.path.join(parent_dir, 'data')
    os.makedirs(data_dir, exist_ok=True)
    
    # Save the papers to a JSON file in the data directory
    json_file_path = os.path.join(data_dir, 'seed_papers.json')
    with open(json_file_path, 'w') as f:
        json.dump(papers, f, indent=2)
    
    logger.info(f"Saved {len(papers)} papers to {json_file_path}")
    
    return papers
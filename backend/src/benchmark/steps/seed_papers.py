import asyncio
import pandas as pd
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
    )

    df = pd.DataFrame(openalex_results['results'])
    df = pd.concat([df, df.meta.apply(pd.Series)], axis=1)

    filtered_df = df[
        (df.text_type == 'full_text') &
        (df.num_tokens > config.num_tokens_min) &
        (df.num_tokens < config.num_tokens_max) &
        (df.cited_by_count > config.cited_by_count_min)
    ].head(config.max_papers_to_seed)
    
    logger.info(f"Fetched and processed {len(filtered_df)} papers")
    return filtered_df.to_dict(orient='records')
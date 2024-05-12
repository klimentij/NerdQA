#%%
import pandas as pd
import numpy as np
import os
import time
import yaml
import copy
from flatten_json import flatten
from func_timeout import func_set_timeout, FunctionTimedOut

import requests
import json
import logging
from tenacity import retry, stop_after_attempt, wait_exponential, after_log


# progress_apply for pandas 
from tqdm import tqdm
tqdm.pandas()

import sys
os.chdir(__file__.split('src/')[0])

sys.path.append(os.getcwd())

from src.utils.env_util import cfg
from src.utils.util import prompts
from src.utils.kb_utils import embeddings, chunks_collection
from src.utils.mysql_util import get_mysql_table_value_samples
from src.utils.setup_logging import setup_logging
logger = setup_logging(__file__)

import cohere
co = cohere.Client(os.environ.get('COHERE_API_KEY'))

from langchain.vectorstores import MongoDBAtlasVectorSearch
from langchain.embeddings.openai import OpenAIEmbeddings
from pymongo import MongoClient




# # cache
# cache_dir='data/cache'
# os.makedirs(cache_dir, exist_ok=True)
# from joblib import Memory

# # Create a memory object with a specific cache directory
# memory = Memory(cache_dir, verbose=0)

from src.llm.tokenizer import VdTokenizer
tokenizer = VdTokenizer(cfg['llm']['best']['name'])

logger.info(f"Starting {__file__}. Running on {os.getcwd()}")

#%%

def mongo_retrieve(question, topk=1000, filters: list = []):
    try:

        or_separated_filters = []
        def add_or_separated_filter(_or_separated_filters, category, tag):
            _or_separated_filters.append(
                {
                    "$and": [
                        {"category": {"$eq": category}},
                        {"tag": {"$eq": tag}}
                    ]
                }
            )
            return _or_separated_filters
        
        for f in filters:
            tag = f.get('tag', None)
            category = f.get('category', None)
            if tag and category:
                or_separated_filters = add_or_separated_filter(or_separated_filters, category, tag)

                # Special tags
                # Support general MA guides/APIs
                if tag == 'MAO' or tag == 'MAWM':
                    or_separated_filters = add_or_separated_filter(or_separated_filters, category, 'MA')

                # TODO: remove this dirty trick once we have proper Egnyte sync API
                # dirty trick to make sure removed manual McLane docs are returned
                if category == 'Sync':
                    or_separated_filters = add_or_separated_filter(or_separated_filters, 'Uploads', tag)

        pre_filter = {"$or": or_separated_filters}


        if len(filters) == 0:
            pre_filter = None

        # run pipeline
        logger.info(f"Calling vector_search aggregate pipeline on docs. \nQuestion: {question}\npre_filter: {json.dumps(pre_filter, indent=2)}")
        st = time.time()
        res = chunks_collection.vector_search(embeddings.embed_query(question), pre_filter, topk)
        logger.info(f"Aggragate returned something in {time.time()-st:.2f}s")
        
        st = time.time()
        res = pd.DataFrame(res)
        logger.info(f"Loaded {len(res)} results to df in {time.time()-st:.2f}s")

        # Flatten the 'content' and 'metadata' columns
        content_df = res['content'].apply(pd.Series)
        metadata_df = res['metadata'].apply(pd.Series)

        # Drop the original 'content' and 'metadata' columns from 'res'
        res.drop(columns=['content', 'metadata'], inplace=True)

        # Concatenate the flattened columns with the original DataFrame
        res = pd.concat([res, content_df, metadata_df], axis=1)

        # dedup
        res = res.drop_duplicates(subset=['embedded_content'])

        res['query'] = question
        res['search'] = 'mongo'
        res['retriever_rank'] = pd.Series(list(range(1, len(res)+1))).astype(int).tolist()
        logger.info(f"mongo_retrieve returned {len(res)} results after dedup by embedded_content")

        if len(res) == 0:
            logger.warning(f"mongo_retrieve returned 0 results for: {question}. pre_filter: {json.dumps(pre_filter, indent=2)}")
        return res
    
    except:
        logger.exception(f"Failed to mongo retrieve to: {question}. Returning empty df")
        return pd.DataFrame()
    
def distil_dict(d):
    out = {}
    out['path'] = list(d['paths'].keys())[0]
    out['method'] = list(d['paths'][out['path']].keys())[0]
    out['description'] = d['paths'][out['path']][out['method']].get('description', '')[:500]
    
    # clean up the description
    seps = ["Included in components: ", "**Error Codes:**"]
    for sep in seps:
        if sep in out['description']:
            out['description'] = out['description'].split(sep)[0]
    out['description'] = out['description']\
        .replace('\n', ' ')\
        .replace('\r', ' ')\
        .replace('  ', ' ')\
        .strip()\
        .strip('.')\
        .strip()

    params = ''
    for p in d['paths'][out['path']][out['method']].get('parameters', []):
        params += p['name']
        if p.get('required', False):
            params += '*'
        params += ';'
    out['params(*=required)'] = params.strip(';')

    resp200 = d['paths'][out['path']][out['method']].get('responses', {}).get('200', {}).get('content', {})
    resp200 = resp200.get('application/json', resp200).get('schema', resp200)
    out['resp200'] = str(resp200)[:500].strip('{').strip('}').replace("'", "")

    return out


def prep_rerank_data(row):
    # for guides KB, where we don't have dicts
    # rerank on path, summary, text
    if 'yaml_full' not in row or pd.isna(row['yaml_full']):
        return row['embedded_content']
    
    # for API KB, where we have dicts
    # rerank on stringified dict
    else:
        return row['embedded_content']
    

# def cohere_rerank(query, docs, top_to_rerank=20, max_chunks_per_doc=1):
#     return co.rerank(
#             query=query, 
#             documents=docs, 
#             model='rerank-english-v2.0',
#             top_n=top_to_rerank,
#             max_chunks_per_doc=max_chunks_per_doc,
#             )


@retry(
    stop=stop_after_attempt(32),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    after=after_log(logger, logging.DEBUG)
)
def cohere_rerank(query, docs, max_chunks_per_doc=1):
    url = "https://api.cohere.ai/v1/rerank"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {os.environ.get('COHERE_API_KEY')}"
    }
    payload = {
        "return_documents": True,
        "max_chunks_per_doc": max_chunks_per_doc,
        "model": "rerank-english-v2.0",
        "query": query,
        "documents": docs
    }
    
    # Perform the API request with a timeout
    logger.info(f"Calling cohere_rerank http request with query: {query}")
    response = requests.post(url, headers=headers, json=payload, timeout=20)
    logger.info(f"cohere_rerank http request returned with status_code: {response.status_code}")
    
    # Check for successful request
    if response.status_code == 200:
        data = response.json()
        results = data.get("results", [])
        
        # Prepare the output
        output = [{"document": r["document"]["text"], "relevance_score": r["relevance_score"]} for r in results]
        return output
    else:
        logger.error(f"Failed request: code {response.status_code}, text {response.text}. Returning output with equal scores.")
        output = [{"document": doc, "relevance_score": 1} for doc in docs]


def rerank(query, docs_df, top_to_rerank=20, rerank_col='embedded_content', max_chunks_per_doc=1):
    try:        
        docs = docs_df[rerank_col].astype(str).head(top_to_rerank).tolist()
        
        st = time.time()
        res = cohere_rerank(query, docs, max_chunks_per_doc=max_chunks_per_doc)
        logger.info(f"Reranked {len(docs)} docs. Only `cohere_rerank` took {time.time()-st:.2f}s. top_to_rerank={top_to_rerank}, max_chunks_per_doc={max_chunks_per_doc}")

        res = pd.DataFrame({
            rerank_col: [r['document'] for r in res],
            'reranker_score': [r['relevance_score'] for r in res],
            'reranker_rank': pd.Series(list(range(1, len(list(res))+1))).astype(int),

        })
        
        # merge with original df.head(top_to_rerank)
        docs_df[f'{rerank_col}_str'] = docs_df[rerank_col].astype(str)
        res = res.merge(docs_df.head(top_to_rerank), left_on=rerank_col, right_on=f'{rerank_col}_str', how='left')
        res = res.sort_values('reranker_score', ascending=False)
        res['reranker_rank'] = list(range(1, len(res)+1))

        # concat with the left over rows
        res = pd.concat([res, docs_df.iloc[top_to_rerank:]], axis=0)
        res['reranker_rank'] = res['reranker_rank'].fillna(len(docs_df)+1)
        res['reranker_score'] = res['reranker_score'].fillna(0)
        res = res.sort_values(['reranker_rank', 'retriever_rank'], ascending=True)

        # time.sleep(0.1) # to avoid cohere rate limit
        return res
        
    except:
        logger.exception(f"Failed to rerank for: {query}. Returning df with fake retrieval ranks.")
        
        # we need to return a df with the same columns as docs_df, add some fake reranker scores
        docs_df[f'{rerank_col}_str'] = docs_df[rerank_col].astype(str)
        docs_df['reranker_score'] = 0
        docs_df['reranker_rank'] = list(range(1, len(docs_df)+1))
        return docs_df
        

def downweight_release_notes(res, release_notes_weight=0.5, score_col='reranker_score'):
    if score_col not in res.columns:
        res[score_col] = np.linspace(1, 0, len(res))

    if 'path' not in res.columns:
        res['path'] = ''
    res['path'] = res['path'].fillna('')

    try:
        res[score_col] = res.apply(lambda x: x[score_col] * release_notes_weight \
                if '| Release ' in x['path'] \
                or '| SCI Updates' in x['path'] \
                or '| Capability Matrix' in x['path'] \
                    else x[score_col], axis=1)
    except:
        logger.exception(f"Failed to downweight release notes for {len(res)} results.")
        
    res = res.sort_values([score_col, 'retriever_score'], ascending=False)
    res = res.reset_index(drop=True)
    return res

def retry_wrapper(func, kwargs, max_retries=10):
    for i in range(max_retries):
        try:
            # Call the function and return its result if it's successful
            return func(**kwargs)
        except FunctionTimedOut:
            # If it times out, try again
            logger.debug(f'Attempt {i+1}: Function timed out.')
    # If it fails max_retries times, raise an error
    raise FunctionTimedOut(f'Function failed after {max_retries} attempts.')


@func_set_timeout(100)
def retrieve(query, return_topk=cfg['search']['topk_to_retrieve'], topk_to_rerank=cfg['search']['topk_to_rerank'], do_rerank=True, conn=None, filters: list = []) -> pd.DataFrame:
    st = time.time()
    logger.info(f"Retrieving from MongoDB with query: {query}. topk_to_rerank={topk_to_rerank}, do_rerank={do_rerank}")
    res = mongo_retrieve(query, topk=cfg['search']['topk_to_rerank'], filters=filters)
    logger.info(f"MongoDB retrieval toook {time.time()-st:.2f}s. Found {len(res)} results.")
    if do_rerank:
        res['rerank_text'] = res.apply(prep_rerank_data, axis=1)
        res = rerank(query, res, 
                    top_to_rerank=topk_to_rerank,
                    rerank_col='rerank_text', 
                    max_chunks_per_doc=cfg['search']['max_chunks_per_doc'])
        res = downweight_release_notes(res, release_notes_weight=cfg['search']['release_notes_weight'], score_col='reranker_score')


    res['sid'] = list(range(1, len(res)+1))

    # add yaml_full with nans for compatibility
    if 'yaml_full' not in res.columns:
        res['yaml_full'] = np.nan

    res = res.head(return_topk)

    if do_rerank:
        res_good_reranker_score = res[res['reranker_score'] >= cfg['search']['reranker_score_threshold']]
        logger.info(f"Dropping {len(res) - len(res_good_reranker_score)} results with reranker_score below threshold of {cfg['search']['reranker_score_threshold']}. Returning {len(res_good_reranker_score)} results.")
        return res_good_reranker_score
    
    return res



def rearrange_info_under_paths(api_dict):
    """Move 'info' section under each path."""
    rearranged_dict = copy.deepcopy(api_dict)
    info = rearranged_dict.pop('info', None)
    for path in rearranged_dict.get('paths', {}):
        rearranged_dict['paths'][path]['info'] = info
    return rearranged_dict

def merge_dicts(dict1, dict2):
    """Merge dict2 into dict1"""

    key = 'info'
    if key in dict1 and key in dict2 and (dict1[key] != dict2[key]):
        dict1 = rearrange_info_under_paths(dict1)
        dict2 = rearrange_info_under_paths(dict2)

    for key in dict2:
        if key in dict1:
            if isinstance(dict1[key], dict) and isinstance(dict2[key], dict):
                merge_dicts(dict1[key], dict2[key])                
            elif dict1[key] == dict2[key]:
                pass # Same leaf value
            else:
                # merge conflict, keep both keys
                dict1[key + '_conflict'] = copy.deepcopy(dict2[key])
                logger.warning(f"Merge conflict for key: {key}; \n\ndict1: {dict1}\n\n dict2: {dict2}")
        else:
            dict1[key] = copy.deepcopy(dict2[key])
    return dict1


def find_duplicate_params(apiSpec):
    params_dict = {}
    duplicates = {}
    cnt = 0
    
    if 'paths' not in apiSpec:
        return duplicates
    
    for path, path_item in apiSpec['paths'].items():
        for method, method_item in path_item.items():
            if 'parameters' in method_item:
                for param in method_item['parameters']:
                    param_str = json.dumps(param, sort_keys=True)
                    if param_str in params_dict:
                        duplicates[param_str] = params_dict[param_str]
                    else:
                        params_dict[param_str] = f"#/components/path_params/{param['name']}_{cnt}"
                        cnt += 1

    return duplicates


def delete_enum_from_statusCode(data):
    if isinstance(data, dict):
        if 'statusCode' in data:
            if 'enum' in data['statusCode']:
                del data['statusCode']['enum']
        for key in data:
            delete_enum_from_statusCode(data[key])

def create_ref_for_duplicates(apiSpec):
    duplicates = find_duplicate_params(apiSpec)
    if not duplicates:
        return apiSpec

    # Add duplicate parameters to the components
    if not 'components' in apiSpec:
        apiSpec['components'] = {}

    if not 'path_params' in apiSpec['components']:
        apiSpec['components']['path_params'] = {}

    for dup_param, ref in duplicates.items():
        param_name = ref.split('/')[-1]
        apiSpec['components']['path_params'][param_name] = json.loads(dup_param)

    # Replace duplicates in the paths with the ref
    for path, path_item in apiSpec['paths'].items():
        for method, method_item in path_item.items():
            if 'parameters' in method_item:
                for i, param in enumerate(method_item['parameters']):
                    param_str = json.dumps(param, sort_keys=True)
                    if param_str in duplicates:
                        method_item['parameters'][i] = {'$ref': duplicates[param_str]}
            
    # Make sure path_params go before other keys in components
    if 'components' in apiSpec:
        if 'path_params' in apiSpec['components']:
            apiSpec['components'] = {'path_params': apiSpec['components']['path_params'], **apiSpec['components']}
        
    return apiSpec


def compress_merged_spec(spec, sid_key="___sid___"):

    # preliminary cleaning
    if 'paths' in spec:
        for path, path_item in spec['paths'].items():
            for method, method_item in path_item.items():
                # clean description
                if 'description' in method_item:
                    method_item['description'] = method_item['description'].split('. Included in components:')[0]

                # drop operationid and summary
                if 'operationId' in method_item:
                    del method_item['operationId']
                
                if 'summary' in method_item:
                    del method_item['summary']

                # name in tags is useless
                if 'tags' in method_item:
                    for tag in method_item['tags']:
                        if 'name' in tag:
                            del tag['name']


    # Delete enum of all codes
    delete_enum_from_statusCode(spec)

    # start with component info
    # normally info is a dict in path object
    # we need to pop and collect all infos, dudup and add before 
    # everything else
    infos = []
    if 'paths' in spec:
        for path, path_item in spec['paths'].items():
            if 'info' in path_item:
                infos.append(path_item.pop('info'))

    # dedup infos
    infos = pd.DataFrame(infos)

    # make title the first columns
    if 'title' in infos.columns:
        infos = infos[['title'] + [col for col in infos.columns if col != 'title']]
    
    infos = infos.drop_duplicates().to_dict('records')

    compressed_component_info = ''
    if len(infos) > 0:
        compressed_component_info += 'Component Info\n'
        for info in infos:
            compressed_component_info += yaml.dump(info, sort_keys=False) + '\n\n'
    
    # sometimes, when all paths have the same info, it is moved to the top level
    if len(infos) == 0:
        if 'info' in spec:
            # make title the first key
            info = spec['info']
            if 'title' in info:
                info = {'title': info['title'], **{key: info[key] for key in info if key != 'title'}}
            compressed_component_info += 'Component Info\n'
            compressed_component_info += yaml.dump(info, sort_keys=False) + '\n\n'

    compressed_paths = ''

    if 'paths' in spec:
        for path, path_item in spec['paths'].items():
            for method, method_item in path_item.items():

                if sid_key in method_item:
                    sid = method_item.pop(sid_key)
                    compressed_paths += f"\n\n{sid_key}: {sid}\n"

                compressed_paths += f"{method.upper()} {path}\n"

                # add non-param keys as yaml
                nonparam_method_item = {k: v for k, v in method_item.items() if k not in  ['parameters', 'responses']}
                compressed_paths += yaml.dump(nonparam_method_item, sort_keys=False) + '\n'

                if 'parameters' in method_item:
                    params = method_item['parameters']

                    # flatten schema
                    for p in params:
                        if 'schema' in p:
                            p.update(p.pop('schema'))

                    param_str = pd.DataFrame(params).to_csv(index=False)
                    compressed_paths += 'parameters:\n' + param_str + '\n'

                # compress responses
                if 'responses' in method_item:
                    rows = []
                    for code, resp in method_item['responses'].items():
                        if isinstance(resp, dict):
                            for code_key in resp.keys():
                                # make value a string
                                resp[code_key] = str(resp[code_key])
                            
                        
                        rows.append({
                            'code': code,
                            **resp})
                    
                    resp_str = pd.DataFrame(rows).to_csv(index=False)
                    compressed_paths += 'responses:\n' + resp_str + '\n'

    # compress path params
    compressed_path_params = ''
    if 'components' in spec:
        if 'path_params' in spec['components']:
            rows = []
            for id, param in spec['components']['path_params'].items():
                # flatten schema
                if 'schema' in param:
                    param.update(param.pop('schema'))

                rows.append({
                    'ref_id': id,
                    **param
                })
            compressed_path_params += 'components/path_params:\n'
            compressed_path_params += pd.DataFrame(rows).to_csv(index=False) + '\n'

    # compress schemas
    compressed_schemas = ''
    if 'components' in spec:
        if 'schemas' in spec['components']:
            compressed_schemas += 'components/schemas:\n\n'
            for id, schema in spec['components']['schemas'].items():
                # first render non-properties values as 1st level yaml
                no_prop_schema = {k: v for k, v in schema.items() if k != 'properties'}
                compressed_schemas += f"{id}\n"
                compressed_schemas += yaml.dump(no_prop_schema, sort_keys=False)

                # then render properties as csv
                if 'properties' in schema:
                    rows = []
                    for id, prop in schema['properties'].items():
                        rows.append({
                            'title': id,
                            **prop
                        })
                    compressed_schemas += 'properties:\n'
                    compressed_schemas += pd.DataFrame(rows).to_csv(index=False) + '\n'

    # requestBodies compression
    compressed_requestBodies = ''
    if 'components' in spec:
        if 'requestBodies' in spec['components']:
            requestBodies = spec['components']['requestBodies']
            compressed_requestBodies += 'components/requestBodies:\n'
            rows = []
            for id, requestBody in requestBodies.items():
                requestBody = flatten(requestBody, )
                rows.append({
                    'id': id,
                    **requestBody
                })


            compressed_requestBodies += pd.DataFrame(rows).to_csv(index=False) + '\n'

    # assemble final compressed spec
    out = ''
    out += compressed_component_info
    out += '\n---Paths---\n'
    out += compressed_paths
    out += '\n---Paths end---\n'
    out += compressed_path_params
    out += compressed_requestBodies
    out += compressed_schemas

    return out

def embed_sids(x, sid_key='___sid___') -> dict:
    if pd.isna(x['dict']):
        return x['dict']
    else:
        method = x['method']
        path = x['path']
        if 'paths' in x['dict']:
            if path in x['dict']['paths']:
                # path_obj = x['dict']['paths'][path].pop()
                # path_dict = {path: path_obj}
                # x['dict']['paths'] = {x['sid']: path_dict}
                
                if method in x['dict']['paths'][path]:
                    x['dict']['paths'][path][method] = {sid_key: x['sid'], **x['dict']['paths'][path][method]}
                    
        return x['dict']

def trim_paths_in_final_string(spec_str: str, sep: str = "___sid___") -> str:
    # post-process trimming
    # make sure none of the paths are too long
    # it's hard to trim as dicts to keep them valid
    # so we trim the final string

    # get part of string with paths 
    before_path = spec_str.split('\n---Paths---\n')[0]
    paths_str = spec_str.split('\n---Paths---\n')[1].split('\n---Paths end---\n')[0]
    after_path = spec_str.split('\n---Paths end---\n')[1]

    # to properly parse it we anchor to specially wraped sids
    sptils = paths_str.split(sep)

    # trim each split
    trimmed_splits = []
    for split in sptils:
        split_tokens = tokenizer.encode(split)
        if len(split_tokens) > cfg['openapi']['max_tokens_per_path']:
            split = tokenizer.decode(split_tokens[:cfg['openapi']['max_tokens_per_path']]) + '..[trimmed]\n\n'

        trimmed_splits.append(split)

    # join back splits
    paths_str = sep.join(trimmed_splits)

    # replace special sid keys with normal ones
    paths_str = paths_str.replace(sep, 'sid')

    # # trim after path
    # ap_tokens = tokenizer.encode(after_path)
    # if len(ap_tokens) > cfg['openapi']['max_tokens_per_components']:
    #     after_path = tokenizer.decode(ap_tokens[:cfg['openapi']['max_tokens_per_components']]) + '..[trimmed]'

    # join back the whole thing
    spec_str = before_path + paths_str + after_path

    return spec_str

def get_compressed_spec(df: pd.DataFrame) -> str:
    
    if len(df) == 0 or df['dict'].isna().all():
        # logger.warning(f"get_compressed_spec: len(df) == 0 or df['dict'].isna().all(). Returning empty string.")
        return ''
    
    # embed sids in spec of each endpoint
    df['dict'] = df.apply(lambda x: embed_sids(x), axis=1)

    spec = {}
    for i, row in df[:].iterrows():
        spec = merge_dicts(spec, row['dict'])

    spec = create_ref_for_duplicates(spec)
    spec_str = compress_merged_spec(spec)
    spec_str = trim_paths_in_final_string(spec_str)

    # logger.info(f"get_compressed_spec: returning string with len(spec_str) = {len(spec_str)}")
    return spec_str

def df_to_context_string(df: pd.DataFrame, max_tokens: int = 6000, return_with_doc_ids: bool = False, merge_api_specs: bool = False, chunk_id_name: str = 'doc_id'):
    
    # keep only up to max_tokens total
    if 'num_tokens' in df.columns:
        try:
            df['num_tokens'] = df['num_tokens'].fillna(0)
            df['total_tokens'] = df['num_tokens'].cumsum()
            df = df[df['total_tokens'] <= max_tokens]
        except Exception as e:
            logger.warning(f"Failed to keep only up to max_tokens total. Keeping all results. Error: {str(e)}")
    
    # assemble chunks for RAG
    chunks = []
    for _, r in df.iterrows():
        # remove summary from embedded_content
        # if embedded_content is dict
        if r.get('embedded_content'):
            if type(r['embedded_content']) == dict:
                if 'summary' in r['embedded_content']:
                    del r['embedded_content']['summary']
            else:
                if r.get('summary'):
                    r['embedded_content'] = str(r['embedded_content']).replace(r['summary'].strip("""'"\`"""), '')

        else:
            logger.warning(f"Skipping chunk {chunk_id_name}={r[chunk_id_name]} because no embedded_content found")
            continue

        chunk = {
            chunk_id_name: r.get('entry_id', 'unknown'),
            'category': r.get('category', 'unknown'),
            'tag': r.get('tag', 'unknown'),
            'content': r.get('embedded_content'),
        }
        ### inject special metadata
        # example_rows for MySQL
        if r.get('category', 'unknown') == 'MySQL':
            # table_name = r.get('table_name', '')
            # db_name = r.get('database_name', '')
            # if table_name and db_name:
            #     chunk['value_samples'] = get_mysql_table_value_samples(f"{db_name}.{table_name}")

            #     # skip whole chunk if no samples
            #     if not chunk.get('value_samples', None):
            #         logger.debug(f"Skipping chunk {chunk_id_name}={chunk[chunk_id_name]} because no value_samples found")
            #         continue

            #     if int(chunk['value_samples'].get('number_of_rows', 0)) == 0:
            #         logger.debug(f"Skipping chunk {chunk_id_name}={chunk[chunk_id_name]} because number_of_rows=0")
            #         continue

            # drop embedded_content and use special keys instead
            chunk.pop('content', None)
            chunk['create_table'] = r.get('create_table', '')
            chunk['top_5_rows'] = r.get('example_rows', '')
            chunk['total_rows'] = r.get('row_count', 0)

        chunks.append(chunk)

    if type(chunks) == list and len(chunks) > 0 and type(chunks[0]) == dict:
        try:

            return {'context_string': chunks}
        except:
            pass

    return {'context_string': ['Error: Failed to assemble chunks']}


def query_to_trimmed_context_string(query: str = None, df: pd.DataFrame = None, max_tokens: int = 6000, top_to_log: int = 30, top_to_retrieve: int = cfg['search']['topk_to_retrieve'], conn=None, filters: list = [], return_with_doc_ids=False, do_rerank=True, merge_api_specs: bool = False, chunk_id_name: str = 'doc_id') -> str:
    st = time.time()
    
    if query:
        # get top k results first
        df = retry_wrapper(retrieve, {'query': query, 'conn': conn, 'filters': filters, 'do_rerank':do_rerank})
        logger.info(f"Retrieved+reranked {len(df)} results for query {query} in {time.time()-st:.2f}s")

        # get topk_to_rag
        df = df.head(cfg['search']['topk_to_rag'])
        
    else:
        logger.info("No query provided, using provided df")

    if df is not None and len(df) > 0:

        # get context
        res = df_to_context_string(df, max_tokens=max_tokens, return_with_doc_ids=return_with_doc_ids, merge_api_specs=merge_api_specs, chunk_id_name=chunk_id_name)
        last_context_string = res['context_string']
        logger.info(f"Got context string based on top {len(df)} results")

        return {
            'docstr': last_context_string,
            'filters': filters,
            'time': time.time() - st
        }
    
    else:
        logger.warning(f"Query {query} returned no results or no df is given")
        return {}

#%%
########################################################







#%%

# #%%
# #%%
# %%time
# question = 'how to see order'
# # question = "/dcorder/api/dcorder/noteVisibility/search"
# question = "receiving/api/receiving/asn/save?"
# question = "What are the required fields for the POST /api/receiving/asn/save API?"
# question = "Short question: What are the required fields for the POST /receiving/api/receiving/asn/save API?\nFull question: What are the required fields for the `POST /receiving/api/receiving/asn/save` API in the Manhattan Active Warehouse Management system?"
# question = "how UI or API"

# topk = 100
# docs = vectorstore.similarity_search_with_score(question, k=topk, 
#                                                 pre_filter=\
# {
#   "compound": {
#       "must": [
#         {
#           "text": {
#             "query": guides.path.unique().tolist()[:3],
#             "path": "path"
#           }
#         },
#         {
#           "text": {
#             "query": [ "API"],
#             "path": "category"
#           }
#         }
#       ]
#     }
# }
# )
# res = pd.DataFrame([d[0].metadata for d in docs])
# res['text'] = [d[0].page_content for d in docs]
# res['retriever_score'] = [d[1] for d in docs]
# res.tag.value_counts()

# res[res['path'] == '/receiving/api/receiving/asn/save']
# #%%
# res = retrieve(question, )
# res[res['path'] == '/receiving/api/receiving/asn/save']
# %%time
# docs = vectorstore.similarity_search_with_score('how log time', k=200)

# # %%
# %%time
# res = pd.DataFrame([d[0].metadata for d in docs])
# res['text'] = [d[0].page_content for d in docs]
# res['retriever_score'] = [d[1] for d in docs]

# #%%
# %%time
# res['dict'] = res['yaml_full'].apply(lambda x: yaml.load(x, Loader=yaml.CBaseLoader))

# # %%
# res
# # %%

# res = retrieve('how log time')
# res
# %%

# %%
# %%time
# json.loads(res.text.iloc[0])
# # %%
# %%timeit
# yaml.load(res.yaml_full.iloc[95], Loader=yaml.CBaseLoader)
# # %%
# res.keys()
# # %%
# print(res['docstr'])
# %%
# %%time
# q = "Short question: I need to send a POST request to the /dcinventory/api/dcinventory/ilpn/createIlpnAndInventory API. Can you help with generating that request? I also need to know what fields are required in the body of the payload.\nFull question: What are the required fields for the payload when sending a POST request to the /dcinventory/api/dcinventory/ilpn/createIlpnAndInventory API in the Manhattan Active Supply Chain Solution, and how can I generate the request?"

# res = query_to_trimmed_context_string(q, max_tokens=20000)
# print(res['res'])
# #%%
# df = res['res']
# df = df[df['sid'].isin([4])]
# df
# #%%
# res = query_to_trimmed_context_string(df=df, max_tokens=6000)
# print(res['docstr'])

#  %%
# spec_str  = """
# """
# spec_str = spec_str.replace('sid', '___sid___')

# spec_str = trim_paths_in_final_string(spec_str)
# print(spec_str)
# # %%
# def get_compressed_spec_dict(df: pd.DataFrame):
    
#     if len(df) == 0 or df['dict'].isna().all():
#         return ''
    
#     # embed sids in spec of each endpoint
#     df['dict'] = df.apply(lambda x: embed_sids(x), axis=1)

#     spec = {}
#     for i, row in df[:].iterrows():
#         spec = merge_dicts(spec, row['dict'])

#     return spec


# cspec = get_compressed_spec_dict(res['res'][res['res']['category']=='API'][:2])
# # %%
# cspec['paths']['/inventory-management/api/inventory-management/create/item/validate']['info']
# # %%
# cspec['components']['schemas']
# # %%
# compressed_schemas = ''
# if 'components' in cspec:
#     if 'schemas' in cspec['components']:
#         compressed_schemas += 'components/schemas:\n\n'

# compressed_schemas
# # %%
# cm = compress_merged_spec(cspec)
# #%%
# print(cm)
# # %%
# t = trim_paths_in_final_string(cm)
# print(t)
# # %%

# # %%
# 

# from langchain.chat_models import ChatOpenAI
# from langchain.schema import (
#     AIMessage,
#     HumanMessage,
#     SystemMessage
# )

# chat = ChatOpenAI(model='gpt-4', temperature=0, max_tokens=500)
# chat.predict_messages([HumanMessage(content="Translate this sentence from English to French. I love programming.")])
# # %%
#%%
# question = "Hey"
# pre_filter = {
#   "compound": {
#     "must": [
#       {
#         "text": {
#           "query": [
#             "f7158355fce4ba9f49d1e3ae3516b6d6"
#           ],
#           "path": "tag"
#         }
#       },
#       {
#         "text": {
#           "query": [
#             "Sync",
#             "Uploads"
#           ],
#           "path": "category"
#         }
#       }
#     ]
#   }
# }
# r = vectorstore.similarity_search_with_score(question, k=10, pre_filter=pre_filter)
# r
# # %%
# %%timeit
# query = "Hey"  # Assuming this is your query string for vector search
# pre_filter = {
#   "$and": [
#     {"tag": "f7158355fce4ba9f49d1e3ae3516b6d6"},  # Adjust with your actual tag value
#     {"category": {"$in": ["Sync", "Uploads"]}}  # Adjust with your actual category values
#   ]
# }
# vectorstore2 = MongoDBAtlasVectorSearch(collection, embeddings, index_name="new_docs_vector_index")
# r = vectorstore2.similarity_search_with_score(
#     query=query, k=500, pre_filter=pre_filter,
    
# )
# %%
# %%time
# query = "get item"  # Assuming this is your query string for vector search
# pre_filter = {
#   "$or": [
#     {
#       "$and": [
#         {"category": {"$eq": "Guides"}},
#         {"tag": {"$eq": "MAWM"}}
#       ]
#     }
#   ]
# }
# post_filter_pipeline = [
#     {"$project": {"embedding": 0}}  # Exclude the embedding field
# ]
# vectorstore2 = MongoDBAtlasVectorSearch(collection, embeddings, index_name="new_docs_vector_index")
# r = vectorstore2.similarity_search_with_score(
#     query=query, k=50, pre_filter=pre_filter, post_filter_pipeline=post_filter_pipeline
    
# )

# pd.DataFrame([d[0].metadata for d in r])
# # %%

#%%
# l = []
# for i in range(100):
#     s = str(np.random.choice(400000))
#     s = f"【{s}†】"
#     print(s)
#     l.append(len(tokenizer.encode(s)))
# pd.Series(l).describe()
# # %%
# from pymongo import MongoClient

# # Connect to your MongoDB database
# db = mongo_client.veridian
# docs_collection = db.docs
# counter_collection = db.counters

# # Find the current highest value in the counter collection for "docsCounter"
# counter = counter_collection.find_one({"_id": "docsCounter"})
# current_max_id = counter["seq_value"] if counter else 0

# # Iterate through each document in the "docs" collection
# for doc in tqdm(docs_collection.find(), total=319509):
#     current_max_id += 1
#     docs_collection.update_one(
#         {"_id": doc["_id"]},
#         {"$set": {"auto_increment_id": current_max_id}}
#     )

# # Update the counter collection with the new highest value
# counter_collection.update_one(
#     {"_id": "docsCounter"},
#     {"$set": {"seq_value": current_max_id}},
#     upsert=True
# )

# %%
# len(tokenizer.encode('source_id'))
# %%

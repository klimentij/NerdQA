#%%
import os
import pandas as pd
import requests
from tqdm import tqdm
import re
import time

# URL of the dataset
url = "https://huggingface.co/datasets/WINGNUS/ACL-OCL/resolve/main/acl-publication-info.74k.v3.full-sections-partial-topic-labels.pkl"

# Local path to save the file
local_path = os.path.expanduser("~/Downloads/acl-publication-info.74k.v3.pkl")

# Download the file if it doesn't exist
if not os.path.exists(local_path):
    print("Downloading dataset...")
    response = requests.get(url, stream=True)
    total_size = int(response.headers.get('content-length', 0))
    
    with open(local_path, 'wb') as file, tqdm(
        desc=local_path,
        total=total_size,
        unit='iB',
        unit_scale=True,
        unit_divisor=1024,
    ) as progress_bar:
        for data in response.iter_content(chunk_size=1024):
            size = file.write(data)
            progress_bar.update(size)
    print("Download complete!")

# Read the DataFrame
df = pd.read_pickle(local_path)

# Show the maximum year
max_year = df['year'].max()
print(f"The most recent year in the dataset is: {max_year}")

# Filter for papers published in 2022
df_2022 = df[df['year'] == "2022"]

# Sort by number of citations (descending) and select top 3
top_3_papers = df_2022.sort_values('numcitedby', ascending=False).head(3)

# Select the second top paper
d = top_3_papers.iloc[1].to_dict()
d
#%%
# Remove { and } from title
title = re.sub(r'[{}]', '', d['title'])

# Function to perform API request with retries
def api_request_with_retries(url, retries=50, backoff_factor=0.3):
    for i in range(retries):
        try:
            response = requests.get(url)
            if response.status_code == 200:
                return response.json()
            else:
                print(f"Request failed with status {response.status_code}. Retrying...")
        except requests.RequestException as e:
            print(f"Request failed with exception {e}. Retrying...")
        time.sleep(backoff_factor * (2 ** i))
    return None

# Search for the paper in Semantic Scholar
search_url = f"https://api.semanticscholar.org/graph/v1/paper/search?query={title}"
search_result = api_request_with_retries(search_url)

if search_result and 'data' in search_result and len(search_result['data']) > 0:
    paper_id = search_result['data'][0]['paperId']
    # Get paper details using the paper ID
    paper_details_url = f"https://api.semanticscholar.org/v1/paper/{paper_id}"
    paper_details = api_request_with_retries(paper_details_url)
    print(paper_details)
else:
    print("Paper not found in Semantic Scholar")

# %%
paper_details

# Function to extract required details from paper details
def extract_references_details(paper_details):
    if not paper_details or 'references' not in paper_details:
        return None

    references = paper_details['references']
    filtered_references = []

    for ref in references:
        first_author = ref['authors'][0]['name'] if ref['authors'] else 'Unknown'
        ref_details = {
            'first_author': first_author,
            'title': ref.get('title', 'No title'),
            'year': ref.get('year', 'No year'),
            'url': ref.get('url', 'No URL')
        }
        filtered_references.append(ref_details)

    return {
        'year': paper_details.get('year', 'No year'),
        'url': paper_details.get('url', 'No URL'),
        'references': filtered_references
    }

# Extract and print filtered details
filtered_details = extract_references_details(paper_details)
print(filtered_details)

# %%
df.columns
# %%]
df.iloc[0].to_dict()
# %%
d
# %%
d['title']
# %%
print(d['full_text'][-1000:])
# %%
d
# %%

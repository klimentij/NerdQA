import requests
from io import BytesIO
from pdfminer.high_level import extract_text
from pdfminer.layout import LAParams

def download_and_save_arxiv_paper(arxiv_url, output_file):
    # Download the PDF
    response = requests.get(arxiv_url)
    if response.status_code != 200:
        raise Exception(f"Failed to download PDF from {arxiv_url}")

    # Parse the PDF and convert to text
    pdf_content = BytesIO(response.content)
    text_content = extract_text(pdf_content, laparams=LAParams())

    # Save as text
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(text_content)

    print(f"Paper saved as text in {output_file}")

# Example usage
arxiv_url = "https://arxiv.org/pdf/2409.10211"
output_file = "arxiv_paper_2409.10211.txt"
download_and_save_arxiv_paper(arxiv_url, output_file)
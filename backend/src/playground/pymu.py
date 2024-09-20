import requests
import fitz
import os

def download_and_save_arxiv_paper(arxiv_url, output_file):
    # Download the PDF
    response = requests.get(arxiv_url)
    if response.status_code != 200:
        raise Exception(f"Failed to download PDF from {arxiv_url}")

    # Save the PDF temporarily
    temp_pdf = "temp_paper.pdf"
    with open(temp_pdf, "wb") as f:
        f.write(response.content)

    # Parse the PDF and convert to markdown
    doc = fitz.open(temp_pdf)
    markdown_content = ""
    for page in doc:
        markdown_content += parse_multicolumn(page)

    # Save as markdown
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(markdown_content)

    # Clean up temporary PDF file
    os.remove(temp_pdf)

    print(f"Paper saved as markdown in {output_file}")

def parse_multicolumn(page):
    bboxes = column_boxes(page, footer_margin=50, no_image_text=True)
    markdown_content = ""
    for rect in bboxes:
        markdown_content += page.get_text(clip=rect, sort=True) + "\n\n"
    return markdown_content

def column_boxes(page, footer_margin=50, no_image_text=True):
    def make_rect(b):
        return fitz.Rect(b[:4])

    blocks = page.get_text("dict", flags=11)["blocks"]
    blocks.sort(key=lambda b: (b["bbox"][3], -b["bbox"][0]))  # sort by y1 descending, then x0 ascending
    
    columns = []
    for block in blocks:
        if block["type"] == 0:  # text block
            bbox = make_rect(block["bbox"])
            if bbox.y1 >= page.rect.height - footer_margin:
                continue
            if no_image_text and block.get("image"):
                continue
            for column in columns:
                if column.intersects(bbox):
                    column |= bbox
                    break
            else:
                columns.append(bbox)
    
    columns.sort(key=lambda r: (r.x0, r.y0))
    return [rect.round() for rect in columns]

# Example usage
arxiv_url = "https://arxiv.org/pdf/2409.10211"
output_file = "arxiv_paper_2409.10211.md"
download_and_save_arxiv_paper(arxiv_url, output_file)
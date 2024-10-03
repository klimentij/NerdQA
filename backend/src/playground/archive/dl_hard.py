import os
from newspaper import Article

def download_and_extract_article(url, output_dir='downloaded_articles'):
    """
    Downloads a webpage from the given URL and extracts the article's text content using Newspaper3k.

    Args:
        url (str): The URL of the article to download.
        output_dir (str): The directory where the extracted article will be saved.

    Returns:
        str: The path to the saved article text file.
    """
    try:
        # Initialize the Article object
        article = Article(url)

        # Download and parse the article
        article.download()
        article.parse()

        # Extract the title and sanitize it for use as a filename
        title = article.title.strip().replace('/', '_').replace('\\', '_')
        if not title:
            title = "untitled_article"

        # Extract the main text of the article
        article_text = article.text
        if not article_text:
            print("Could not extract the article content.")
            return ""

        # Ensure the output directory exists
        os.makedirs(output_dir, exist_ok=True)

        # Define the output file path
        output_file = os.path.join(output_dir, f"{title}.txt")

        # Save the extracted content to a text file
        with open(output_file, "w", encoding="utf-8") as file:
            file.write(article_text)

        print(f"Article content has been successfully extracted and saved to '{output_file}'.")
        return output_file

    except Exception as e:
        print(f"An error occurred while fetching or extracting the article: {e}")
        return ""

if __name__ == "__main__":
    article_url = "https://onlinelibrary.wiley.com/doi/10.1155/2021/6634811"
    download_and_extract_article(article_url)
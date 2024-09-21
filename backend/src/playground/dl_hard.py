import aiohttp
import asyncio
import os

class PDFDownloader:
    def __init__(self, download_url, save_path):
        self.download_url = download_url
        self.save_path = save_path
        self.headers = {
            'User-Agent': (
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/112.0.0.0 Safari/537.36'
            ),
            'Accept': 'application/pdf,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Referer': 'https://effectivehealthcare.ahrq.gov/',  # Adjust if necessary
            'Connection': 'keep-alive',
        }

    async def download_pdf(self):
        """
        Download the PDF file using aiohttp with appropriate headers.
        """
        try:
            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with session.get(self.download_url, allow_redirects=True) as response:
                    if response.status == 403:
                        print("Received 403 Forbidden. Attempting to adjust headers.")
                        # Optionally, adjust headers or handle authentication here
                        return
                    response.raise_for_status()
                    # Ensure the save directory exists
                    os.makedirs(os.path.dirname(self.save_path), exist_ok=True)
                    with open(self.save_path, 'wb') as f:
                        # Download in chunks to handle large files efficiently
                        async for chunk in response.content.iter_chunked(1024):
                            f.write(chunk)
            print(f"PDF downloaded successfully and saved to {self.save_path}")
        except aiohttp.ClientResponseError as cre:
            print(f"Client response error: {cre.status}, {cre.message}")
        except Exception as e:
            print(f"Error downloading PDF: {e}")

    async def run(self):
        """
        Main method to orchestrate the PDF download process.
        """
        await self.download_pdf()

if __name__ == "__main__":
    # URL of the PDF to download
    TARGET_URL = "https://effectivehealthcare.ahrq.gov/sites/default/files/pdf/registries-evaluating-patient-outcomes-4th-edition.pdf"
    
    # Path where the PDF will be saved
    SAVE_PATH = "downloads/registries-evaluating-patient-outcomes-4th-edition.pdf"
    
    downloader = PDFDownloader(download_url=TARGET_URL, save_path=SAVE_PATH)
    asyncio.run(downloader.run())
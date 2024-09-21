import os
import logging
import sys
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s:%(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

class PDFDownloaderSelenium:
    def __init__(self, download_url, save_path):
        self.download_url = download_url
        self.save_path = save_path
        self.download_dir = os.path.abspath(os.path.dirname(self.save_path))
        
        # Ensure the download directory exists
        os.makedirs(self.download_dir, exist_ok=True)
        logging.debug(f"Download directory set to: {self.download_dir}")
        
        # Configure Chrome options for Selenium
        chrome_options = Options()
        chrome_options.add_argument("--headless")  # Run in headless mode
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_experimental_option("prefs", {
            "download.default_directory": self.download_dir,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "plugins.always_open_pdf_externally": True  # Download PDFs instead of opening them
        })
        
        # Initialize the Chrome WebDriver
        try:
            self.driver = webdriver.Chrome(options=chrome_options)
            logging.debug("Initialized headless Chrome WebDriver.")
        except Exception as e:
            logging.exception(f"Failed to initialize Chrome WebDriver: {e}")
            sys.exit(1)
        
    def download_pdf(self):
        """
        Use Selenium to navigate to the PDF URL and download the file.
        """
        try:
            logging.debug(f"Navigating to {self.download_url}")
            self.driver.get(self.download_url)
            
            # Wait for download to complete
            # Adjust the sleep time as necessary based on your network speed and server response
            time.sleep(10)
            
            # Check if any files have been downloaded
            if not os.path.exists(self.download_dir):
                logging.error(f"Download directory does not exist: {self.download_dir}")
                return
            
            downloaded_files = os.listdir(self.download_dir)
            logging.debug(f"Files in download directory: {downloaded_files}")
            
            if not downloaded_files:
                logging.error("No files were downloaded. Check the download process.")
                return
            
            # Assuming the most recently downloaded file is the target PDF
            latest_file_path = max(
                [os.path.join(self.download_dir, f) for f in downloaded_files],
                key=os.path.getctime
            )
            logging.debug(f"Latest downloaded file: {latest_file_path}")
            
            # Rename and move the downloaded file to the desired save_path
            os.rename(latest_file_path, self.save_path)
            logging.info(f"PDF downloaded successfully and saved to {self.save_path}")
        except FileNotFoundError as fnf_error:
            logging.error(f"File not found error: {fnf_error}")
        except Exception as e:
            logging.exception(f"Error downloading PDF with Selenium: {e}")
        finally:
            self.driver.quit()
            logging.debug("Chrome WebDriver session ended.")
    
if __name__ == "__main__":
    # URL of the PDF to download
    TARGET_URL = "https://downloads.hindawi.com/journals/complexity/2021/6634811.pdf"
    
    # Path where the PDF will be saved (including the filename)
    SAVE_PATH = os.path.join("downloads", "6634811.pdf")
    
    downloader = PDFDownloaderSelenium(download_url=TARGET_URL, save_path=SAVE_PATH)
    downloader.download_pdf()
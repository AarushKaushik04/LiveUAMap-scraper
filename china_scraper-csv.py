import os
import logging
import time
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, WebDriverException
from webdriver_manager.firefox import GeckoDriverManager
from selenium.common.exceptions import ElementClickInterceptedException

# from pymongo import MongoClient

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

geckodriver_path = r'C:\Users\aarus\Downloads\geckodriver-v0.36.0-win64\geckodriver.exe'

# # MongoDB configuration
# mongo_client = MongoClient("mongodb://localhost:27017/")  
# db = mongo_client["liveuamap"]

import csv

def save_to_csv(data, filename="scraped_events.csv"):
    if not data:
        logger.info("No data to save.")
        return

    keys = data[0].keys()

    with open(filename, 'w', newline='', encoding='utf-8') as output_file:
        dict_writer = csv.DictWriter(output_file, fieldnames=keys)
        dict_writer.writeheader()
        dict_writer.writerows(data)

    logger.info(f"Saved {len(data)} events to {filename}")

def setup_firefox_service():
    try:
        if os.path.exists(geckodriver_path):
            return FirefoxService(geckodriver_path)
        else:
            raise FileNotFoundError(f"GeckoDriver not found at {geckodriver_path}")
    except WebDriverException as e:
        logger.error("Error setting up Firefox service: %s", e)
        raise

def initialize_driver():
    try:
        firefox_service = setup_firefox_service()
        firefox_options = webdriver.FirefoxOptions()
        # firefox_options.add_argument('--headless')  # Uncomment for headless mode
        firefox_options.add_argument('--disable-notifications')
        driver = webdriver.Firefox(service=firefox_service, options=firefox_options)
        logger.info("Firefox driver initialized successfully.")
        return driver
    except WebDriverException as e:
        logger.error("Driver initialization failed: %s", e)
        raise

def store_data_in_mongo(event_data_list, collection_name):
    try:
        # Create a unique identifier (e.g., using source_url or any other unique field)
        scrape_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Get the collection based on the dynamic collection_name
        collection = db[collection_name]
        
        # Check if the document already exists (based on a field like scrape_time or source_url)
        existing_document = collection.find_one({"scrape_time": scrape_time})
        
        if existing_document:
            # If the document already exists, append the new events to the existing array
            collection.update_one(
                {"scrape_time": scrape_time},
                {"$push": {"events": {"$each": event_data_list}}}
            )
            logger.info(f"Updated existing document with scrape time {scrape_time}.")
        else:
            # If it's a new document, insert it with an array of events
            collection.insert_one({
                "scrape_time": scrape_time,
                "events": event_data_list
            })
            logger.info(f"Inserted new document with scrape time {scrape_time}.")
    except Exception as e:
        logger.error(f"Error storing data in MongoDB: {e}")


# def get_queries_from_file(file_name="countries.txt"):
#     try:
#         with open(file_name, "r") as file:
#             queries = [line.strip() for line in file if line.strip()]
#         logger.info(f"Loaded {len(queries)} queries from {file_name}.")
#         return queries
#     except FileNotFoundError:
#         logger.error(f"File {file_name} not found in the working directory.")
#         return []

def get_china_only():
    return ["china"]

def visit_liveumap(query):
    url = f"https://{query}.liveuamap.com/"
    logger.info(f"Visiting {url}")
    driver = None  # Initialize driver variable

    try:
        # Initialize WebDriver for each query
        driver = initialize_driver()

        driver.get(url)
        WebDriverWait(driver, 10).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        logger.info("Page loaded successfully.")
        
        # Wait for the div with class 'scroller' to be present
        scroller_div = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "scroller"))
        )
        logger.info("Found the div with class 'scroller'.")
        
        event_data_list = []  # List to store the scraped event data
        
        # Find all divs with class 'event cat' and process them one by one
        event_cat_divs = driver.find_elements(By.CSS_SELECTOR, "div[class^='event cat']")
        if event_cat_divs:
            for idx, event_div in enumerate(event_cat_divs, 1):
                logger.info(f"Processing Event {idx} div.")
                try:
                    # Click the div the first time with handling for overlapping elements
                    attempt_click(event_div)
                    time.sleep(2)  # Wait for 2 seconds
                    
                    # Click the div again with handling for overlapping elements
                    attempt_click(event_div)
                    logger.info(f"Clicked Event {idx} div twice.")
                    
                    # Locate and scrape the location from the 'marker-time' div
                    try:
                        marker_time_div = WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.CLASS_NAME, "marker-time"))
                        )
                        location_a = marker_time_div.find_element(By.TAG_NAME, "a")
                        location = location_a.text if location_a else "Location not found"
                        logger.info(f"Location scraped for Event {idx}: {location}")
                    except NoSuchElementException:
                        logger.error(f"No 'marker-time' div found for Event {idx} location.")

                    # Click the specific XPath to continue scraping
                    try:
                        xpath_button = driver.find_element(By.XPATH, "//*[@id='top']/div[2]/div[2]/div[2]/div[4]/a")
                        xpath_button.click()
                        logger.info(f"Clicked the specific XPath button for Event {idx} to continue.")
                    except NoSuchElementException:
                        logger.error(f"No XPath button found to continue for Event {idx}.")
                        # If XPath fails, try clicking the alternative 'Jump to map' link
                        try:
                            jump_to_map_link = driver.find_element(By.CSS_SELECTOR, "div.map_link_par a.map-link")
                            jump_to_map_link.click()
                            logger.info(f"Clicked 'Jump to map' link for Event {idx}.")
                        except NoSuchElementException:
                            logger.error(f"No 'Jump to map' link found for Event {idx}.")

                    # Now, continue scraping for the clicked div (Event {idx})
                    logger.info(f"Continuing scraping process for Event {idx}.")

                    # Extract date
                    try:
                        date = event_div.find_element(By.CSS_SELECTOR, "span.date_add").text
                    except NoSuchElementException:
                        date = "Date not found"
                    
                    # Extract source
                    try:
                        source_url = event_div.find_element(By.CSS_SELECTOR, "a.source-link").get_attribute("href")
                    except NoSuchElementException:
                        source_url = "Source not found"
                    
                    # Extract data (title)
                    try:
                        data = event_div.find_element(By.CSS_SELECTOR, "div.title").text
                    except NoSuchElementException:
                        data = "Data not found"
                    
                    # Extract image source if present
                    try:
                        img_src = event_div.find_element(By.CSS_SELECTOR, "label img").get_attribute("src")
                    except NoSuchElementException:
                        img_src = "Image not found"
                    
                    event_data = {
                        "date": date,
                        "source_url": source_url,
                        "data": data,
                        "img_src": img_src,
                        "location": location  # Add the location to the scraped data
                    }
                    
                    # Append the event data to the list
                    event_data_list.append(event_data)

                    # Add a 2-second delay between processing each event
                    time.sleep(2)

                except Exception as e:
                    logger.error(f"Error during processing Event {idx}: {e}")

        # Store the scraped data in MongoDB (collection named after query)
        # store_data_in_mongo(event_data_list, query.lower())
        save_to_csv(event_data_list, f"{query.lower()}_events.csv")

    except Exception as e:
        logger.error(f"Error while scraping {url}: {e}")
    finally:
        if driver:
            driver.quit()  # Close the driver for each query
            logger.info("Driver closed.")

def attempt_click(element, retries=3, delay=1):
    """Try to click an element with retries if it's obscured by another element."""
    for attempt in range(retries):
        try:
            element.click()
            return
        except ElementClickInterceptedException:
            logger.warning(f"Attempt {attempt + 1} failed. Element is obscured. Retrying...")
            time.sleep(delay)  # Wait before retrying
    logger.error("Failed to click element after several attempts.")


def main():
    try:
        # queries = get_queries_from_file()
        queries = get_china_only()
        for query in queries:
            visit_liveumap(query)  # No need to pass driver anymore, it's handled in visit_liveumap
    except Exception as e:
        logger.error(f"Scraper encountered an error: {e}")

if __name__ == "__main__":
    main()

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
from selenium.common.exceptions import (
    NoSuchElementException,
    WebDriverException,
    ElementClickInterceptedException
)
from pymongo import MongoClient
import csv

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Set GeckoDriver path
geckodriver_path = r'C:\Users\aarus\Downloads\geckodriver-v0.36.0-win64\geckodriver.exe'

# MongoDB Configuration
mongo_client = MongoClient("mongodb://localhost:27017/")
db = mongo_client["liveuamap"]

def save_to_csv(data, filename="scraped_events.csv"):
    if not data:
        print("No data to save.")
        return
    keys = data[0].keys()
    with open(filename, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(data)
    print(f"✅ Saved {len(data)} events to CSV: {filename}")

def setup_firefox_service():
    if os.path.exists(geckodriver_path):
        return FirefoxService(geckodriver_path)
    else:
        raise FileNotFoundError(f"GeckoDriver not found at {geckodriver_path}")

def initialize_driver():
    firefox_service = setup_firefox_service()
    firefox_options = webdriver.FirefoxOptions()
    # firefox_options.add_argument('--headless')  # Uncomment for headless mode
    firefox_options.add_argument('--disable-notifications')
    return webdriver.Firefox(service=firefox_service, options=firefox_options)
def get_available_regions():
    driver = initialize_driver()
    driver.get("https://liveuamap.com")

    WebDriverWait(driver, 10).until(lambda d: d.execute_script("return document.readyState") == "complete")
    time.sleep(2)

    try:
        select_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.ID, "modalRegions"))
        )
        driver.execute_script("arguments[0].scrollIntoView(true);", select_button)
        select_button.click()
        logger.info("Clicked 'Select regions' button.")
        time.sleep(1)

        # Scroll modal to bottom to ensure all regions load
        scroll_modal_to_bottom(driver)

        WebDriverWait(driver, 10).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "a.modalRegName"))
        )
        time.sleep(1)

    except Exception as e:
        logger.error("❌ Could not open region selector: %s", e)
        driver.quit()
        return []

    regions = []
    seen = set()

    def extract_links():
        links = driver.find_elements(By.CSS_SELECTOR, "a.modalRegName")
        new_regions = []

        for link in links:
            try:
                class_attr = link.get_attribute("class") or ""
                is_parent = "hasLvl" in class_attr
                href = link.get_attribute("href")
                title = link.get_attribute("title").strip()

                # ✅ Parent Region → expand to get subregions
                if is_parent:
                    logger.debug(f"📂 Expanding parent region: {title}")
                    if not safe_click(driver, link):
                        logger.warning(f"⚠️ Failed to click or extract subregions for {title}")
                        continue
                    time.sleep(1)

                    try:
                        subregion_anchors = driver.find_elements(By.CSS_SELECTOR, "li.col-md-4 > a[href*='liveuamap.com']")
                        for sub_a in subregion_anchors:
                            sub_href = sub_a.get_attribute("href")
                            sub_name = sub_a.text.strip() or sub_a.get_attribute("title").strip()
                            if not sub_name:
                                continue
                            subdomain = sub_href.split("//")[1].split(".")[0]
                            if subdomain not in seen:
                                seen.add(subdomain)
                                new_regions.append({"name": sub_name, "subdomain": subdomain})
                                logger.debug(f"✅ Subregion added: {sub_name} ({subdomain})")
                    except Exception as e:
                        logger.warning(f"⚠️ Failed extracting subregions from {title}: {e}")

                    try:
                        return_link = driver.find_element(By.CSS_SELECTOR, "a.retallregs")
                        safe_click(driver, return_link)
                        time.sleep(1)
                        scroll_modal_to_bottom(driver)  # Scroll again after returning
                    except Exception as e:
                        logger.warning(f"⚠️ Could not return to all regions after {title}: {e}")
                    continue

                # ✅ Standalone Region
                if href and "liveuamap.com" in href:
                    subdomain = href.split("//")[1].split(".")[0]
                    if subdomain.lower() in ["login", "about", "privacy", "terms"]:
                        continue
                    if subdomain not in seen:
                        name = link.text.strip() or link.get_attribute("title").strip()
                        if not name:
                            continue
                        seen.add(subdomain)
                        new_regions.append({"name": name, "subdomain": subdomain})
                        logger.debug(f"✅ Region added: {name} ({subdomain})")

            except Exception as e:
                logger.warning(f"⚠️ Error processing region link: {e}")

        return new_regions

    try:
        regions = extract_links()
        logger.info(f"✅ Found {len(regions)} valid regions.")
        return regions

    except Exception as e:
        logger.error("❌ Error extracting region links: %s", e)
        return []

    finally:
        driver.quit()
        
def scroll_modal_to_bottom(driver, container_selector="div.modal-body", pause_time=0.5, max_scrolls=30):
    try:
        scroll_box = driver.find_element(By.CSS_SELECTOR, container_selector)
        last_height = driver.execute_script("return arguments[0].scrollHeight", scroll_box)
        for _ in range(max_scrolls):
            driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", scroll_box)
            time.sleep(pause_time)
            new_height = driver.execute_script("return arguments[0].scrollHeight", scroll_box)
            if new_height == last_height:
                break
            last_height = new_height
        logger.info("✅ Scrolled modal to bottom.")
    except Exception as e:
        logger.warning(f"⚠️ Failed to scroll modal: {e}")


def safe_click(driver, element, retries=3):
    for attempt in range(retries):
        try:
            driver.execute_script("arguments[0].scrollIntoView({behavior: 'instant', block: 'center'});", element)
            time.sleep(0.5)
            element.click()
            return True
        except Exception as e:
            logger.warning(f"⚠️ Retry {attempt + 1} clicking failed: {e}")
            time.sleep(1)
    logger.error("❌ Could not click element after retries.")
    return False



def get_user_selected_regions(regions):
    print("\nAvailable Regions:")
    for idx, region in enumerate(regions, 1):
        print(f"{idx}. {region['name']}")

    selection = input("\nEnter region numbers to scrape (comma-separated) or type 'all': ").strip()
    if selection.lower() == "all":
        return [r["subdomain"] for r in regions]

    indices = [int(i.strip()) for i in selection.split(",") if i.strip().isdigit()]
    selected = [regions[i - 1]["subdomain"] for i in indices if 0 < i <= len(regions)]
    return selected

def attempt_click(element, retries=3, delay=1):
    for attempt in range(retries):
        try:
            element.click()
            return
        except ElementClickInterceptedException:
            logger.warning(f"Click attempt {attempt + 1} failed. Retrying...")
            time.sleep(delay)
    logger.error("Failed to click element after several attempts.")

def store_data_in_mongo(event_data_list, collection_name):
    scrape_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    collection = db[collection_name]
    existing_document = collection.find_one({"scrape_time": scrape_time})

    if existing_document:
        collection.update_one(
            {"scrape_time": scrape_time},
            {"$push": {"events": {"$each": event_data_list}}}
        )
        logger.info(f"Updated existing document with scrape time {scrape_time}.")
    else:
        collection.insert_one({
            "scrape_time": scrape_time,
            "events": event_data_list
        })
        logger.info(f"Inserted new document with scrape time {scrape_time}.")

def visit_liveumap(query):
    url = f"https://{query}.liveuamap.com/"
    logger.info(f"Visiting {url}")
    driver = None

    try:
        driver = initialize_driver()
        driver.get(url)
        WebDriverWait(driver, 10).until(lambda d: d.execute_script("return document.readyState") == "complete")

        scroller_div = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "scroller"))
        )

        event_data_list = []
        event_cat_divs = driver.find_elements(By.CSS_SELECTOR, "div[class^='event cat']")
        if event_cat_divs:
            for idx, event_div in enumerate(event_cat_divs, 1):
                try:
                    logger.info(f"Processing Event {idx} div.")
                    attempt_click(event_div)
                    time.sleep(2)
                    attempt_click(event_div)

                    try:
                        marker_time_div = WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.CLASS_NAME, "marker-time"))
                        )
                        location_a = marker_time_div.find_element(By.TAG_NAME, "a")
                        location = location_a.text if location_a else "Location not found"
                    except NoSuchElementException:
                        location = "Location not found"

                    try:
                        xpath_button = driver.find_element(By.XPATH, "//*[@id='top']/div[2]/div[2]/div[2]/div[4]/a")
                        xpath_button.click()
                    except NoSuchElementException:
                        try:
                            jump_to_map_link = driver.find_element(By.CSS_SELECTOR, "div.map_link_par a.map-link")
                            jump_to_map_link.click()
                        except NoSuchElementException:
                            logger.warning(f"No jump-to-map link for Event {idx}.")

                    try:
                        date = event_div.find_element(By.CSS_SELECTOR, "span.date_add").text
                    except NoSuchElementException:
                        date = "Date not found"

                    try:
                        source_url = event_div.find_element(By.CSS_SELECTOR, "a.source-link").get_attribute("href")
                    except NoSuchElementException:
                        source_url = "Source not found"

                    try:
                        data = event_div.find_element(By.CSS_SELECTOR, "div.title").text
                    except NoSuchElementException:
                        data = "Data not found"

                    try:
                        img_src = event_div.find_element(By.CSS_SELECTOR, "label img").get_attribute("src")
                    except NoSuchElementException:
                        img_src = "Image not found"

                    event_data = {
                        "date": date,
                        "source_url": source_url,
                        "data": data,
                        "img_src": img_src,
                        "location": location
                    }

                    event_data_list.append(event_data)
                    time.sleep(2)

                except Exception as e:
                    logger.error(f"Error during processing Event {idx}: {e}")

        store_data_in_mongo(event_data_list, query.lower())

    except Exception as e:
        logger.error(f"Error while scraping {url}: {e}")
    finally:
        if driver:
            driver.quit()
            logger.info("Driver closed.")

def main():
    try:
        regions = get_available_regions()
        selected_subdomains = get_user_selected_regions(regions)

        all_events = []

        for subdomain in selected_subdomains:
            url = f"https://{subdomain}.liveuamap.com/"
            logger.info(f"Scraping: {url}")

            driver = initialize_driver()
            driver.get(url)
            WebDriverWait(driver, 10).until(lambda d: d.execute_script("return document.readyState") == "complete")
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CLASS_NAME, "scroller")))

            event_data_list = []
            event_cat_divs = driver.find_elements(By.CSS_SELECTOR, "div[class^='event cat']")
            for idx, event_div in enumerate(event_cat_divs, 1):
                try:
                    logger.info(f"Processing Event {idx}...")
                    attempt_click(event_div)
                    time.sleep(1)
                    attempt_click(event_div)

                    try:
                        marker_time_div = WebDriverWait(driver, 5).until(
                            EC.presence_of_element_located((By.CLASS_NAME, "marker-time"))
                        )
                        location_a = marker_time_div.find_element(By.TAG_NAME, "a")
                        location = location_a.text if location_a else "Location not found"
                    except NoSuchElementException:
                        location = "Location not found"

                    try:
                        xpath_button = driver.find_element(By.XPATH, "//*[@id='top']/div[2]/div[2]/div[2]/div[4]/a")
                        xpath_button.click()
                    except NoSuchElementException:
                        try:
                            jump_to_map_link = driver.find_element(By.CSS_SELECTOR, "div.map_link_par a.map-link")
                            jump_to_map_link.click()
                        except NoSuchElementException:
                            pass

                    event_data = {
                        "region": subdomain,
                        "date": event_div.find_element(By.CSS_SELECTOR, "span.date_add").text if event_div.find_elements(By.CSS_SELECTOR, "span.date_add") else "Date not found",
                        "source_url": event_div.find_element(By.CSS_SELECTOR, "a.source-link").get_attribute("href") if event_div.find_elements(By.CSS_SELECTOR, "a.source-link") else "Source not found",
                        "data": event_div.find_element(By.CSS_SELECTOR, "div.title").text if event_div.find_elements(By.CSS_SELECTOR, "div.title") else "Data not found",
                        "img_src": event_div.find_element(By.CSS_SELECTOR, "label img").get_attribute("src") if event_div.find_elements(By.CSS_SELECTOR, "label img") else "Image not found",
                        "location": location
                    }
                    event_data_list.append(event_data)

                except Exception as e:
                    logger.error(f"Error during processing Event {idx}: {e}")

            all_events.extend(event_data_list)
            driver.quit()

        if not all_events:
            logger.warning("⚠️ No events collected from selected regions.")
            return

        # Prompt user where to save
        while True:
            output_choice = input("\nSave scraped data to: [csv / mongo / both] → ").strip().lower()
            if output_choice in ["csv", "mongo", "both"]:
                break
            print("Invalid input. Please enter 'csv', 'mongo', or 'both'.")

        if output_choice in ["csv", "both"]:
            save_to_csv(all_events)

        if output_choice in ["mongo", "both"]:
            for subdomain in selected_subdomains:
                relevant_data = [e for e in all_events if e["region"] == subdomain]
                store_data_in_mongo(relevant_data, subdomain.lower())

    except Exception as e:
        logger.error(f"Scraper encountered an error: {e}")


if __name__ == "__main__":
    main()

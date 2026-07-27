from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from datetime import datetime, timedelta
import re
import time
import json


def parse_seek_posted_at(text):
    if not text:
        return None
    t = text.lower().strip()
    if "just posted" in t or "just now" in t:
        return datetime.now().isoformat()
    m = re.search(r"(\d+)\s*([mhdw])(?![a-z])", t)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    delta = {
        "m": timedelta(minutes=n),
        "h": timedelta(hours=n),
        "d": timedelta(days=n),
        "w": timedelta(weeks=n),
    }[unit]
    return (datetime.now() - delta).isoformat()


QUERYS = [
    ["https://www.seek.com.au/jobs-in-information-communication-technology/in-Brisbane-QLD-4000?distance=100&subclassification=6287%2C6290%2C6302%2C6291%2C6286%2C6293"],
    ["https://www.seek.com.au/jobs-in-information-communication-technology/in-Cooroy-QLD-4563?distance=50&subclassification=6287%2C6290%2C6302%2C6291%2C6286%2C6293"],
    ["https://www.seek.com.au/jobs-in-information-communication-technology/in-Surfers-Paradise-QLD-4217?distance=50&subclassification=6287%2C6290%2C6302%2C6291%2C6286%2C6293"],
]

def setup_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--width=1920")
    options.add_argument("--height=1080")
    options.set_preference("general.useragent.override", "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv=109.0) Gecko/20100101 Firefox/115.0")

    driver = webdriver.Firefox(options=options)
    return driver

def get(url, max_pages=200):
    driver = setup_driver()
    all_jobs = []

    try:
        driver.get(url)
        time.sleep(3)

        for page in range(1, max_pages + 1):
            print(f"Page {page}: ", end="", flush=True)

            for _ in range(3):
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1)

            title_elems = driver.find_elements(By.CSS_SELECTOR, "[data-automation='jobTitle']")
            company_elems = driver.find_elements(By.CSS_SELECTOR, "[data-automation='jobCompany']")

            if not title_elems:
                print("No jobs found")
                break

            page_jobs = 0
            for title_elem, company_elem in zip(title_elems, company_elems):
                try:
                    title = title_elem.text.strip()
                    job_url = title_elem.get_attribute("href")
                    company = company_elem.text.strip()

                    raw = ""
                    try:
                        date_elem = title_elem.find_element(By.XPATH, "./ancestor::article[1]//*[@data-automation='jobListingDate']")
                        raw = date_elem.text.strip()
                    except:
                        pass
                    posted_at = parse_seek_posted_at(raw)

                    if title and job_url:
                        job = {
                            "reference_url": job_url.split("?")[0],
                            "job_title": title,
                            "company": company,
                            "posted_at": posted_at,
                        }
                        all_jobs.append(job)
                        page_jobs += 1

                except:
                    pass

            print(f"{page_jobs} jobs", end="", flush=True)

            try:
                next_link = driver.find_element(By.CSS_SELECTOR, "a[aria-label='Next']")
                next_url = next_link.get_attribute("href")
                driver.get(next_url)
                time.sleep(3)
                print(" -> ", end="", flush=True)
            except:
                print(" (no next)", end="", flush=True)
                break

    finally:
        driver.quit()

    return all_jobs

if __name__ == "__main__":
    url = "https://www.seek.com.au/jobs-in-information-communication-technology/in-Brisbane-QLD-4000?subclassification=6287%2C6290%2C6302"

    print("Starting Seek job scraper...")
    print("=" * 50)
    jobs = get(url, max_pages=3)

    print("\n" + "=" * 50)
    print(f"Total jobs found: {len(jobs)}")
    for job in jobs:
        print(f"{job['job_title']} at {job['company']}")
        print(f"  {job['reference_url']}")

from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
import time
import json

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
    
    service = Service(executable_path="/usr/bin/geckodriver")
    driver = webdriver.Firefox(options=options, service=service)
    return driver

def get(url, max_pages=20):
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
            
            cards = driver.find_elements(By.CSS_SELECTOR, "article")
            
            if not cards:
                print("No articles found")
                break
            
            page_jobs = 0
            for card in cards:
                try:
                    links = card.find_elements(By.TAG_NAME, "a")
                    title = ""
                    job_url = ""
                    for link in links:
                        href = link.get_attribute("href")
                        if href and "/job/" in href and "seek.com.au/job/" in href:
                            title = link.text.strip()
                            if title:
                                job_url = href
                                break
                    
                    if title and job_url:
                        company_elem = card.find_elements(By.CSS_SELECTOR, "[data-automation='jobCompany']")
                        company = company_elem[0].text.strip() if company_elem else ""
                        
                        job = {
                            "reference_url": job_url.split("?")[0],
                            "job_title": title,
                            "company": company,
                        }
                        all_jobs.append(job)
                        page_jobs += 1
                    
                except:
                    pass
            
            print(f"{page_jobs} jobs", end="", flush=True)
            
            try:
                next_link = driver.find_element(By.CSS_SELECTOR, "li._6wfnkxbd > a:nth-child(1)")
                next_link.click()
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
    jobs = scrape_seek_jobs(url, max_pages=20)
    print(jobs)
    exit()
    
    unique_jobs = []
    seen = set()
    for job in jobs:
        base_url = job['reference_url'].split('?')[0]
        if base_url not in seen:
            seen.add(base_url)
            unique_jobs.append(job)
    
    print("\n" + "=" * 50)
    print(f"Total unique jobs found: {len(unique_jobs)}")
    
    with open("seek_jobs.json", "w") as f:
        json.dump(unique_jobs, f, indent=2)
    
    print(f"\nJobs saved to seek_jobs.json\n")
    
    for job in unique_jobs:
        print(f"{job['job_title']} at {job['company']}")
        print(f"  {job['reference_url']}")

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import scrape_seek

def scrape():
    url = "https://www.seek.com.au/jobs-in-information-communication-technology/in-Brisbane-QLD-4000?subclassification=6287%2C6290%2C6302"
    return scrape_seek.scrape_seek_jobs(url, max_pages=50)

import requests
from bs4 import BeautifulSoup
import json
import re

QUERYS = [
    ["14904", "scoring desc", "49", '"Brisbane Inner City" "Brisbane - North" "Brisbane - South" "Brisbane - East" "Brisbane - West"']
]

BASE_URL = "https://smartjobs.qld.gov.au"

def get(*args, max_pages=None):
    in_organid = args[0] if len(args) > 0 else "14904"
    in_orderby = args[1] if len(args) > 1 else "scoring desc"
    in_others_region = args[2] if len(args) > 2 else "49"
    in_others_location = args[3] if len(args) > 3 else ""
    
    form_data = {
        "in_version": "",
        "in_sessionid": "",
        "in_graphic": "",
        "javaProxyUrl": "",
        "in_param5": "",
        "in_param": "",
        "in_organid": in_organid,
        "in_usid": "",
        "in_others": in_others_region,
        "in_orderby": in_orderby,
        "in_skills": "",
        "in_location": in_others_location,
        "in_multi01": in_others_region + "~",
        "in_multi01_id": "1108",
        "in_param1": "",
        "in_param2": "",
        "in_param6": "",
        "in_param7": "",
        "in_multi02": "",
        "in_multi02_id": "requirements.agencynumber"
    }
    
    response = requests.post(
        f"{BASE_URL}/jobtools/jncustomsearch.searchResults",
        data=form_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    
    soup = BeautifulSoup(response.text, 'html.parser')
    total_rows_input = soup.find('input', {'name': 'in_totalrows'})
    total_rows = int(total_rows_input.get('value', '0')) if total_rows_input else 0
    
    page_size = 20
    num_pages = (total_rows + page_size - 1) // page_size
    
    if max_pages:
        num_pages = min(num_pages, max_pages)
    
    print(f"Total jobs: {total_rows}, pages: {num_pages}")
    
    all_jobs = []
    
    for page in range(num_pages):
        page_offset = page * page_size
        form_data["in_pg"] = str(page_offset)
        
        response = requests.post(
            f"{BASE_URL}/jobtools/jncustomsearch.searchResults",
            data=form_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        
        print(f"Page {page + 1}: Status {response.status_code}")
        
        jobs = parse_jobs(response.text)
        all_jobs.extend(jobs)
        print(f"  Found {len(jobs)} jobs")
    
    return all_jobs

def fetch_posted_at(url):
    try:
        r = requests.get(url, timeout=10)
        m = re.search(r'"datePosted"\s*:\s*"([^"]+)"', r.text)
        return m.group(1) if m else None
    except:
        return None

def parse_jobs(html):
    jobs = []
    soup = BeautifulSoup(html, 'html.parser')
    
    bad_links = soup.find_all('a', href=lambda h: h and 'viewFullSingle' in h)
    good_links = soup.find_all('a', href=lambda h: h and '/jobs/QLD' in h)
    
    for link in bad_links:
        href = link.get('href', '')
        if not href:
            continue
        
        full_url = f"{BASE_URL}/jobtools/{href}"
        
        title_span = link.find('span', class_='result-title')
        if title_span:
            job_title = title_span.get_text(strip=True)
        else:
            job_title = link.get_text(strip=True)
        
        company = "Queensland Government"

        job = {
            "reference_url": full_url,
            "job_title": job_title,
            "company": company,
            "posted_at": fetch_posted_at(full_url),
        }
        jobs.append(job)

    for link in good_links:
        href = link.get('href', '')
        if not href:
            continue
        
        full_url = f"{BASE_URL}/{href}"
        
        title_span = link.find('span', class_='result-title')
        if title_span:
            job_title = title_span.get_text(strip=True)
        else:
            job_title = link.get_text(strip=True)
        
        company = "Queensland Government"

        job = {
            "reference_url": full_url,
            "job_title": job_title,
            "company": company,
            "posted_at": fetch_posted_at(full_url),
        }
        jobs.append(job)

    return jobs

if __name__ == "__main__":
    query = QUERYS[0]
    jobs = get(*query)
    print(f"\nTotal jobs found: {len(jobs)}")
    print(json.dumps(jobs, indent=2))

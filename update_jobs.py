import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scrapers import seek
from jobs_db import add_jobs

def query_():
    while True:
        update = input("do you want to update jobs listings? [y/n]: ")

        if update.lower() == "y":
            start_update()
            break
        elif update.lower() == "n":
            break


def start_update():
    print("Starting job update...")
    print("=" * 40)
    
    total_jobs = 0
    
    print("\nRunning seek scraper...")
    try:
        jobs = seek.scrape()
        print(f"  Got {len(jobs)} jobs")
        add_jobs(jobs)
        print(f"  Added {len(jobs)} jobs to database")
        total_jobs += len(jobs)
    except Exception as e:
        print(f"  Error: {e}")
    
    print("\n" + "=" * 40)
    print(f"Update complete. Total jobs added: {total_jobs}")

if __name__ == "__main__":
    start_update()

import sys
import os
import importlib

import jobs_db

IMPORT_DIR = "job_finders"

def query_update():
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

    # find files with job getters
    os.makedirs(IMPORT_DIR, exist_ok=True)
    files = os.listdir(IMPORT_DIR)

    # get all jobs from them
    for f in files:
        if f == "__pycache__":
            continue

        print(f"trying to get from {f}")
        try:
            module = f.strip(".py")
            module = importlib.import_module(f"{IMPORT_DIR}.{f.strip('.py')}")
            
            Q = getattr(module, "QUERYS")
            get = getattr(module, "get")

            jobs = []

            for q in Q:
                jobs += get(*q)
            
            n = jobs_db.add_jobs(jobs)

            print(f"\nadded {n} new jobs to the database")

        except Exception as e:
            print(f"{f} failed with {e}")

        print("Done")

if __name__ == "__main__":
    start_update()

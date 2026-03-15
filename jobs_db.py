import sqlite3

DB_PATH = "jobs.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            reference_url TEXT PRIMARY KEY,
            job_title TEXT NOT NULL,
            company TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


def add_jobs(jobs):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.executemany(
        "INSERT OR IGNORE INTO jobs (reference_url, job_title, company, status) VALUES (?, ?, ?, ?)",
        [(j["reference_url"], j["job_title"], j["company"], j.get("status", "pending")) for j in jobs]
    )

    conn.commit()
    conn.close()

    return cursor.rowcount

def get_jobs_by_status(status_filter="%"):
    if not status_filter in ["pending", "excluded", "applied"]:
        status_filter = "%"

    conn = sqlite3.connect(DB_PATH)
    
    cursor = conn.execute(
        "SELECT reference_url, job_title, company, status FROM jobs WHERE status LIKE ? ORDER BY rowid DESC",
        (status_filter,)
    )

    jobs = cursor.fetchall()

    conn.close()
    return [{"url":job[0], "title":job[1], "company":job[2], "status":job[3]} for job in jobs] # anotate in dict and return

def update_status(reference_url, status):
    conn = sqlite3.connect(DB_PATH)
    
    conn.execute("UPDATE jobs SET status = ? WHERE reference_url = ?", (status, reference_url))
    
    conn.commit()
    conn.close()

init_db() # make sure the db exists on file import

if __name__ == "__main__":
    #init_db()
    #print("Database created successfully with jobs table.")
    print(get_jobs_by_status("pending"))

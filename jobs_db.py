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


if __name__ == "__main__":
    init_db()
    print("Database created successfully with jobs table.")

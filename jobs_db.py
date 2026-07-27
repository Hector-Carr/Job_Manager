import contextlib
import datetime
import os
import signal
import sqlite3
import atexit

import libsql
from dotenv import load_dotenv

load_dotenv()

DB_PATH = "jobs.db"
META_PATH = DB_PATH + "-info"          # libsql writes replica metadata here
SIDECARS = (DB_PATH + "-wal", DB_PATH + "-shm")
LEGACY_BACKUP = "jobs.db.pre-turso.bak"

TURSO_URL = os.getenv("TURSO_URL")
TURSO_TOKEN = os.getenv("TURSO_TOKEN")

SCHEMA = """
    CREATE TABLE IF NOT EXISTS jobs (
        reference_url TEXT PRIMARY KEY,
        job_title TEXT NOT NULL,
        company TEXT NOT NULL,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        posted_at TIMESTAMP
    )
"""
COLUMNS = "reference_url, job_title, company, status, posted_at"

_conn = None
_closed = False
_SHUTDOWN_SIGNALS = tuple(getattr(signal, s) for s in ("SIGINT", "SIGTERM", "SIGHUP")
                          if hasattr(signal, s))


def cloud_enabled() -> bool:
    return bool(TURSO_URL and TURSO_TOKEN)


############ keeping a sync alive to the end ##########
@contextlib.contextmanager
def uninterruptible():
    """
    Hold off Ctrl-C / SIGTERM / SIGHUP for the duration of the block, so a sync
    in flight is never abandoned partway leaving the replica ahead of the remote.

    Two things combine to give that guarantee, and it is worth knowing which one
    is load bearing. CPython only runs python level signal handlers in the main
    thread between bytecodes, so the C call inside conn.sync() always runs to
    completion regardless of this mask - that is the real protection. The mask
    adds to it by stopping the main thread taking an EINTR driven early exit
    mid-syscall. It cannot stop the kernel delivering a process directed signal
    to one of libsql's rust background threads, which is why the handler can
    still appear to fire promptly - the sync has already finished by then.
    """
    if not hasattr(signal, "pthread_sigmask"):
        yield
        return

    try:
        previous = signal.pthread_sigmask(signal.SIG_BLOCK, _SHUTDOWN_SIGNALS)
    except (ValueError, OSError):
        yield
        return

    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)


############ replica setup ##########
def _read_legacy_rows():
    """
    The old jobs.db is a plain sqlite file. libsql refuses to adopt one as a
    replica (it wants its own -info metadata beside it), so lift the rows out
    and move the file aside to be re-seeded into the fresh replica.
    """
    if not os.path.exists(DB_PATH):
        return []

    try:
        legacy = sqlite3.connect(DB_PATH)
        rows = legacy.execute(f"SELECT {COLUMNS} FROM jobs").fetchall()
        legacy.close()
    except sqlite3.DatabaseError:
        rows = []

    os.replace(DB_PATH, LEGACY_BACKUP)
    for path in SIDECARS:
        if os.path.exists(path):
            os.remove(path)

    return rows


def _open():
    """Return a connection, building the local replica the first time round."""
    if not cloud_enabled():
        return sqlite3.connect(DB_PATH)

    credentials = {"sync_url": TURSO_URL, "auth_token": TURSO_TOKEN}

    if not os.path.exists(META_PATH):
        legacy_rows = _read_legacy_rows()

        # a fresh replica has to be pulled to the remote's head before it may
        # push anything, otherwise its first sync is rejected as a conflict
        boot = libsql.connect(DB_PATH, **credentials)
        boot.sync()
        boot.close()

        conn = libsql.connect(DB_PATH, offline=True, **credentials)
        conn.execute(SCHEMA)
        if legacy_rows:
            conn.executemany(
                f"INSERT OR IGNORE INTO jobs ({COLUMNS}) VALUES (?, ?, ?, ?, ?)",
                legacy_rows,
            )
        conn.commit()
        return conn

    return libsql.connect(DB_PATH, offline=True, **credentials)


def connect():
    global _conn
    if _conn is None:
        _conn = _open()
    return _conn


############ sync ##########
def sync() -> bool:
    """
    Push local writes and pull anything the other devices did. Bidirectional.

    Never raises: losing the network should cost you the sync, not the session.
    Writes already committed to the replica are durable on disk either way and
    go up on the next successful sync.
    """
    if _conn is None or not cloud_enabled():
        return False

    with uninterruptible():
        try:
            _conn.sync()
            return True
        except Exception as e:
            if "conflict" in str(e).lower():
                return _recover_from_conflict()
            return False


def _recover_from_conflict() -> bool:
    """
    The replica diverged from the remote - we held unpushed writes while another
    device pushed (only really possible after a hard kill that skipped the exit
    flush). Rebuild the replica from the remote and replay our rows on top, so
    local status changes win. The pre-rebuild file is kept, not deleted.
    """
    global _conn

    try:
        rows = _conn.execute(f"SELECT {COLUMNS} FROM jobs").fetchall()
    except Exception:
        return False

    with contextlib.suppress(Exception):
        _conn.close()
    _conn = None

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    os.replace(DB_PATH, f"{DB_PATH}.conflict-{stamp}.bak")
    for path in (META_PATH,) + SIDECARS:
        if os.path.exists(path):
            os.remove(path)

    try:
        conn = _open()
        conn.execute(SCHEMA)
        conn.executemany(
            f"INSERT OR IGNORE INTO jobs ({COLUMNS}) VALUES (?, ?, ?, ?, ?)", rows
        )
        for row in rows:
            conn.execute(
                "UPDATE jobs SET status = ? WHERE reference_url = ?", (row[3], row[0])
            )
        conn.commit()
        conn.sync()
        _conn = conn
        return True
    except Exception:
        return False


############ shutdown ##########
def _shutdown():
    """Final flush. Runs on normal exit, Ctrl-C, SIGTERM and SIGHUP alike."""
    global _closed
    if _closed or _conn is None:
        return
    _closed = True

    with uninterruptible():
        with contextlib.suppress(Exception):
            _conn.commit()
        sync()
        with contextlib.suppress(Exception):
            _conn.close()


def _on_terminate(signum, frame):
    # raise rather than exit outright so curses.wrapper still gets to restore
    # the terminal on the way out, and atexit still fires
    raise SystemExit(128 + signum)


atexit.register(_shutdown)
for _sig in (getattr(signal, "SIGTERM", None), getattr(signal, "SIGHUP", None)):
    if _sig is not None:
        with contextlib.suppress(ValueError, OSError):
            signal.signal(_sig, _on_terminate)


############ queries ##########
def init_db():
    conn = connect()
    conn.execute(SCHEMA)

    cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    if "posted_at" not in cols:
        conn.execute("ALTER TABLE jobs ADD COLUMN posted_at TIMESTAMP")

    conn.commit()
    sync()  # pull whatever the other devices have done since last time


def add_jobs(jobs):
    conn = connect()

    before = conn.execute("SELECT count(*) FROM jobs").fetchall()[0][0]
    conn.executemany(
        f"INSERT OR IGNORE INTO jobs ({COLUMNS}) VALUES (?, ?, ?, ?, ?)",
        [
            (j["reference_url"], j["job_title"], j["company"],
             j.get("status", "pending"), j.get("posted_at"))
            for j in jobs
        ],
    )
    conn.commit()
    after = conn.execute("SELECT count(*) FROM jobs").fetchall()[0][0]

    sync()  # a scrape is a big infrequent write, worth pushing straight away
    return after - before


def get_jobs_by_status(status_filter="%"):
    if status_filter not in ["pending", "excluded", "applied"]:
        status_filter = "%"

    conn = connect()
    jobs = conn.execute(
        f"SELECT {COLUMNS} FROM jobs WHERE status LIKE ? "
        "ORDER BY posted_at IS NULL, posted_at DESC, rowid DESC",
        (status_filter,),
    ).fetchall()

    return [{"url": j[0], "title": j[1], "company": j[2], "status": j[3], "posted_at": j[4]}
            for j in jobs]


def update_status(reference_url, status):
    conn = connect()
    conn.execute("UPDATE jobs SET status = ? WHERE reference_url = ?", (status, reference_url))
    conn.commit()
    # deliberately no sync here - this fires on every keypress during triage and
    # a round trip to Tokyo is ~2s. The exit flush pushes them as a batch.


init_db()  # make sure the db exists on file import

if __name__ == "__main__":
    print(f"cloud sync: {'on' if cloud_enabled() else 'off (local only)'}")
    print(f"pending: {len(get_jobs_by_status('pending'))}")

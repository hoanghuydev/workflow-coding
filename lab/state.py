"""Durable job transitions; a completed job is never implicitly retried."""
from contextlib import contextmanager
import fcntl
import json
from pathlib import Path
import sqlite3
from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def run_lock(directory):
    with (directory / ".lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("Another supervisor is using this run") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def process_group_alive(pid):
    # Ignore zombies; a live child can outlast its CLI parent after a crash.
    if not pid:
        return False
    for entry in Path("/proc").glob("[0-9]*/stat"):
        try:
            fields = entry.read_text().rsplit(") ", 1)[1].split()
            if int(fields[2]) == pid and fields[0] != "Z":
                return True
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
    return False


class State:
    def __init__(self, directory):
        self.db = sqlite3.connect(directory / "state.db")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, stage TEXT NOT NULL, worker TEXT NOT NULL,
            status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
            metadata TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        self.db.commit()

    def close(self):
        self.db.close()

    def get(self, job_id):
        row = self.db.execute("SELECT status, attempts, metadata FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            return None
        return {"status": row[0], "attempts": row[1], "metadata": json.loads(row[2])}

    def plan(self, job_id, stage, worker):
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO jobs VALUES (?, ?, ?, 'pending', 0, '{}', ?)",
                            (job_id, stage, worker, now()))

    def start(self, job_id, max_calls):
        with self.db:
            if self.calls() >= max_calls:
                raise ValueError(f"Model call limit reached ({max_calls}); no inference started")
            self.db.execute("UPDATE jobs SET status='running', attempts=attempts+1, metadata='{}', updated_at=? WHERE id=?",
                            (now(), job_id))

    def save(self, job_id, metadata):
        with self.db:
            self.db.execute("UPDATE jobs SET status=?, metadata=?, updated_at=? WHERE id=?",
                            (metadata["status"], json.dumps(metadata, ensure_ascii=False), now(), job_id))

    def calls(self):
        return self.db.execute("SELECT COALESCE(SUM(attempts),0) FROM jobs").fetchone()[0]

    def rows(self):
        return [{"job": row[0], "stage": row[1], "worker": row[2], "status": row[3],
                 "attempts": row[4], **json.loads(row[5])}
                for row in self.db.execute("SELECT id,stage,worker,status,attempts,metadata FROM jobs ORDER BY rowid")]

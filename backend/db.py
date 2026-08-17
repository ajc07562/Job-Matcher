"""
Lightweight SQLite persistence for users and saved matches. Plain sqlite3 from
the standard library — no ORM — since the schema is small and stable.
"""
import sqlite3
import time
from contextlib import contextmanager
from typing import Optional

from backend.config import DB_FILE


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS saved_matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                job_id TEXT NOT NULL,
                company TEXT NOT NULL,
                title TEXT NOT NULL,
                final_score REAL NOT NULL,
                explanation TEXT,
                url TEXT,
                created_at INTEGER NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                UNIQUE(user_id, job_id)
            )
        """)


def create_user(email: str, password_hash: str) -> sqlite3.Row:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email.lower().strip(), password_hash, int(time.time())),
        )
        user_id = cur.lastrowid
        return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def get_user_by_email(email: str) -> Optional[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE email = ?", (email.lower().strip(),)
        ).fetchone()


def get_user_by_id(user_id: int) -> Optional[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def save_match(user_id: int, job_id: str, company: str, title: str,
                final_score: float, explanation: Optional[str], url: Optional[str]) -> sqlite3.Row:
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO saved_matches (user_id, job_id, company, title, final_score, explanation, url, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(user_id, job_id) DO UPDATE SET
                   final_score=excluded.final_score,
                   explanation=excluded.explanation,
                   created_at=excluded.created_at""",
            (user_id, job_id, company, title, final_score, explanation, url, int(time.time())),
        )
        return conn.execute(
            "SELECT * FROM saved_matches WHERE user_id = ? AND job_id = ?",
            (user_id, job_id),
        ).fetchone()


def delete_saved_match(user_id: int, job_id: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM saved_matches WHERE user_id = ? AND job_id = ?",
            (user_id, job_id),
        )


def get_saved_matches(user_id: int) -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM saved_matches WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()

"""SQLite memory store - records all channel messages and summaries."""
import sqlite3
import os
from config import DB_PATH


def _ensure_dir():
    d = os.path.dirname(DB_PATH)
    if d:
        os.makedirs(d, exist_ok=True)


def get_conn():
    _ensure_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT UNIQUE,
            channel TEXT,
            user_id TEXT,
            user_name TEXT,
            text TEXT,
            thread_ts TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT UNIQUE,
            summary TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS knowledge (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE,
            value TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()


def store_message(ts, channel, user_id, user_name, text, thread_ts=None):
    conn = get_conn()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO messages (ts, channel, user_id, user_name, text, thread_ts) VALUES (?, ?, ?, ?, ?, ?)",
            (ts, channel, user_id, user_name, text, thread_ts)
        )
        conn.commit()
    finally:
        conn.close()


def get_recent_messages(limit=50):
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT user_name, text, ts, created_at FROM messages ORDER BY ts DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return list(reversed(rows))
    finally:
        conn.close()


def get_all_messages_for_date(date_str):
    """Get all messages for a specific date (YYYY-MM-DD)."""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT user_name, text FROM messages WHERE DATE(created_at) = ? ORDER BY ts",
            (date_str,)
        ).fetchall()
        return rows
    finally:
        conn.close()


def get_summaries():
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT date, summary FROM summaries ORDER BY date"
        ).fetchall()
        return rows
    finally:
        conn.close()


def store_summary(date_str, summary):
    conn = get_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO summaries (date, summary) VALUES (?, ?)",
            (date_str, summary)
        )
        conn.commit()
    finally:
        conn.close()


def get_knowledge(key):
    conn = get_conn()
    try:
        row = conn.execute("SELECT value FROM knowledge WHERE key = ?", (key,)).fetchone()
        return row['value'] if row else None
    finally:
        conn.close()


def set_knowledge(key, value):
    conn = get_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO knowledge (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
            (key, value)
        )
        conn.commit()
    finally:
        conn.close()


def get_message_count():
    conn = get_conn()
    try:
        row = conn.execute("SELECT COUNT(*) as cnt FROM messages").fetchone()
        return row['cnt']
    finally:
        conn.close()

import sqlite3
from datetime import datetime

DB_FILE = "cleardrive.db"


def init_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scans (
            id INTEGER PRIMARY KEY,
            timestamp TEXT,
            codes TEXT,
            safety TEXT,
            guidance TEXT
        )
    """)
    conn.commit()
    conn.close()


def log_scan(codes: str, safety: str, guidance: str):
    conn = sqlite3.connect(DB_FILE)
    conn.execute(
        "INSERT INTO scans (timestamp, codes, safety, guidance) VALUES (?, ?, ?, ?)",
        (datetime.now().isoformat(), codes, safety, guidance)
    )
    conn.commit()
    conn.close()


def get_recent_scans(limit: int = 10):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.execute(
        "SELECT timestamp, codes, safety, guidance FROM scans ORDER BY id DESC LIMIT ?",
        (limit,)
    )
    rows = cursor.fetchall()
    conn.close()
    return rows
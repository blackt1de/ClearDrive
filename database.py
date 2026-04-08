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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS followups (
            id INTEGER PRIMARY KEY,
            scan_id INTEGER,
            timestamp TEXT,
            question TEXT,
            answer TEXT,
            is_human_generated INTEGER DEFAULT 1,
            FOREIGN KEY (scan_id) REFERENCES scans(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY,
            scan_id INTEGER,
            rating TEXT,
            timestamp TEXT,
            FOREIGN KEY (scan_id) REFERENCES scans(id)
        )
    """)
    conn.commit()
    conn.close()


def log_scan(codes: str, safety: str, guidance: str) -> int:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.execute(
        "INSERT INTO scans (timestamp, codes, safety, guidance) VALUES (?, ?, ?, ?)",
        (datetime.now().isoformat(), codes, safety, guidance)
    )
    scan_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return scan_id


def log_followup(scan_id: int, question: str, answer: str, is_human_generated: bool = True) -> int:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.execute(
        "INSERT INTO followups (scan_id, timestamp, question, answer, is_human_generated) VALUES (?, ?, ?, ?, ?)",
        (scan_id, datetime.now().isoformat(), question, answer, 1 if is_human_generated else 0)
    )
    followup_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return followup_id


def log_feedback(scan_id: int, rating: str) -> int:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.execute(
        "INSERT INTO feedback (scan_id, rating, timestamp) VALUES (?, ?, ?)",
        (scan_id, rating, datetime.now().isoformat())
    )
    feedback_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return feedback_id


def get_recent_scans(limit: int = 10):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.execute(
        "SELECT timestamp, codes, safety, guidance FROM scans ORDER BY id DESC LIMIT ?",
        (limit,)
    )
    rows = cursor.fetchall()
    conn.close()
    return rows

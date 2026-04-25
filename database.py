import sqlite3
import json
import sys
from datetime import datetime
from typing import Optional

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


# ============================================================================
# RESEARCH LOGGING - ADDITIVE, PARALLEL TABLE
# ----------------------------------------------------------------------------
# Everything below is new. It creates and writes to a separate `research_scans`
# table. The original `scans` table and its functions above are NOT touched.
#
# Why a separate table instead of adding columns to `scans`?
#   1. Zero risk of breaking anything that queries the existing table.
#   2. Easy rollback: if we ever want to drop research logging, we drop
#      one table and delete one import - nothing else is affected.
#   3. Clean ethical separation: when the consent flow ships, we can
#      filter/wipe pre-consent rows in research_scans without touching
#      the operational scans table.
#   4. Different retention policies: research data may need GDPR-style
#      expiry rules that the operational log doesn't need.
#
# Schema version is tracked so future migrations are possible without
# breaking old rows.
# ============================================================================

RESEARCH_SCHEMA_VERSION = 1


def init_research_table():
    """
    Create the research_scans table and its indexes if they don't exist.

    Safe to call on every startup. Uses CREATE TABLE IF NOT EXISTS, so
    running it repeatedly is a no-op after first creation.

    Unlike log_research_scan(), this function raises on failure. Startup-time
    table creation failing is something we want to know about immediately -
    it means the DB file is unwritable or corrupt. We do NOT want to silently
    run an app whose research logging is broken.

    Call this once at startup, right after init_db().
    """
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS research_scans (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp             TEXT NOT NULL,

            -- Identity + consent tracking.
            -- Defaults are safe placeholders so logging works before the
            -- A/B and consent systems exist. When they ship, callers pass
            -- real values instead.
            user_id_hash          TEXT NOT NULL DEFAULT 'anonymous',
            ab_bucket             TEXT,
            consent_version       TEXT NOT NULL DEFAULT 'pre-consent',

            -- Which model produced this response.
            -- Critical for A/B analysis between base-gemma, dspy-gemma,
            -- cleardrive-gemma, etc. Today it'll be 'groq-llama-3.1-8b'.
            model_version         TEXT NOT NULL DEFAULT 'unknown',

            -- Vehicle context captured from CarsXE VIN decode.
            -- Stored as JSON because the shape may evolve and we don't
            -- want to migrate the schema every time we add a field.
            vehicle_id            TEXT,
            trim                  TEXT,
            vehicle_profile_json  TEXT,

            -- OBD data sent into the prompt.
            codes_json            TEXT,
            rpm                   INTEGER,
            speed_mph             INTEGER,
            coolant_temp_f        INTEGER,
            obd_source            TEXT,

            -- The full prompt sent to the LLM and the raw text it returned.
            -- These two fields are the "training data payload" - the single
            -- most important pair of fields in this table. Without them,
            -- scans cannot be used as training examples later.
            prompt_text           TEXT,
            response_text         TEXT,

            -- The parsed 11-section response as JSON, for querying without
            -- re-parsing. Derived from response_text by the caller.
            response_parsed_json  TEXT,

            -- Derived fields promoted to columns for quick filtering /
            -- aggregation without JSON extraction.
            safety_level          TEXT,
            had_error             INTEGER NOT NULL DEFAULT 0,
            latency_ms            INTEGER,

            -- User feedback, populated later via update_research_rating().
            -- NULL until the user taps good / ok / bad in the iOS app.
            user_rating           TEXT,
            user_comment          TEXT,

            -- Which scrapers / APIs contributed context to this scan.
            -- Operational - useful for debugging which sources were hit.
            data_sources_json     TEXT,

            -- Schema version of this row. Lets us write migration scripts
            -- later that know how to read older rows.
            schema_version        INTEGER NOT NULL DEFAULT 1
        )
    """)

    # Indexes for the queries we'll actually run.
    # - timestamp DESC: "show me recent scans" (the default admin query)
    # - model_version: A/B analysis ("show me all cleardrive-gemma scans")
    # - user_rating: filter to only scans the user actually rated
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_research_scans_timestamp "
        "ON research_scans(timestamp DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_research_scans_model "
        "ON research_scans(model_version)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_research_scans_rating "
        "ON research_scans(user_rating)"
    )

    conn.commit()
    conn.close()


def log_research_scan(
    *,
    model_version: str,
    vehicle_id: Optional[str] = None,
    trim: Optional[str] = None,
    vehicle_profile: Optional[dict] = None,
    codes: Optional[list] = None,
    rpm: Optional[int] = None,
    speed_mph: Optional[int] = None,
    coolant_temp_f: Optional[int] = None,
    obd_source: Optional[str] = None,
    prompt_text: Optional[str] = None,
    response_text: Optional[str] = None,
    response_parsed: Optional[dict] = None,
    safety_level: Optional[str] = None,
    had_error: bool = False,
    latency_ms: Optional[int] = None,
    data_sources: Optional[list] = None,
    user_id_hash: str = "anonymous",
    ab_bucket: Optional[str] = None,
    consent_version: str = "pre-consent",
) -> Optional[int]:
    """
    Insert a research-grade scan record. Returns the new row's id on success,
    or None on failure.

    KEYWORD-ONLY ARGUMENTS: the leading `*` forces every caller to name its
    arguments explicitly. This prevents the classic bug where someone adds
    a new field in the middle of the parameter list and every existing call
    site silently passes the wrong value to the wrong column.

    FAILURE BEHAVIOR: this function catches every exception internally and
    returns None on failure. It NEVER raises. The reason is the same as why
    the try/except wraps the entire body: if this function raises, it could
    propagate up through the /interpret endpoint and cause the user to see
    a 500 error instead of their diagnosis. Research logging must never
    break the user-facing flow.

    Failures are printed to stderr so they show up in server logs and we
    can investigate later.
    """
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.execute(
            """
            INSERT INTO research_scans (
                timestamp, user_id_hash, ab_bucket, consent_version,
                model_version,
                vehicle_id, trim, vehicle_profile_json,
                codes_json, rpm, speed_mph, coolant_temp_f, obd_source,
                prompt_text, response_text, response_parsed_json,
                safety_level, had_error, latency_ms,
                data_sources_json, schema_version
            ) VALUES (
                ?, ?, ?, ?,
                ?,
                ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?
            )
            """,
            (
                datetime.now().isoformat(),
                user_id_hash,
                ab_bucket,
                consent_version,
                model_version,
                vehicle_id,
                trim,
                json.dumps(vehicle_profile) if vehicle_profile is not None else None,
                json.dumps(codes) if codes is not None else None,
                rpm,
                speed_mph,
                coolant_temp_f,
                obd_source,
                prompt_text,
                response_text,
                json.dumps(response_parsed) if response_parsed is not None else None,
                safety_level,
                1 if had_error else 0,
                latency_ms,
                json.dumps(data_sources) if data_sources is not None else None,
                RESEARCH_SCHEMA_VERSION,
            ),
        )
        scan_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return scan_id
    except Exception as e:
        # Swallow everything. Log to stderr, do NOT propagate.
        print(
            f"[log_research_scan] WARNING: failed to log scan: {e!r}",
            file=sys.stderr,
            flush=True,
        )
        try:
            conn.close()
        except Exception:
            pass
        return None


def update_research_rating(
    scan_id: int,
    rating: str,
    comment: Optional[str] = None,
) -> bool:
    """
    Update the user's good/ok/bad rating (and optional comment) for a
    previously-logged scan.

    To be called by the iOS client via a new endpoint (not yet added -
    see the migration doc for the suggested route shape).

    Returns True on success, False on failure. Validates the rating value
    so we don't end up with arbitrary strings in the column.
    """
    valid_ratings = {"good", "ok", "bad"}
    if rating not in valid_ratings:
        print(
            f"[update_research_rating] rejected invalid rating: {rating!r}",
            file=sys.stderr,
            flush=True,
        )
        return False

    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.execute(
            "UPDATE research_scans SET user_rating = ?, user_comment = ? WHERE id = ?",
            (rating, comment, scan_id),
        )
        updated = cursor.rowcount
        conn.commit()
        conn.close()
        # rowcount == 0 means the scan_id didn't exist. Return False so the
        # caller knows the update didn't actually hit anything.
        return updated > 0
    except Exception as e:
        print(
            f"[update_research_rating] WARNING: failed to update rating: {e!r}",
            file=sys.stderr,
            flush=True,
        )
        return False


def get_research_scans(
    limit: int = 100,
    model_version: Optional[str] = None,
    rated_only: bool = False,
) -> list:
    """
    Query recent research scans. Optional filters:
      - model_version: e.g. 'groq-llama-3.1-8b-instant' or 'gemma4-e4b-base'
      - rated_only: only return scans the user has rated

    Returns a list of dicts (one per row), newest first. Returns [] on failure.
    """
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row  # gives us dict-like row access
        query = "SELECT * FROM research_scans WHERE 1=1"
        params: list = []
        if model_version is not None:
            query += " AND model_version = ?"
            params.append(model_version)
        if rated_only:
            query += " AND user_rating IS NOT NULL"
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        cursor = conn.execute(query, params)
        rows = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        print(
            f"[get_research_scans] WARNING: query failed: {e!r}",
            file=sys.stderr,
            flush=True,
        )
        return []

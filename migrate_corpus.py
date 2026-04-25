#!/usr/bin/env python3
"""Idempotent post-process cleanup for training_data/raw/.

Two transformations are applied to every {vehicle_slug}/{code}.json
file under training_data/raw/:

  1. Replace the malformed NHTSA empty-result blob (HTTP 400 quirk)
     with a clean empty-results placeholder.

     The malformed shape is:
         {"error": "HTTPStatusError(... 400 Bad Request ... api.nhtsa.gov ...)",
          "count": 0, "results": []}

     The clean replacement is:
         {"count": 0, "message": "Results returned successfully", "results": []}

     Detection requires ALL of: error key present, error string contains
     "400 Bad Request", error string contains "api.nhtsa.gov", count == 0,
     results == []. A real transient NHTSA failure with a non-400 status
     would NOT match (different error text), so it is left alone for
     visibility.

  2. Strip the obd_codes source key entirely. The OBD-Codes.com scraper
     returned {} on every call due to a Cloudflare browser challenge
     (HTTP 403). The source has been removed from scrape_training_data.py
     in this same revision; this script removes the empty key from
     pre-existing files so the corpus has a consistent schema (no
     obd_codes key anywhere).

Idempotency:
  After a successful clean pass, every NHTSA blob no longer matches the
  detection rule (no "error" key) and no file has an obd_codes key.
  A second run scans every file, finds nothing to change, and reports
  "0 files needed cleaning" without writing anything.

Atomic writes:
  Each modified file is written to {path}.json.tmp and renamed into
  place. An interrupted migration never leaves a half-written file.

Usage:
    py -3 migrate_corpus.py --dry-run   # report only, no writes
    py -3 migrate_corpus.py             # apply changes
"""

import argparse
import json
import sys
from pathlib import Path

DATA_ROOT = Path(__file__).parent / "training_data"
RAW_DIR = DATA_ROOT / "raw"

NHTSA_CLEAN_BLOB = {
    "count": 0,
    "message": "Results returned successfully",
    "results": [],
}

NHTSA_KEYS = ("nhtsa_complaints", "nhtsa_recalls")


def is_malformed_nhtsa(blob) -> bool:
    """Match only the specific HTTP-400-on-empty-results quirk."""
    if not isinstance(blob, dict):
        return False
    err = blob.get("error", "")
    return (
        isinstance(err, str)
        and "400 Bad Request" in err
        and "api.nhtsa.gov" in err
        and blob.get("count") == 0
        and blob.get("results") == []
    )


def transform(record: dict) -> tuple[int, bool]:
    """Mutate `record` in place. Return (n_nhtsa_cleaned, did_strip_obd)."""
    sources = record.get("sources")
    if not isinstance(sources, dict):
        return 0, False

    n_nhtsa_cleaned = 0
    for key in NHTSA_KEYS:
        if is_malformed_nhtsa(sources.get(key)):
            sources[key] = dict(NHTSA_CLEAN_BLOB)
            n_nhtsa_cleaned += 1

    did_strip_obd = "obd_codes" in sources
    if did_strip_obd:
        del sources["obd_codes"]

    return n_nhtsa_cleaned, did_strip_obd


def write_atomic(path: Path, record: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)
    tmp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Idempotent cleanup for training_data/raw/: replace malformed "
            "NHTSA empty-result blobs with clean placeholders, and strip the "
            "obd_codes source key from every file."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without modifying any files.",
    )
    args = parser.parse_args()

    if not RAW_DIR.exists():
        print(f"No raw/ directory at {RAW_DIR} — nothing to migrate.")
        return 0

    files = sorted(RAW_DIR.rglob("*.json"))
    n_scanned = 0
    n_files_modified = 0
    n_nhtsa_total = 0
    n_obd_stripped = 0
    n_read_errors = 0

    for f in files:
        n_scanned += 1
        try:
            with f.open("r", encoding="utf-8") as fh:
                record = json.load(fh)
        except Exception as e:
            print(f"  ERROR reading {f}: {e!r}", file=sys.stderr)
            n_read_errors += 1
            continue

        n_nhtsa_cleaned, did_strip_obd = transform(record)
        if n_nhtsa_cleaned == 0 and not did_strip_obd:
            continue

        n_files_modified += 1
        n_nhtsa_total += n_nhtsa_cleaned
        if did_strip_obd:
            n_obd_stripped += 1

        if not args.dry_run:
            try:
                write_atomic(f, record)
            except Exception as e:
                print(f"  ERROR writing {f}: {e!r}", file=sys.stderr)
                return 2

    prefix = "DRY RUN -- " if args.dry_run else ""
    verb_nhtsa = "Would clean" if args.dry_run else "Cleaned"
    verb_strip = "Would strip" if args.dry_run else "Stripped"

    print(f"{prefix}Scanned {n_scanned} files.")
    print(f"{prefix}{verb_nhtsa} {n_nhtsa_total} NHTSA blobs across {n_files_modified} files.")
    print(f"{prefix}{verb_strip} OBD-Codes from {n_obd_stripped} files.")

    if n_files_modified == 0:
        print(f"{prefix}0 files needed cleaning.")

    if n_read_errors:
        print(f"WARNING: {n_read_errors} file(s) failed to read and were left untouched.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

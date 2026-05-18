#!/usr/bin/env python3
"""Reddit-only backfill for combos where the original scrape stored 0 posts.

Why this exists
---------------
The v2 overnight scraper used a *lean* Reddit wrapper to fit inside the
8h time budget: 3 subreddits (MechanicAdvice + Cartalk + brand-specific)
times the single query variant `"{make} {model} {code}"`. That kept Reddit
fast enough but left ~70% of (vehicle, code) combos with `posts: []`
(measured by `corpus_stats.py`). For most low-volume models, the
make+model+code phrase is too specific to match anything in those subs.

This script re-runs Reddit-only against the **broader** query strategy
that `forum_scraper.scrape_reddit_fallback` defines but the lean wrapper
skipped:

    queries = [
        "{make} {model} {code}",   # variant 1 — already tried by lean wrapper
        "{code} {make}",           # variant 2 — NEW (drops model)
        "{code}",                  # variant 3 — NEW (broadest)
    ]

By default this script runs **only the new variants (2 and 3)** to avoid
re-issuing the same query the lean wrapper already tried. Use
`--include-variant-1` to issue all three (useful only if subreddits are
also expanded — see `--subreddits`).

What gets touched
-----------------
- Walks `training_data/raw/*/*.json`.
- A combo is in scope iff `len(reddit.posts) == 0 AND len(reddit.top_post_comments) == 0`.
- A combo is **skipped** (already backfilled) if the existing reddit blob
  carries a `backfill_at` key.
- Existing source data is NEVER mutated. Only the `reddit` blob is touched,
  and only by *adding* fields. Specifically:
    - new posts are appended to `reddit.posts`
    - new comments are appended to `reddit.top_post_comments`
    - `reddit.backfill_at`, `reddit.backfill_queries`,
      `reddit.backfill_subreddits_tried`, `reddit.backfill_added_posts`,
      and `reddit.backfill_top_post` are added for traceability
- Atomic writes: write to `{path}.tmp` then rename.

Idempotency / resume
--------------------
- A second run sees `backfill_at` and skips the file with no upstream calls.
- A run interrupted mid-combo writes nothing for that combo (the
  in-progress combo is skipped by the next run because it still lacks a
  `backfill_at` key — it'll be retried, which is the correct behavior).

Memoization
-----------
Cross-combo, in-process LRU on `(query, subreddit)`. Variant 3 (just the
code) collapses to ~`50 codes × N subreddits` unique upstream fetches,
not 10,500. Variant 2 collapses to ~`50 codes × ~25 makes × N subreddits`.
This is what makes the run finish overnight.

Runtime estimate
----------------
With defaults (variants 2+3, REPAIR_SUBREDDITS = 4 subs, ~10,500 zero
combos, per-domain cooldown 1.5s):

  - variant 2 unique searches:  ~25 makes × 50 codes × 4 subs       ≈ 5,000
  - variant 3 unique searches:  50 codes × 4 subs                   =   200
  - top-post comment fetches:   one per backfill combo that found
                                any new post; assume ~50% of zero
                                combos pick up a post → ~5,250
  - per-domain cooldown:        1.5s + ~1s internal sleep per call  ≈ 2.5s

  Total upstream calls          ≈ 10,450
  Wall time                     ≈ 10,450 × 2.5s / 3600 ≈ 7.3 hours

(`forum_scraper.search_reddit` and `get_post_comments` carry an internal
`time.sleep(1)` which is BLOCKING; the per-domain cooldown is on top.
Keep that 1.5s cooldown — Reddit's unauth limit is ~60 req/min.)

Use `--max-hours` to bound the run. The script checks the budget before
each combo and exits cleanly so the next run resumes seamlessly.

Usage
-----
    py -3 backfill_reddit.py --dry-run            # report scope, no calls
    py -3 backfill_reddit.py                      # default: ~7h, variants 2+3
    py -3 backfill_reddit.py --max-hours 9
    py -3 backfill_reddit.py --include-variant-1  # also rerun variant 1
"""

import argparse
import asyncio
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from forum_scraper import REPAIR_SUBREDDITS, get_post_comments, search_reddit


# --- Paths and config ------------------------------------------------------

DATA_ROOT = Path(__file__).parent / "training_data"
RAW_DIR = DATA_ROOT / "raw"
LOG_FILE = DATA_ROOT / "backfill_reddit.log"

DEFAULT_MAX_HOURS = 9.0
PER_DOMAIN_COOLDOWN_SECONDS = 1.5
REDDIT_DOMAIN = "www.reddit.com"
SEARCH_LIMIT_PER_QUERY = 5
COMMENT_LIMIT = 5
TOP_COMMENTS_KEPT = 3


# --- Logging ---------------------------------------------------------------

_log_handle = None


def _log_init() -> None:
    global _log_handle
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    _log_handle = LOG_FILE.open("a", encoding="utf-8")


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    if _log_handle is not None:
        _log_handle.write(line + "\n")
        _log_handle.flush()


# --- Per-domain rate limiting ---------------------------------------------

_last_hit: dict[str, float] = {}


async def wait_for_domain(domain: str, min_gap: float = PER_DOMAIN_COOLDOWN_SECONDS) -> None:
    now = time.monotonic()
    elapsed = now - _last_hit.get(domain, 0.0)
    if elapsed < min_gap:
        await asyncio.sleep(min_gap - elapsed)
    _last_hit[domain] = time.monotonic()


# --- Cross-combo memoization ----------------------------------------------

# Key: (query.lower(), subreddit.lower())  -> list[dict] (search results)
_search_cache: dict[tuple[str, str], list[dict]] = {}


async def cached_search(query: str, subreddit: str) -> list[dict]:
    key = (query.lower(), subreddit.lower())
    if key in _search_cache:
        return _search_cache[key]
    await wait_for_domain(REDDIT_DOMAIN)
    try:
        posts = await search_reddit(query, subreddit, limit=SEARCH_LIMIT_PER_QUERY) or []
    except Exception as e:
        log(f"  search error r/{subreddit} {query!r}: {e!r}")
        posts = []
    _search_cache[key] = posts
    return posts


# --- Combo processing -----------------------------------------------------

def is_empty_reddit(blob: dict) -> bool:
    if not isinstance(blob, dict):
        return True
    if "error" in blob:
        return True
    posts = blob.get("posts", []) or []
    comments = blob.get("top_post_comments", []) or []
    return len(posts) == 0 and len(comments) == 0


def build_query_variants(make: str, model: str, code: str, include_v1: bool) -> list[str]:
    variants = []
    if include_v1:
        variants.append(f"{make} {model} {code}")
    variants.append(f"{code} {make}")
    variants.append(code)
    return variants


async def backfill_combo(
    record: dict,
    subreddits: list[str],
    include_v1: bool,
) -> tuple[int, int, dict]:
    """Run the broader Reddit strategy for one combo. Returns (n_new_posts,
    n_new_comments, mutated_record_or_None). The record dict is mutated in
    place if anything was added.
    """
    vehicle = record.get("vehicle", {})
    code = record.get("code", "")
    make = vehicle.get("make", "")
    model = vehicle.get("model", "")

    sources = record.setdefault("sources", {})
    reddit = sources.setdefault("reddit", {})

    queries = build_query_variants(make, model, code, include_v1)

    existing_posts = reddit.get("posts") or []
    existing_urls = {p.get("url") for p in existing_posts if isinstance(p, dict)}

    new_posts: list[dict] = []
    for q in queries:
        for sub in subreddits:
            posts = await cached_search(q, sub)
            for p in posts:
                url = p.get("url")
                if not url or url in existing_urls:
                    continue
                existing_urls.add(url)
                new_posts.append({**p, "_query": q, "_subreddit_searched": sub})

    new_comments: list[str] = []
    new_top_post: dict | None = None
    if new_posts:
        new_top_post = max(new_posts, key=lambda p: p.get("score", 0))
        permalink = (new_top_post.get("url") or "").replace("https://reddit.com", "")
        if permalink:
            await wait_for_domain(REDDIT_DOMAIN)
            try:
                comments = await get_post_comments(permalink, limit=COMMENT_LIMIT) or []
                new_comments = comments[:TOP_COMMENTS_KEPT]
            except Exception as e:
                log(f"  comments error {permalink!r}: {e!r}")
                new_comments = []

    # Always stamp backfill_at so this combo isn't retried next run, even
    # if nothing was found. Add additive fields for traceability.
    reddit["backfill_at"] = datetime.now(timezone.utc).isoformat()
    reddit["backfill_queries"] = queries
    reddit["backfill_subreddits_tried"] = subreddits
    reddit["backfill_added_posts"] = len(new_posts)
    reddit["backfill_top_post"] = new_top_post

    # Merge into the existing fields so summarize_reddit sees the new data.
    if new_posts:
        reddit.setdefault("posts", []).extend(new_posts)
    if new_comments:
        existing_comments = reddit.setdefault("top_post_comments", [])
        for c in new_comments:
            if c not in existing_comments:
                existing_comments.append(c)
        # If the original top_post was null, point it at the new one too.
        if reddit.get("top_post") is None and new_top_post is not None:
            reddit["top_post"] = new_top_post

    return len(new_posts), len(new_comments), record


def write_atomic(path: Path, record: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)
    tmp.replace(path)


# --- Main loop ------------------------------------------------------------

async def run(
    files: list[Path],
    subreddits: list[str],
    include_v1: bool,
    dry_run: bool,
    max_seconds: float,
) -> int:
    started = time.monotonic()
    n_scanned = 0
    n_skipped_existing = 0
    n_skipped_already_backfilled = 0
    n_processed = 0
    n_failed = 0
    n_new_posts_total = 0
    n_new_comments_total = 0

    # Pre-classify so the user sees scope before the run starts.
    in_scope: list[Path] = []
    by_make = defaultdict(int)
    for f in files:
        n_scanned += 1
        try:
            with f.open(encoding="utf-8") as fh:
                rec = json.load(fh)
        except Exception as e:
            log(f"  parse error {f}: {e!r}")
            n_failed += 1
            continue
        reddit = rec.get("sources", {}).get("reddit", {})
        if isinstance(reddit, dict) and "backfill_at" in reddit:
            n_skipped_already_backfilled += 1
            continue
        if not is_empty_reddit(reddit):
            n_skipped_existing += 1
            continue
        in_scope.append(f)
        by_make[rec.get("vehicle", {}).get("make", "?")] += 1

    log(f"Scanned {n_scanned} files.")
    log(f"  in scope (reddit empty, not yet backfilled): {len(in_scope)}")
    log(f"  skipped (reddit already has data):           {n_skipped_existing}")
    log(f"  skipped (already backfilled):                {n_skipped_already_backfilled}")
    log(f"  parse failures:                              {n_failed}")
    log(f"In-scope by make (top 10):")
    for make, n in sorted(by_make.items(), key=lambda kv: -kv[1])[:10]:
        log(f"    {make:18s} {n}")
    log(f"Subreddits: {subreddits}")
    log(f"Variants:   {'1+2+3' if include_v1 else '2+3'}")

    if dry_run:
        log("DRY RUN -- no upstream calls issued, no files modified.")
        return 0

    if not in_scope:
        log("Nothing to backfill.")
        return 0

    # Process each in-scope combo.
    for idx, f in enumerate(in_scope, start=1):
        if (time.monotonic() - started) >= max_seconds:
            log(
                f"Hit --max-hours budget after {n_processed} combos "
                f"({n_new_posts_total} new posts, {n_new_comments_total} new comments). "
                f"Resume with the same command — already-backfilled files will be skipped."
            )
            return 0

        try:
            with f.open(encoding="utf-8") as fh:
                rec = json.load(fh)
        except Exception as e:
            log(f"  parse error mid-run {f}: {e!r}")
            n_failed += 1
            continue

        try:
            n_new, n_cmt, mutated = await backfill_combo(rec, subreddits, include_v1)
        except Exception as e:
            log(f"  combo failed {f}: {e!r}")
            n_failed += 1
            continue

        try:
            write_atomic(f, mutated)
        except Exception as e:
            log(f"  write error {f}: {e!r}")
            n_failed += 1
            continue

        n_processed += 1
        n_new_posts_total += n_new
        n_new_comments_total += n_cmt

        v = rec.get("vehicle", {})
        log(
            f"[{idx}/{len(in_scope)}] {v.get('year','?')} {v.get('make','?')} "
            f"{v.get('model','?')} {rec.get('code','?')} - "
            f"+{n_new} posts, +{n_cmt} comments  "
            f"(cache: {len(_search_cache)} searches memoized)"
        )

    log(
        f"Done. Processed {n_processed} combos. "
        f"Added {n_new_posts_total} posts, {n_new_comments_total} comments. "
        f"Failures: {n_failed}."
    )
    return 0 if n_failed == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Reddit-only backfill for empty (vehicle, code) combos. "
            "Re-runs against the broader query variants from "
            "scrape_reddit_fallback. Idempotent and resumable."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report scope and exit without making any upstream calls.",
    )
    parser.add_argument(
        "--max-hours",
        type=float,
        default=DEFAULT_MAX_HOURS,
        help=f"Wall-clock budget. Default: {DEFAULT_MAX_HOURS}.",
    )
    parser.add_argument(
        "--subreddits",
        type=str,
        default=",".join(REPAIR_SUBREDDITS),
        help=(
            "Comma-separated subreddit list. Default: REPAIR_SUBREDDITS from "
            "forum_scraper (MechanicAdvice, AskMechanics, Cartalk, AutoRepair)."
        ),
    )
    parser.add_argument(
        "--include-variant-1",
        action="store_true",
        help=(
            "Also run the original variant 1 ('{make} {model} {code}'). "
            "By default it's skipped because the lean wrapper already tried it."
        ),
    )
    args = parser.parse_args()

    if not RAW_DIR.exists():
        print(f"No raw/ directory at {RAW_DIR} — nothing to backfill.")
        return 0

    _log_init()

    subreddits = [s.strip() for s in args.subreddits.split(",") if s.strip()]
    if not subreddits:
        log("ERROR: --subreddits resolved to an empty list.")
        return 2

    files = sorted(RAW_DIR.rglob("*.json"))
    log(f"backfill_reddit starting | files={len(files)} | max_hours={args.max_hours}")

    return asyncio.run(
        run(
            files=files,
            subreddits=subreddits,
            include_v1=args.include_variant_1,
            dry_run=args.dry_run,
            max_seconds=args.max_hours * 3600.0,
        )
    )


if __name__ == "__main__":
    sys.exit(main())

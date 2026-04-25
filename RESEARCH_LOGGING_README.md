# Research Logging — Migration Notes

## What this adds

A new SQLite table, `research_scans`, alongside the existing `scans` table.
This new table captures the **full context** of every successful-with-codes
scan: the vehicle profile, the OBD inputs, the complete prompt sent to the
LLM, the complete response received, which model served it, and (later) the
user's good/ok/bad rating.

The existing `scans` table is not modified. The existing `log_scan()`
function is not modified. Nothing that reads from the existing table is
affected.

## Why this matters for the project

Today, every scan logged to the `scans` table only preserves three fields:
the comma-joined codes, the safety level, and the AI response text. That's
enough for operational review — "did my users get reasonable answers
yesterday?" — but it is **not enough** to:

1. **Train a fine-tuned model on real user scans.** Without the prompt
   text, vehicle profile, and sensor readings, a scan cannot be turned
   into a training example.
2. **A/B test between model variants.** Without a `model_version` column,
   there's no way to split responses into "served by base Gemma" vs
   "served by ClearDrive-Gemma" later.
3. **Correlate user satisfaction with response quality.** Without a
   `user_rating` column tied to specific scans, the good/ok/bad feedback
   is floating signal with nothing to attach it to.
4. **Reproduce any individual scan** later for debugging or case studies.
   Without the full prompt, we can't replay what the model saw.

Every scan that happens between today and the day this logging ships is
a scan that can never be used as training data or cited in research. The
lower the cost of adding this, the sooner it should ship.

## What is logged (and what is not)

### Logged today

- Successful scans with DTCs (the main diagnostic flow that calls
  `ask_ollama()` and returns a parsed response).

### Not logged today (intentional, minimum-change approach)

- **Codeless scans.** When a user scans a vehicle with no DTCs, the
  codeless branch at around line 1312 of `main.py` returns without
  calling either `log_scan()` (pre-existing behavior) or
  `log_research_scan()` (this change preserves that). Adding logging
  here is a future change — H4 of the research plan will need it.
- **Error responses.** When the AI returns a string starting with
  `"ERROR:"`, the early-return at line 1603 skips logging. Also a
  future change.
- **Follow-up questions.** The `/followup` endpoint is not touched.
- **Latency.** Would need a `time.time()` call earlier in the function
  to measure end-to-end latency. Skipped for the minimum-change version.

All four of these can be added as separate, small follow-up changes
once the core logging is proven stable in production.

## Schema reference

```
research_scans
├── id                    INTEGER PRIMARY KEY AUTOINCREMENT
├── timestamp             TEXT NOT NULL            (ISO 8601)
│
├── user_id_hash          TEXT DEFAULT 'anonymous'
├── ab_bucket             TEXT
├── consent_version       TEXT DEFAULT 'pre-consent'
│
├── model_version         TEXT DEFAULT 'unknown'
│
├── vehicle_id            TEXT
├── trim                  TEXT
├── vehicle_profile_json  TEXT                     (JSON-encoded dict)
│
├── codes_json            TEXT                     (JSON-encoded list)
├── rpm                   INTEGER
├── speed_mph             INTEGER
├── coolant_temp_f        INTEGER
├── obd_source            TEXT
│
├── prompt_text           TEXT                     ← training data payload
├── response_text         TEXT                     ← training data payload
├── response_parsed_json  TEXT                     (JSON-encoded dict)
│
├── safety_level          TEXT
├── had_error             INTEGER DEFAULT 0        (0 or 1)
├── latency_ms            INTEGER
│
├── user_rating           TEXT                     ('good' | 'ok' | 'bad' | NULL)
├── user_comment          TEXT
│
├── data_sources_json     TEXT                     (JSON-encoded list)
└── schema_version        INTEGER DEFAULT 1
```

## Common queries

### Count scans by model version (A/B analysis)

```sql
SELECT model_version, COUNT(*) as n
FROM research_scans
GROUP BY model_version;
```

### Get all "bad"-rated scans with full context

```sql
SELECT id, timestamp, model_version, vehicle_id, codes_json, user_comment
FROM research_scans
WHERE user_rating = 'bad'
ORDER BY id DESC;
```

### Export scans as training data candidates

```sql
SELECT
    vehicle_profile_json,
    codes_json,
    rpm, speed_mph, coolant_temp_f,
    prompt_text,
    response_text,
    user_rating
FROM research_scans
WHERE had_error = 0
  AND obd_source != 'Demo Mode'
  AND obd_source NOT LIKE 'Demo%'
  AND consent_version != 'pre-consent'
ORDER BY id DESC;
```

Note the three filters: exclude errors, exclude demo-mode scans (they
don't reflect real vehicles), and **exclude pre-consent rows** once the
consent system exists. Until consent ships, this query will return no
rows — which is correct; we shouldn't use pre-consent data for training.

### Recent scans

```sql
SELECT id, timestamp, model_version, safety_level, user_rating
FROM research_scans
ORDER BY id DESC
LIMIT 20;
```

## Disaster recovery

### Disable research logging without code changes

The only hard dependency is the import and the `init_research_table()`
call. If something goes catastrophically wrong and you need to disable
logging fast without redeploying:

```sql
-- Option A: rename the table. log_research_scan() will fail silently
-- (returns None, prints a warning). User-facing flow keeps working.
ALTER TABLE research_scans RENAME TO research_scans_disabled;
```

Or:

```sql
-- Option B: revoke write perms. Same effect.
-- (Not applicable to sqlite without filesystem changes; just a thought.)
```

### Drop research logging entirely

```sql
DROP TABLE research_scans;
DROP INDEX IF EXISTS idx_research_scans_timestamp;
DROP INDEX IF EXISTS idx_research_scans_model;
DROP INDEX IF EXISTS idx_research_scans_rating;
```

Then remove the two new imports and the three call sites. The original
`scans` table and `log_scan()` are untouched throughout, so the app
returns to its pre-research-logging state.

## Pre-consent data policy

Every row logged before the consent flow ships will have
`consent_version = 'pre-consent'`. This is the flag that lets you
distinguish data you can use in research from data you can't.

When the consent flow ships, you have two options:

1. **Keep pre-consent data for internal product development only.**
   Never cite it in the paper, never use it for training. Filter it
   out of any research query via `WHERE consent_version != 'pre-consent'`.

2. **Wipe pre-consent data entirely.**
   ```sql
   DELETE FROM research_scans WHERE consent_version = 'pre-consent';
   ```

Recommendation: option 1 while you're still in pre-launch testing,
option 2 before the WESEF submission to keep the data provenance
story clean.

## What to add later (not in this change)

In rough priority order, the follow-ups that complete the system:

1. **Rating update endpoint.** POST `/scan/{scan_id}/rating` taking
   `{"rating": "good|ok|bad", "comment": "..."}`, calling
   `update_research_rating()`. Plus iOS app wiring so the good/ok/bad
   buttons call it with the scan_id from the last response.
   This requires the `/interpret` response to include `scan_id`, which
   means `log_research_scan()`'s return value (the row id) needs to be
   plumbed into `response_data`. Small change.

2. **Codeless path logging.** Add `log_research_scan()` call at the
   codeless return (~line 1312). Needed for H4.

3. **Error path logging.** Add `log_research_scan(had_error=True, ...)`
   at the error return (~line 1603). Useful for tracking when the model
   fails and why.

4. **Latency measurement.** `start = time.time()` at function entry,
   `latency_ms = int((time.time() - start) * 1000)` at each log call.

5. **Model version auto-detection.** Replace the hard-coded literal
   `"groq-llama-3.1-8b-instant"` with a value read from whichever
   client module is active. Could be as simple as a `MODEL_VERSION`
   constant exported from `groq_client.py` / `ollama_client.py`.

6. **User ID hashing.** Once iOS sends a device-level anonymous ID,
   hash it (SHA-256, keep the first 16 hex chars) and pass as
   `user_id_hash`.

7. **Consent flow + version tag.** Actual onboarding screen in the
   iOS app, with the consent version passed through on every request.

8. **A/B bucket assignment.** Deterministic assignment of users to
   model conditions, passed as `ab_bucket`.

None of these are required for the current change to work. They build
on top of it cleanly.

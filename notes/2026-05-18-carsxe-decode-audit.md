# CarsXE OBD-code decode audit

**Date:** 2026-05-18
**Triggered by:** PR #8 baseline validation — every P0420 response in the 20-scenario eval reasoned about "Secondary Air Injection System Relay 'B' Circuit Malfunction" instead of "Catalyst Efficiency Below Threshold". This file audits whether the bug is isolated to P0420 or systemic.

**No code changes in this audit. Audit and report only.**

---

## Scope adjustment (important)

The task brief asked to sample 5–10 files per code from `training_data/raw/{vehicle}/{code}.json` and extract the natural-language code description. **The corpus JSON files do not store CarsXE-decoded descriptions.** Their schema is:

```
{"vehicle": {...}, "code": "P0420", "fetched_at": "...",
 "sources": {"nhtsa_complaints": {...}, "nhtsa_recalls": {...},
             "repairpal": {...}, "carcomplaints": {...}, "reddit": {...}}}
```

No string field in any sampled corpus file references the wrong CarsXE descriptions (verified by recursive text search for "secondary air injection" / "catalyst" / "air injection"). `scrape_training_data.py` does **not** call `decode_obd_code()` during scraping — confirmed by grep.

So the wrong-decode bug is **NOT contaminating the corpus**. It contaminates:
1. `vehicle_cache.json` (under `obd_codes` key) — 4 codes currently cached with wrong descriptions
2. **Live production responses** via `/interpret` → `decode_obd_codes_batch()` → CarsXE `/obdcodesdecoder` endpoint at `vehicle_data.py:1526`
3. **Any prompt where the model was fed the wrong description** — this affected the PR #8 baseline measurement, so the baseline numbers are evaluating gemma4:e4b against a corrupted prompt for P0420

Audit therefore pivots to: probe the live CarsXE `/obdcodesdecoder` endpoint for each of the 10 sample codes, compare against SAE J2012 canonical definitions, characterize the pattern.

---

## Corpus coverage per code (for reference)

All 10 sample codes are present in the corpus across 300 vehicles each, except `P0506`:

| Code | Corpus files |
|---|---|
| P0011 | 300 |
| P0014 | 300 |
| P0128 | 300 |
| P0171 | 300 |
| P0300 | 300 |
| P0301 | 300 |
| P0420 | 300 |
| P0455 | 300 |
| P0506 | **0** |
| P0700 | 300 |

`P0506` isn't in `TOP_CODES` in `scrape_training_data.py` — minor coverage gap unrelated to this bug.

---

## Methodology

For each of the 10 codes:
1. Look up the current cached CarsXE response in `vehicle_cache.json["obd_codes"]["obd_<CODE>"]` if present.
2. Call `decode_obd_code(code)` for any not cached (uses the CarsXE `/obdcodesdecoder` endpoint at `vehicle_data.py:1526`).
3. Compare against the canonical SAE J2012 definition (manually curated from the published standard).
4. Classify match as: **exact**, **paraphrase**, **wrong-adjacent** (definition of a nearby code), **wrong-unrelated** (definition of an unrelated code), or **API-error**.

CarsXE OBD endpoint URL: `https://api.carsxe.com/obdcodesdecoder?key=<KEY>&code=<CODE>`.

---

## Results

| Code | Canonical (SAE J2012)                                              | CarsXE returned                                                       | Verdict          |
|------|---------------------------------------------------------------------|------------------------------------------------------------------------|------------------|
| P0011 | "A" Camshaft Position Timing Over-Advanced (Bank 1)                | (HTTP 500)                                                             | API-error        |
| P0014 | "B" Camshaft Position Timing Over-Advanced (Bank 1)                | (HTTP 500)                                                             | API-error        |
| P0128 | Coolant Thermostat (Below Regulating Temperature)                  | Insufficient Coolant Temperature for Stable Operation                  | paraphrase (OK)  |
| P0171 | System Too Lean (Bank 1)                                           | Fuel Trim Malfunction (Bank 1)                                         | **wrong-adjacent** — that's P0170's definition |
| P0300 | Random / Multiple Cylinder Misfire Detected                        | Cylinder 12 Contribution/Range Fault                                   | **wrong-unrelated** — cylinder 12 is unrelated to "random misfire" (and not even a standard P0300 alternative) |
| P0301 | Cylinder 1 Misfire Detected                                        | Random/Multiple Cylinder Misfire Detected                              | **wrong-adjacent** — that's P0300's definition |
| P0420 | Catalyst System Efficiency Below Threshold (Bank 1)                | Secondary Air Injection System Relay "B" Circuit Malfunction          | **wrong-unrelated** — likely a P041X-range definition |
| P0455 | Evaporative Emission Control System Leak Detected (Large Leak)     | Evaporative Emission Control System Pressure Sensor Intermittent       | **wrong-unrelated** — same broad system, different code (P0453-ish) |
| P0506 | Idle Air Control System RPM Lower Than Expected                    | Idle Control System Malfunction                                        | paraphrase (OK)  |
| P0700 | Transmission Control System Malfunction                            | Fuel Level Output Circuit Malfunction                                  | **wrong-unrelated** — fuel-level vs transmission, totally different system |

**Summary:** of 10 codes:
- **5 wrong** (P0171, P0300, P0301, P0420, P0455, P0700 — actually 6 — let me recount: P0171, P0300, P0301, P0420, P0455, P0700 = 6 wrong)
- **2 acceptable paraphrases** (P0128, P0506)
- **2 API errors** (P0011, P0014)

**60% wrong-decode rate** on a 10-code sample, 0% exact matches even on the "OK" cases.

---

## Pattern analysis

Three sub-patterns emerge:

### Sub-pattern A: -1 offset (next-lower code's definition)
- `P0171 → P0170's def` ("Fuel Trim Malfunction Bank 1")
- `P0301 → P0300's def` ("Random/Multiple Cylinder Misfire")

Suggests CarsXE's backend has an off-by-one indexing issue on at least some code ranges, or their database row for `P0XXX` was populated with `P0(XXX-1)`'s description.

### Sub-pattern B: cross-range substitution
- `P0420 → "Secondary Air Injection Relay 'B'"` (a P041X-series description, not adjacent)
- `P0455 → "EVAP Pressure Sensor Intermittent"` (likely P0453/P0454 territory)
- `P0700 → "Fuel Level Output Circuit"` (looks like P0461-series — completely different system from transmission)

These aren't off-by-one. They look like CarsXE's database has full-blown rows attached to wrong codes — looks more like a join error or an old database snapshot than a calculation bug.

### Sub-pattern C: nonsense
- `P0300 → "Cylinder 12 Contribution/Range Fault"`. There's no SAE J2012 code that says exactly this; closest is P2300-series (heavy-duty Cummins / diesel). Possibly CarsXE inherited a heavy-duty / J1939 definition row for P0300.

### Sub-pattern D: API instability
- `P0011` and `P0014` return HTTP 500. Could be transient, or could be code-range-dependent. Re-probing might succeed.

---

## Severity estimate

If 6 of 10 sampled codes are wrong (60%), the population of broken codes is large. The TOP_CODES list in `scrape_training_data.py` has ~50 codes — extrapolating, **~30 codes are likely receiving wrong descriptions** in production.

The user-visible impact:
- Every `/interpret` call for an affected code feeds the model a wrong description in the `[VEHICLE-SPECIFIC CODE ANALYSIS]` prompt section.
- The model then writes a 4–6 paragraph response based on the wrong premise.
- TestFlight users have been receiving subtly-incorrect diagnoses; the baseline-validation responses confirm this concretely for P0420.

The corpus is unaffected. But every model trained on this data and then evaluated via the production `/interpret` path is being evaluated against a contaminated prompt.

---

## Recommendation

**Re-source code definitions from SAE J2012 canonical table.** Specifically:
- Build a local Python dict mapping `P0XXX` → canonical description, sourced from the public J2012 reference (or NHTSA's OBD-II canonical table, or even the Wikipedia-published P-code table which is auditable).
- In `vehicle_data.decode_obd_code()`, prefer the local mapping when the code is present; fall back to CarsXE only for unknown / proprietary codes.
- Wipe `vehicle_cache.json["obd_codes"]` after switching, so cached wrong values don't survive.
- The local table is small (~500 codes for the full standard, but the practically-needed subset is ~50–100 codes). It's text, doesn't change, no API dependency.

Do **not** try to fix at the CarsXE layer. The pattern analysis above shows multiple distinct failure modes; CarsXE's database is broken in at least three different ways. Even if they fix it tomorrow, we'd have to re-validate every code. Owning a local canonical table is a one-time investment with a permanent payoff.

Optional: file a bug report with CarsXE. We're not waiting on them.

---

## Follow-up tasks

- [ ] Build `obd_codes_canonical.py` with SAE J2012 P-code dictionary (~50 codes covering TOP_CODES, expand to ~100 if practical).
- [ ] Patch `vehicle_data.decode_obd_code()` to prefer the local mapping.
- [ ] Wipe stale CarsXE entries from `vehicle_cache.json["obd_codes"]`.
- [ ] Re-run PR #8's baseline validation against fixed descriptions. The format-adherence / vehicle-specificity numbers should improve, even on base Gemma 4.
- [ ] Document the CarsXE bug + workaround in `ml/CLAUDE.md` "Never trust CarsXE for code definitions" rule (already added).

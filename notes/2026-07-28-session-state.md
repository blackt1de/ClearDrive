# Session state — 2026-07-28

Branch: `brief-1a-truth-fixes`. Four commits, all pushed. No PR opened yet
(`gh` is not installed on the laptop) — see `pr-body` note at the bottom.

## What landed

| Commit | What |
|---|---|
| `e5f21ec` | Brief 1a — truth fixes: null telemetry, recall instructions deleted, mock scans gated out of `research_scans`, scrapers off the prompt path |
| `7e77a3b` | Payload v2, rule engine, tiered code definitions, retrieval wiring, 9 fixtures, parser fix |
| `40ec2d3` | O2 + unmatched-code rules, cause/status split, check de-duplication, M6 hard case, 16-test suite |
| `a3c6742` | iOS: decode and render the evidence-backed diagnosis, DEBUG scenario picker |

New backend modules: `diagnostics.py`, `dtc_definitions.py`, `fixtures.py`,
`test_diagnostics.py`. Payload v2 lives in `schemas.py`.

## How to run it again

```bash
cd ~/ClearDrive
.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8077   # backend (Ollama via Tailscale)
.venv/bin/python test_diagnostics.py                       # 16 tests, offline, no model
curl -s localhost:8077/demo/scenarios                      # list the 10 fixtures
curl -s -X POST localhost:8077/interpret \
  -H 'Content-Type: application/json' \
  -d '{"scenario":"m6-2014-bank1-lean-misfire-hard"}'
```

The local venv is Python 3.14 and resolved `pydantic` to 2.13.4, because the
pinned 2.9.2 will not build on 3.14. `requirements.txt` is deliberately
unchanged — production pins are load-bearing for deploy.

## Verified this session

All 10 fixtures ran end to end against `gemma4:e4b` on the A4500. 12/12 sections
on every coded scenario except the Accord (11/12, run before the
`ESTIMATED REPAIR COST` parser fix) and the Sonata (10/12, correct — it abstains).
`rav4-2018-clean` reports 4/12 because the no-codes path emits a different,
shorter format by design; that is not a failure.

Two defects found only by running it:
1. `ollama_client.py` SYSTEM_PROMPT rules 5 and 9 instructed the model to invent
   content for any section lacking data — a fourth gap-filling instruction living
   outside `main.py`.
2. `num_ctx` was never set, so Ollama used its 4096 default against a ~4,000-token
   prompt, truncating the response-format instructions out of the window. Sections
   went 1/12 → 11/12 on that change alone.

## Accuracy — read this before quoting any of it

**Diagnostic accuracy is unmeasured. N=0 real vehicles.** The fixtures and the
rules were written by the same author, so a fixture agreeing with a rule proves
only that the code matches the belief that produced it. Nothing here validates
that either matches a real car.

What the sweep *does* establish, because these are properties of the system
rather than claims about vehicles: the model restates the computed differential
instead of inventing alternatives; it abstains when data is missing rather than
guessing; the same code yields opposite conclusions when the underlying readings
differ; manufacturer-specific codes are never given a fabricated meaning.

Measuring accuracy requires real captures paired with **confirmed repair
outcomes**. That is the only ground truth, and the WESEF claims will need it.

## Known weaknesses (my own assessment, not exhaustive)

- Rule thresholds (10% / 25% / 8%) are shop convention I selected, not
  manufacturer specifications. Tagged `heuristic` in output, but still mine.
- Mode 06 misfire counters are present in the M6 fixture and **no rule reads
  them**.
- `P052E` resolves structurally to "vehicle speed control, idle control" — which
  correctly follows the J2012 second-digit convention and still points at the
  wrong subsystem, since the code is crankcase-ventilation related. The
  structural fallback can mislead while being technically honest. Narrow that
  language.
- Bank identification is deferred to the user when engine layout could compute it.
- **Safety level is not computed** — it is the model's judgement from a prose
  rubric, and 8 of 10 scans returned CAUTION regardless of severity. The M6 with
  seven codes and permanent misfires rated the same as one marginal catalyst.
  Strong candidate to move into `diagnostics.py`.
- Five rules against thousands of DTCs.
- `known_issues.json` has no engine field populated and no mileage windows. The
  engine gate exists and is forward-compatible; no record uses it yet.

## Queued, agreed but NOT started

Proposed rule tranche, held at your instruction:
1. **MAF plausibility** (P0101/0102/0103) — expected airflow from displacement
   and RPM vs. measured `maf_rate_gs`. A cross-check, not an invented threshold.
   Also reinforces the lean chain, which is the strongest path already.
2. **Thermostat** (P0128/P0125) — `at_operating_temperature` is already derived.
3. **Coolant sensor plausibility** (P0116–P0118) — coolant vs. IAT on a cold
   start; a sensor reading 200 °F while intake air reads 70 °F is lying.

Plus the two fixes above (`P052E` wording, unused misfire counters).

## Still open elsewhere

- `[OPEN] Canonical Qwen SKU` — worst case is now ~5,100 prompt + 2,800
  `num_predict` ≈ 7,900 tokens, above the ~6,500 the old budget assumed.
- `[OPEN] Scraped content in the training corpus` — must be settled before the
  synthesis run.
- `ml/data/sae_j2012.json` needs re-verification against an actual copy of J2012;
  its 39 manufacturer entries are model-recalled and are currently ignored by
  `dtc_definitions.py`.
- iOS changes are **not compiled** — no macOS available. Expect build errors on
  first run on a Mac.

## PR

Not opened; `gh` is not installed. Body is written and ready at
`/tmp/claude-1000/-home-blacktide-ClearDrive/<session>/scratchpad/pr-body-1a.md`
(session-scoped, so regenerate if lost). Open at:
https://github.com/blackt1de/ClearDrive/pull/new/brief-1a-truth-fixes

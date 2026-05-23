# Baseline validation re-run brief

**Status:** Queued, not run. Wait for the A4500 latency investigation to complete (those changes might also affect numbers; we want one re-run that captures both).

## Why re-run

The original baseline at `notes/baseline-gemma-format-validation-2026-05-18.md` (PR #8) was measured against contaminated prompts:

- Every P0420 scenario fed Gemma 4 E4B the **wrong** code definition (`Secondary Air Injection System Relay "B" Circuit Malfunction` instead of `Catalyst System Efficiency Below Threshold (Bank 1)`). The model dutifully reasoned about the wrong code.
- Independent verification (`notes/2026-05-18-carsxe-independent-verification.md`) found this was systemic: 8 of 10 sampled codes returned wrong descriptions from CarsXE.
- Among the 5 DTCs in the baseline (P0420, P0171, P0300, P0011, P0455), at least **3 were definitively wrong** (P0420, P0171, P0455 all returned −1 offset definitions per the verification).

So the headline numbers (3.5/12 format adherence, 2.4/5 vehicle-specificity, 35% degenerate) are partially measuring the model's response to wrong-code prompts, not the model's behavior on the production prompt path.

## What changed since the original

Landed in PR #10 (`vehicle_data.py`) and PR (this PR, `feat/canonical-codes-expansion`):

- `CANONICAL_OBD_CODES` override in `vehicle_data.py` covers all 50 TOP_CODES + P0506. `decode_obd_code()` returns the SAE J2012 canonical definition for codes in the dict, bypassing CarsXE entirely.
- All 5 DTCs in the baseline test set (P0420, P0171, P0300, P0011, P0455) are now covered by the override.

## Re-run methodology

**Identical** to PR #8 except for the CarsXE fix in the prompt-construction path. No changes to:

- The 5 DTCs: `P0420, P0171, P0300, P0011, P0455`
- The 4 vehicles: `2015 Chevrolet Silverado 1500`, `2018 Honda Civic`, `2020 BMW M5 (substitute for M550i — CarsXE 404s on M550i)`, `2010 Toyota Camry`
- The orchestrator: `scripts/baseline_format_validation.py` (use as-is; no edits)
- The scorer: `scripts/baseline_score_responses.py`
- The capture: spy on `main.ask_ollama` to record both prompt and raw response
- The model: `gemma4:e4b` on the A4500 via `ollama_client.py` (`/api/chat`)

The only difference: the `[VEHICLE-SPECIFIC CODE ANALYSIS]` section of each prompt now contains the correct canonical SAE J2012 definition for each code, instead of CarsXE's wrong text.

## How to run

```bash
# from project root
py -3 scripts/baseline_format_validation.py     # 20 calls, ~12-15 min
py -3 scripts/baseline_score_responses.py       # parses output, fills scores
```

The orchestrator writes to `notes/baseline-gemma-format-validation-<YYYY-MM-DD>.md`. If running on the same UTC date as the original (2026-05-18), it would overwrite — to keep both, **rename the output to `notes/baseline-gemma-format-validation-rerun-<YYYY-MM-DD>.md` immediately after the script finishes** (the path is hard-coded in `baseline_format_validation.write_report()`; either edit it temporarily or rename post-hoc).

## Expected outcome

Two non-overlapping things are being measured:

1. **Did fixing the code descriptions improve format adherence and vehicle-specificity?** If the baseline numbers move from 3.5/12 and 2.4/5 to noticeably higher, that quantifies how much of the original gap was code-description noise vs. genuine model limitation.
2. **Did fixing the code descriptions reduce the degenerate-response rate?** 7/20 degenerated originally; some of those (notably BMW M5 P0011 hallucinating "2024 Model Year Vehicle" and BMW M5 P0455 dropping the code entirely) may have been triggered by the model getting confused by wrong-code prompts.

If both improve substantially → much of the H1+H2 baseline gap is attributable to the upstream pipeline bug, not the model. The fine-tuning case stays unchanged but the magnitude of the lift target shrinks.

If neither moves much → the gap is genuinely the model's limitation. Original PR #8 headline numbers stand. Fine-tuning is even more load-bearing than the (already pessimistic) baseline suggested.

Either result is useful for the WESEF write-up.

## Side-by-side comparison plan

After the re-run, produce a `notes/baseline-comparison-{orig-vs-rerun}.md` with a single side-by-side table per scenario:

| Vehicle / Code | Original (fmt, vs, latency, degen) | Re-run (fmt, vs, latency, degen) | Delta |
|---|---|---|---|

And a single aggregate row. That's the artifact that goes into the WESEF eval-methodology section.

## Cost

- ~20 CarsXE-equivalent lookups (now hitting the local CANONICAL_OBD_CODES dict — $0)
- ~4 CarsXE trim-lookup calls (cached from the original run — $0)
- ~20 Gemma 4 E4B inference calls on the A4500 (already-deployed, no marginal cost)
- ~12-15 minutes wall time

Effectively free. Run whenever the A4500 latency investigation finishes.

## Pre-flight checklist before running

- [ ] A4500 latency investigation merged or paused
- [ ] `vehicle_data.py` has the expanded `CANONICAL_OBD_CODES` (51 entries) — verify with `py -3 -c "from vehicle_data import CANONICAL_OBD_CODES; print(len(CANONICAL_OBD_CODES))"` → should print 51
- [ ] `cleardrive.service` on A4500 has been restarted after pulling the canonical-dict commit, OR the script runs locally where the dict is loaded directly
- [ ] `OLLAMA_HOST` in `.env` points at the A4500 (`100.100.254.15`) — verify with `py -3 -c "from ollama_client import OLLAMA_HOST; print(OLLAMA_HOST)"`
- [ ] No other Reddit/CarComplaints backfill running (avoids rate-limit collisions)

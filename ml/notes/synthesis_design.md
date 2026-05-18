# ETL synthesis design

Stub — will be expanded Wed during ETL design session.

## Approach: hybrid

**Rule-based extraction** for structured fields:
- `SAFETY LEVEL` (lookup table keyed by DTC)
- `ESTIMATED REPAIR COST` (RepairPal data)
- `SERVICE RECOMMENDATIONS` (lookup table by year / make / engine)
- `OTHER OWNERS REPORT` (Reddit data summarized)

**LLM-synthesized via Claude Opus 4.7 (OpenRouter)** for prose fields:
- `WHAT'S HAPPENING`
- `LIKELY CAUSES`
- `WHAT YOU MIGHT NOTICE`
- `IF YOU IGNORE THIS`
- `QUICK CHECKS`
- `DIY FIX`
- `WHEN TO SEE A MECHANIC`
- `KNOWN ISSUES FOR THIS ENGINE`

Opus chosen because it must **not** be one of the five eval condition models (rule-based DTC lookup, base Gemma 4 E4B, Llama 3.1 8B via Groq, base Gemma 4 + DSPy, ClearDrive-Gemma) — eliminates contamination.

## Deduplication

- ~300 per-vehicle summaries (one per vehicle, regardless of DTC)
- ~50 per-DTC explanations (one per DTC, regardless of vehicle)
- Final stitching = ~15,000 training pairs

This is the knowledge-distillation pattern: Opus does heavy synthesis offline, one-time. Inference at runtime is local on ClearDrive-Gemma.

## Cost estimate

~$300–600 in OpenRouter spend, one-time.

## Inference

Local on ClearDrive-Gemma (Gemma 4 E4B fine-tune). Production deploy on A4500.

## Pre-flight items (resolve before synthesis run)

1. **CarsXE wrong-decode bug.** See `../../notes/2026-05-18-carsxe-decode-audit.md` (added in same PR as this stub). Almost certainly need to re-source code definitions from SAE J2012 canonical table — CarsXE's decoded descriptions are not trustworthy for at least P0420.
2. **`get_vehicle_by_id` trim selection.** Picks `trims[0]`, which is the wrong engine for many multi-trim vehicles (e.g., Silverado defaults to 4.3L V6 instead of 5.3L V8). Need a deterministic canonical-trim selector for the ETL pipeline; production needs an iOS UI to confirm trim post-VIN-decode.
3. **CarsXE coverage gaps.** BMW M550i returns 404; likely others. Need fallback to NHTSA vPIC year/make/model search.

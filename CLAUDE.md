# CLAUDE.md

This file is the orientation doc for Claude Code working in this repo. It is loaded automatically at the start of every session. Keep it short, accurate, and focused on what matters for writing code.

## What this is

ClearDrive is a vehicle diagnostic app that reads OBD-II codes from a real car (via a Bluetooth adapter) and produces plain-English, vehicle-specific diagnoses. It exists in two halves:

- A **Python FastAPI backend** that handles VIN decoding, multi-source data enrichment, prompt construction, LLM inference, and response parsing.
- A **native iOS app written in Swift** that connects to the OBD-II adapter, talks to the backend, and renders results.

The medium-term research goal is to replace the current cloud LLM (Groq Llama-3.1-8B-instant) with a small fine-tuned local model (Gemma 4 E4B, fine-tuned via LoRA on a curated diagnostic dataset, optimized via DSPy + GEPA). The fine-tuned model will eventually run on-device.

## Where things live

The repo is the FastAPI backend at the root, plus a sibling `ios/` folder with the Swift app.

### Backend (Python, repo root)

- `main.py` — FastAPI app. Single file, large (~1,775 lines). Contains all routes, the prompt construction logic, response parsing, and the engine/vehicle profiling helpers. The `/interpret` endpoint is the heart of the app.
- `database.py` — SQLite logging. Three tables: `scans` (operational, 5 columns: timestamp, codes, safety, guidance), `followups` (scan-linked Q&A with an `is_human_generated` flag), and `feedback` (scan-linked rating). A `research_scans` table for full prompt/response/context capture is planned but not yet applied — see "What's actively in progress".
- `groq_client.py` — Cloud LLM client (Groq, Llama-3.1-8B-instant). Currently the active inference path. Imported by `main.py` line 15 as `ask_ollama` (legacy name, despite being Groq).
- `ollama_client.py` — Local LLM client. **Stubbed but not wired** — it exists, but `main.py` still imports from `groq_client`. Needs to be the active path once the local Gemma 4 E4B server is online.
- `vehicle_data.py` — VIN decoding, CarsXE API integration, vehicle spec normalization. Large (~2,180 lines).
- `code_scraper.py` — Scrapes OBD-Codes.com, RepairPal, CarComplaints for code-specific diagnostic context.
- `forum_scraper.py` — Scrapes Reddit and other forums for community-reported issues.
- `knowledge.py` — NHTSA API queries plus a small hand-curated `known_issues.json` (~15 vehicles).
- `obd_reader.py` — Threaded OBD-II reader using the python-obd library.
- `schemas.py` — Pydantic request/response schemas.

### iOS (Swift, `ios/ClearDrive/`)

The iOS app is **Swift, not Objective-C**. SwiftUI views in `Views/`, services in `Services/` (APIClient, OBDManager, VehicleStore), models in `Models/`. The app talks to the backend over HTTP.

### Other

- `index.html` + `manifest.json` + `sw.js` — a PWA front-end variant. Not the primary client; the iOS app is.
- `Procfile`, `nixpacks.toml`, `deploy.sh` — deployment artifacts. The backend is designed to be deployable on a Linux server (systemd service via `deploy.sh`) or a PaaS (`Procfile` for Railway/Heroku-style hosts).

## Current state

- iOS app is on TestFlight, distributed to ~50 beta testers (not all activated). App is currently in downtime while the backend transitions off Groq.
- Backend currently uses Groq for inference. The Ollama client exists but is not wired. Migration to local Gemma 4 E4B is pending hardware (3090/A4500 inference server arriving soon).
- A fine-tuning pipeline is planned but not built. The 5090 desktop is the training rig; the inference server is the deployment target.

## Conventions and gotchas

These exist for real reasons. Don't refactor them away without asking.

### Inference

- `main.py` line 15 imports `ask_ollama` from `groq_client`. The name is a legacy artifact from before Groq replaced an earlier Ollama setup. Don't rename it casually — it's used in many places. When the local Ollama server is ready, the swap is a one-line change in the import statement, not a global rename.
- The prompt in `main.py` is **layered and structured**: system instructions → vehicle context → trouble codes → conditional engine-specific sub-prompts (turbo, supercharged, V8, AWD) → output format spec → external scraped data. This architecture matters for the research — the `base Gemma 4 E4B` baseline condition uses this same prompt, so the fine-tuning delta measures something meaningful. Don't rewrite the prompt structure unless explicitly asked.
- Output is parsed into 11 sections (safety_level, dont_panic, whats_happening, symptoms, consequences, quick_checks, diy_fix, mechanic_urgency, cost_estimate, service_recommendations, known_issues). Both the iOS app and the database depend on this format. If you change one section name, you have to update parsers and consumers in lockstep.

### Security

- `vehicle_data.py` has **hardcoded API keys** for CarsXE (line 13) and Auto.dev (line 17). These are live, working keys. They are also already on the public GitHub repo, so they're effectively burned. Rotation + env vars is a planned cleanup; until then, don't commit additional changes that touch those lines without coordinating with the project owner.
- Don't commit `.env` files, `cleardrive.db`, or any file in a `__pycache__/`.

### Process

- Every change goes through git on a branch, never directly on `main`. PR diffs should be small and reviewable.
- Additive changes are strongly preferred over modifying existing behavior, especially anything in the `/interpret` request path. The app is in production beta with real users.
- For complex multi-file changes, write a short markdown spec in repo root (e.g. `MAIN_PY_PATCH.md`, `RESEARCH_LOGGING_README.md`) before implementing. The spec serves as the design doc and the implementation checklist.

## What's actively in progress

- Wiring `ollama_client.py` into `main.py` once the inference server is online.
- Building a `dataset_builder.py` that turns the existing scrapers into a training-data generator for fine-tuning Gemma 4 E4B.
- Locking a held-out evaluation set of ~100-150 (vehicle, code, expected diagnosis) cases for measuring fine-tuning impact.
- Adding a `/scan/{id}/rating` endpoint so the iOS good/ok/bad feedback persists into `research_scans.user_rating`.
- Applying the `research_scans` table + `log_research_scan()` patch (full prompt/response/context capture for training data and A/B analysis). Design constraints when it lands: kept separate from the operational `scans` table (different read patterns, retention, consent implications); `log_research_scan()` swallows all exceptions internally so research logging can never break `/interpret`; pre-consent rows tagged `consent_version='pre-consent'` and excluded from training-data export until a real consent flow ships.

## When in doubt

Ask before making changes that:

1. Touch `/interpret` request handling
2. Modify the response JSON the iOS app receives
3. Change the database schema (any table)
4. Refactor the prompt construction in `main.py`
5. Bring in a new Python dependency

For everything else (new endpoints, new utility functions, new scrapers, internal refactors that preserve external behavior), proceed and show the diff.

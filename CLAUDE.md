# CLAUDE.md — ClearDrive

This file is loaded at the start of every Claude Code session in this repo. It is the source of truth for project-level operational rules. Keep it short. Detailed conventions live in subdirectory CLAUDE.md files (e.g. `ml/CLAUDE.md` when `ml/` exists).

---

## What this is

ClearDrive is a vehicle diagnostic iOS app. It reads OBD-II codes from real cars (via ELM327 Bluetooth) and produces plain-English, vehicle-specific diagnoses through a small language model. The iOS app is in TestFlight beta with real users. The FastAPI backend runs at `https://api.cleardriveapp.com`.

The fine-tuning of Gemma 4 E4B into a domain-specific `ClearDrive-Gemma` is the active research project, targeting WESEF March 2027. Austin Brennan is the lead. Mentor: Nikita Makarov.

---

## Current LLM situation (read this before touching anything LLM-related)

The backend calls **Ollama** for all LLM work. `main.py:14` reads `from ollama_client import ask_ollama, check_ollama`. `ollama_client.py` POSTs to **`/api/chat`** (not `/api/generate` — that endpoint returns empty `response` for chat-trained Gemma 4 in Ollama 0.24). Model: `gemma4:e4b`. Groq has been fully cut — `groq_client.py` is deleted, `GROQ_API_KEY` is no longer used anywhere.

**A4500 endpoint is LIVE** (as of 2026-05-18). Ollama 0.24.0 runs on `ajb1ubuntu` (Ubuntu 24.04, NVIDIA RTX A4500), bound to `0.0.0.0:11434` via systemd override at `/etc/systemd/system/ollama.service.d/override.conf`. Reachable over Tailscale at `100.100.254.15`. Verified end-to-end with a P0420 prompt.

Host is configurable via the `OLLAMA_HOST` env var (defaults to `100.100.254.15` for dev). Accepts `host` or `host:port`. **Production deploy is still blocked on getting the A4500 reachable from the PaaS** — PaaS providers can't reach Tailscale IPs directly. Cloudflare Tunnel (or equivalent) exposing the A4500 on a public hostname is the planned path; tunnel setup is in progress.

---

## Critical rules

### Never

- **Commit API keys.** `CARSXE_API_KEY` and `AUTODEV_API_KEY` are loaded from `os.environ` via `python-dotenv` (see `vehicle_data.py:13,18`). The old cleartext keys still live in git history (PR that rotates + scrubs is pending — `git-filter-repo` follow-up). Real keys go in `.env` (gitignored) locally and in the PaaS dashboard in prod. `.env.example` documents the required names.
- **Modify the LLM output format** without also updating `parse_guidance()` in `main.py`. The format has 12 structured sections (SAFETY LEVEL, WHAT'S HAPPENING, LIKELY CAUSES, WHAT YOU MIGHT NOTICE, IF YOU IGNORE THIS, QUICK CHECKS, DIY FIX, WHEN TO SEE A MECHANIC, ESTIMATED REPAIR COST, SERVICE RECOMMENDATIONS, KNOWN ISSUES FOR THIS ENGINE, OTHER OWNERS REPORT). The iOS app parses these field-by-field; format drift breaks production.
- **Drop or merge `research_scans` into `scans`.** When the `research_scans` table is added (Stream A), it's parallel to the legacy `scans` table by design. `scans` is the production-quality log; `research_scans` is the training-data capture with explicit consent flag. Different audiences, different retention, do not unify.
- **Push directly to `main`.** Feature branch, PR, Austin reviews.
- **Break existing API endpoints.** Real TestFlight users are hitting them. Additive changes only; deprecate before remove.

### Always

- Treat the production backend as live. No breaking changes to endpoints in `main.py`.
- Match the existing prompt-construction pattern when extending the LLM pipeline. The structured output format is what the iOS app expects.
- Use environment variables for secrets. `.env.example` should document required keys (without values).
- When making a load-bearing decision, log it in `notes/decisions.md` (create the file if it doesn't exist).

---

## Repo at a glance

```
/
├── main.py                  FastAPI app · 21 endpoints · ~76 KB
├── ollama_client.py         ONLY LLM client · posts to gemma4:e4b · /api/chat
│                            OLLAMA_HOST env var (default 100.100.254.15 — A4500 over Tailscale)
├── database.py              SQLite · scans + research_scans (parallel tables by design)
├── schemas.py               Pydantic models (minimal)
├── vehicle_data.py          CarsXE + Auto.dev · keys via os.environ (python-dotenv)
├── code_scraper.py          CarComplaints / RepairPal (OBD-Codes was removed in PR #5)
├── forum_scraper.py         Reddit scraper
├── knowledge.py             NHTSA Complaints API + known_issues.json
├── obd_reader.py            python-obd / ELM327 Bluetooth
├── known_issues.json        seed knowledge (15 vehicle entries)
├── scrape_training_data.py  v2 corpus builder (300 vehicles × 50 codes × 5 sources)
├── backfill_reddit.py       Reddit-only re-run with broader query strategy
├── backfill_carcomplaints.py  CarComplaints-only re-fetch for vehicles hit by .title() bug
├── corpus_stats.py          one-shot stats over training_data/raw/
├── GLC300_INVESTIGATION.md  source-coverage diagnostic (April)
├── .env.example             required env vars (no values)
├── ios/                     Swift app · TestFlight beta
├── index.html, sw.js, manifest.json    vestigial PWA, served at /
├── .claude/
│   ├── agents/              5 council subagents (Contrarian / Executor / etc.)
│   └── commands/            /council slash command
├── notes/                   decisions.md and council/decisions/ live here
└── ml/                      PLANNED · created in Stream B · has its own CLAUDE.md
```

When `ml/` exists, its `CLAUDE.md` takes precedence inside `ml/` for fine-tuning operational rules. This root doc covers backend + cross-cutting concerns.

---

## The council

Five strategic-thinking subagents are defined in `.claude/agents/`: Contrarian, Executor, Expansionist, First Principles, Outsider.

Convene the full council via `/council "<question>"` for irreversible decisions, major artifact reviews, or pre-mortems. Do not convene for execution work, bug fixes, or quick clarifications.

Individual personas are invokable directly:

```
Agent(subagent_type="executor", prompt="Gut-check this timeline: ...")
```

Council verdicts are written to `notes/council/decisions/YYYY-MM-DD--<slug>.md`. Austin makes the actual decision after reading the synthesis.

---

## Settled decisions (as of 2026-05-10)

These are committed. Don't relitigate without escalating.

- **Repo layout:** same repo, `ml/` subdirectory for fine-tune work (rather than separate ML repo)
- **Hardware:** training on RTX 5090 desktop (Blackwell, sm_120, 32 GB); inference on RTX A4500 Linux server (Ampere, sm_86, 20 GB)
- **Model:** Gemma 4 E4B (Apache 2.0)
- **Default training method:** QLoRA r=128 — 16-bit LoRA is on the table given 32 GB VRAM, open decision
- **Install path:** Unsloth Studio, not pypi `unsloth` (needs Blackwell kernels and the KV-share bug patches)
- **Attention:** always `attn_implementation="sdpa"` for Gemma 4 (FA2 rejects head_dim > 256 in hybrid global layers)
- **Chat template:** pull from `tokenizer.apply_chat_template()` at runtime — never hand-roll
- **Reflection LM for GEPA:** Claude Opus 4.7 via OpenRouter (must NOT be any of the 5 eval-condition models)
- **Frontend:** iOS is the product. PWA is vestigial but kept as a low-cost browser fallback.
- **Orchestration:** Austin uses Claude web (orchestrator with persistent context) for strategy and Claude Code (this surface, with subagents) for execution. Council convenes for council-worthy decisions only.

Full history will live in `notes/decisions.md` once Stream A creates it.

---

## Workflow expectations

- **Feature branches and PRs.** Don't push to `main`. Austin reviews.
- **Tests:** `test_adapter.py` (OBD adapter) and `test_api.py` (API smoke tests) exist. Run them when touching OBD or API code.
- **Deployment:** PaaS via `nixpacks.toml` + `Procfile`. Don't change the deployment pipeline without Austin's approval.
- **Secrets:** environment variables only. Never `.env` files committed. `.env.example` documents required keys without values.
- **Long context:** when a task is design-heavy (schema changes, methodology decisions), check `notes/decisions.md` first to avoid relitigating. When unsure, ask Austin.

---

## When stuck

1. Check `notes/decisions.md` for prior commitments.
2. Read the relevant existing code — `main.py`'s prompt construction is the canonical source for output format, `database.py` is the canonical source for schema patterns, `ollama_client.py`'s system message is the canonical source for system-prompt expectations.
3. If still ambiguous, ask Austin. Don't guess at design decisions on a research project — the wrong call here is much more expensive than the round trip of a clarifying question.

---

*Maintained at the repo root. Last updated 2026-05-18 (Groq cut, env-var migration, CarComplaints fix, A4500 Ollama live + /api/chat switch + OLLAMA_HOST env var).*

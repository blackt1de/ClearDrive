# CLAUDE.md — ClearDrive

<!-- Maintainer note: loaded in full every session. Target <200 lines.
     RULE FOR EDITING THIS FILE: it describes what EXISTS TODAY. Anything planned goes under
     "Direction" and must be marked as not-yet-built. A CLAUDE.md written in the future tense
     misleads every session. Procedures -> .claude/skills/. Scoped rules -> .claude/rules/.
     HTML comments are stripped before injection, so they cost no context. -->

ClearDrive reads OBD-II data from real cars over ELM327 Bluetooth and produces plain-English, vehicle-specific diagnoses. iOS client + FastAPI backend + a locally served LLM.

Also a research project: does a domain-fine-tuned LM beat rule-based DTC lookup on accuracy and comprehension. WESEF March 2027. Lead: Austin Brennan. Mentor: Nikita Makarov.

## The one idea that governs every change

**The model reasons. Everything else remembers.**

Facts about a vehicle — recalls, TSBs, known failure patterns, code definitions — come from retrieval or from a data file with a `source` field. The model connects evidence to conclusions. It never supplies a vehicle fact from its own weights. A confidently wrong "known issue" is worse than a generic answer.

This is the target behavior, not current behavior. Today `/interpret` still asks the model to recall TSBs from memory. Fixing that is the first queued change.

## What actually runs today

| Piece | State |
|---|---|
| Inference | **Ollama**, `gemma4:e4b`, via `ollama_client.py`. Not fine-tuned — base model. |
| Backend | FastAPI `main.py` on the A4500 (`ajb1ubuntu`, Ubuntu 24.04, RTX A4500) |
| Services | `ollama.service` :11434 · `cleardrive.service` :8000 · `cloudflared.service` |
| Ingress | Cloudflare Tunnel → `api.cleardriveapp.com`. Dev: `100.100.254.15:8000` over Tailscale. |
| iOS | SwiftUI client, `ios/ClearDrive/`. TestFlight currently dormant. |
| Output format | 12 string-parsed sections via `parse_guidance()` |

`OLLAMA_HOST` accepts a bare hostname or `host:port`; defaults to `100.100.254.15`.

## Direction — decided, not yet built

- **Target model family: Qwen MoE. Exact SKU is OPEN** — see `[DECIDED] Pivot to Qwen MoE — 2026-07-27` and `[OPEN] Canonical Qwen SKU` in `notes/decisions.md`. It supersedes the 2026-05-23 Gemma 4 26B-A4B lock on model family only. Constraints, all measured: **Qwen3-30B-A3B is ruled out** — 1.93 GB headroom against the measured ~6,500-token demand, below the 2 GB target (`notes/2026-05-23-production-context-size.md`). VRAM is set by **total** params, not active, so the SKU must be under 30B total. A **typical-case** context budget exists (~6,500 tokens = ~2,000–2,500 input + `num_predict=4000`), measured over 2 vehicles both P0420; **no worst-case budget exists**, and payload v2 + retrieval will push demand above 6,500. Do not pin a SKU by estimate.
- Serving moves from Ollama to SGLang.
- Output moves from string-parsed sections to a validated JSON contract.
- Retrieval (NHTSA + platform KB) replaces model-recalled vehicle facts.

None of the above is implemented. Do not write code that assumes it is.

## Never

1. Send any UDS service other than `0x19`, `10 03`, `3E 80`. Standard OBD modes 01/02/03/06/07/09/0A and AT/ST adapter commands are fine. Full rules: `.claude/rules/obd-safety.md` (loads when you touch OBD code).
2. Substitute a default for a missing measurement. Missing is `null`, rendered as `unavailable`.
3. Change the LLM output format without updating `parse_guidance()` in `main.py` — iOS parses those 12 sections field by field and will break silently.
4. Write `research_scans` rows into `scans` or vice versa. Parallel tables by design, different audiences.
5. Break an existing API endpoint without a migration path. Old iOS builds hit them.
6. Invent manufacturer PIDs, module addresses, or scaling formulas. These come only from versioned files with `source` and `verified_by`.
7. **Put scraped content in a prompt.** Per-request live scraping makes prompt content depend on what a website said that day, so a baseline is not reproducible and eval arms are not comparable across time. Reddit is deleted from `/interpret`; OBD-Codes / CarComplaints / RepairPal are gated OFF behind `ENABLE_SCRAPED_CODE_CONTEXT` (default `0`) and get deleted when their sourced replacements land (SAE J2012 + manufacturer definitions; NHTSA + platform KB). Do not add scrapers or new scraped sources. **The corpus half of this rule is OPEN** — see `[OPEN] Scraped content in the training corpus` in `notes/decisions.md`. `training_data/raw/` is built from scraped sources and `ml/CLAUDE.md` marks it read-only source of truth; extending the ban to the corpus invalidates it and the ETL design. Decide before the synthesis run.
8. Hardcode secrets, IPs, or hostnames. Use `os.environ`.
9. `git push --force`, or amend a pushed commit.

## Always

1. Verify a line anchor before editing — quote the string, don't trust the number.
2. When a spec's precondition doesn't match real code: **stop and report with the actual code quoted.** Do not improvise a substitute design.
3. Keep diffs scoped to the current task. No opportunistic refactors.
4. New data files carry `source`, `verified_by`, `verified_at`.
5. Run `test_adapter.py` when touching OBD code.
6. Append a `notes/decisions.md` entry after any decision-bearing change. Supersede prior entries; never delete them.

## Commands

```bash
uvicorn main:app --reload     # backend, local
pytest test_api.py            # API tests
python test_adapter.py        # OBD adapter tests
```

Deploy: `cd /home/abrennan/cleardrive && git pull && sudo systemctl restart cleardrive`

## Repo notes

- `ml/` exists — training code, configs, notes. See `ml/CLAUDE.md`.
- `nixpacks.toml` and `Procfile` are vestiges of a prior PaaS deploy. Not load-bearing; leave alone.
- `knowledge.py` contains working NHTSA and local-KB retrieval that **is never called** from `/interpret`. Wiring it in is queued work, not a bug to fix opportunistically.

## Work model

Work arrives as numbered execution briefs, pasted per session. One brief = one session = one branch = one PR. Invoke the `brief-executor` skill when starting one.

## Research integrity

Anything touching `ml/` or scoring scripts affects published results. Held-out splits are by platform, not by example. Training input format must stay byte-identical to the production prompt assembler.

## Where things live

- `notes/decisions.md` — the decision log
- `.claude/rules/` — path-scoped, load only when touching matching files
- `.claude/skills/` — procedures, loaded on demand
- `.claude/agents/` — five-instance strategic council (`/council`)

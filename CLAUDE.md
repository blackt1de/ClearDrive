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

- **Target model: a Qwen MoE (~4B active).** Exact SKU still open. Note: `decisions.md` previously rejected Qwen3-30B-A3B on VRAM headroom (0.13 GB at 2048 ctx on 20 GB) and selected Gemma 4 26B-A4B; that decision has been superseded in favor of Qwen for training-ecosystem reasons, but **the VRAM constraint has not been re-measured.** Do not treat any SKU as pinned until a measured context budget exists.
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
7. Add scrapers or new scraped sources.
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

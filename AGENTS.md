# AGENTS.md - ClearDrive

This file is loaded at the start of every Codex session in this repo. It is the source of truth for project-level operational rules. Keep it short. Detailed conventions live in subdirectory `AGENTS.md` files, especially `ml/AGENTS.md`.

---

## What This Is

ClearDrive is both:

- A vehicle OBD-II diagnostic product: an iOS app reads DTCs and vehicle context, then returns a plain-language diagnosis.
- A WESEF/ISEF research project: the app, backend, corpus, fine-tune, deployment, and evaluation are the research artifact.

Lead: Austin Brennan. Mentor: Nikita Makarov. Target: WESEF March 2027, with ISEF possible after.

The current research direction is **ClearDrive-Qwen**: a Qwen MoE model fine-tuned on the ClearDrive diagnostic corpus, trained on the RTX 5090 desktop and served from the RTX A4500 server.

---

## Current Truth - 2026-05-30

The v0.2 project prospect from Claude web supersedes the older Gemma/Ollama/on-device plan.

### Live Today

- iOS app exists and has been in TestFlight beta.
- FastAPI backend is reachable at `https://api.cleardriveapp.com` through Cloudflare Tunnel.
- Current production inference path may still be the old stack: Llama 3.1 8B via Groq.
- The fine-tuned ClearDrive model is **not** in production yet.
- The locally deployed model claim is a target state, not current fact.

Before infra or backend work, verify live state directly. Do not assume the local code, old notes, or old service docs describe reality.

### Target State

- iOS app is a thin client.
- FastAPI backend calls an OpenAI-compatible SGLang endpoint.
- A4500 serves ClearDrive-Qwen via SGLang + NEXTN speculative decoding if supported for the pinned model.
- 5090 Windows desktop does development and QLoRA training.
- On-device iPhone inference is dead as the primary path. Whether an offline demo survives is an open decision.

### Superseded

- Gemma 4 E4B as the fine-tune target.
- ClearDrive-Gemma naming.
- Ollama as the target serving stack.
- On-device iPhone deployment as the primary research/product claim.
- Single-executor build model.

---

## Deployment Topology

| Machine | Role | Notes |
|---|---|---|
| RTX 5090 desktop | Development + training | Blackwell, sm_120, 32 GB. Runs Codex/Claude, gates, corpus work, QLoRA. Prefer WSL2 with repo on Linux filesystem if native Windows tooling becomes flaky. |
| RTX A4500 server (`ajb1ubuntu`) | Inference only | Ampere, sm_86, 20 GB. Target serving stack: SGLang + ClearDrive-Qwen. |
| iPhone | Thin client | Runs the app, not the model. |

Public ingress remains via Cloudflare Tunnel: `api.cleardriveapp.com` -> FastAPI.

Open infra decisions:

- Pin the canonical Qwen model SKU before any config or chat-template work.
- Confirm SGLang + NEXTN support and memory fit for that exact model.
- Confirm whether Together.ai is fully dropped or kept as a fallback.

---

## Current LLM Direction

The target runtime path is:

`iOS app -> FastAPI -> OpenAI-compatible client -> SGLang -> ClearDrive-Qwen on A4500`

The backend should move away from `ollama_client.py` toward an OpenAI-compatible SGLang client. Mirror the old `groq_client.py` pattern if useful, but do not resurrect Groq as the research target.

Contamination guardrail:

- GPT/Codex writes code only.
- Synthesis LM for training-pair generation: Claude Opus 4.7 via OpenRouter.
- Reflection/judge LM for GEPA/eval: Claude Opus 4.7 via OpenRouter.
- None of the 5 eval-condition models may be used for synthesis or judging.

---

## Critical Rules

### Never

- Commit API keys or `.env` files.
- Modify the 12-section LLM output format without also updating `parse_guidance()` in `main.py`.
- Drop or merge `research_scans` into `scans`.
- Push directly to `main`.
- Break existing API endpoints.
- Edit `training_data/raw/`; it is read-only source evidence.
- Use any eval-condition model as a synthesis or judge LM.
- Hand-roll chat templates. Always use `tokenizer.apply_chat_template()`.

### Always

- Treat production as live until proven otherwise.
- Use environment variables for secrets.
- Check `notes/decisions.md` before relitigating settled decisions.
- Log new load-bearing decisions in `notes/decisions.md`.
- Run the 5% / 200-step QLoRA pilot before any full training run.
- Freeze train/val/test splits with a manifest and vehicle-level holdouts.
- Run `scripts/blackwell_check.py` before any 5090 training operation.
- Trust SAE J2012 canonical DTC definitions over CarsXE when code descriptions conflict.

---

## Repo At A Glance

```text
/
├── main.py                         FastAPI app
├── ollama_client.py                legacy/current code path; target is replacement with SGLang client
├── database.py                     SQLite; scans + research_scans pattern
├── vehicle_data.py                 CarsXE + Auto.dev; keys via environment
├── code_scraper.py                 CarComplaints / RepairPal
├── forum_scraper.py                Reddit scraper
├── scrape_training_data.py         v2 corpus builder
├── backfill_reddit.py              Reddit backfill
├── backfill_carcomplaints.py       CarComplaints re-fetch after casing bug
├── corpus_stats.py                 stats over training_data/raw/
├── GLC300_INVESTIGATION.md         source-coverage diagnostic
├── ios/                            Swift app
├── ml/                             fine-tuning, eval, and deployment artifacts
├── .codex/agents/                  Codex council subagents
├── .claude/agents/                 Claude council subagents
├── .claude/commands/council.md     Claude /council command
└── notes/                          decisions, council verdicts, collaboration blackboard
```

---

## The Council

Five strategic-thinking personas exist for major decisions: Contrarian, Executor, Expansionist, First Principles, Outsider.

- Codex personas live in `.codex/agents/`.
- Claude personas live in `.claude/agents/`.
- Claude slash command lives in `.claude/commands/council.md`.
- Verdicts go to `notes/council/decisions/YYYY-MM-DD--<slug>.md`.

Use the council for irreversible decisions, major artifact reviews, and pre-mortems. Do not convene it for routine execution or bug fixes.

---

## AI Collaboration Blackboard

When Codex and Claude Code are both open, coordinate through `notes/ai-collab/`.

- Read `notes/ai-collab/current-state.md`, `notes/ai-collab/task-board.md`, and your inbound handoff file before coordinated work.
- Codex writes requests for Claude in `notes/ai-collab/codex-to-claude.md`.
- Claude writes requests for Codex in `notes/ai-collab/claude-to-codex.md`.
- Append notable actions and handoffs to `notes/ai-collab/session-log.md`.
- Keep settled decisions in `notes/decisions.md`; the blackboard is coordination, not the decision log.
- One owner per task. Do not let both assistants edit the same code path at once.

---

## Settled Direction As Of 2026-05-30

- Same repo; `ml/` is the ML work area.
- iOS remains the product. PWA is a vestigial fallback.
- Target model family is Qwen MoE, exact SKU still **[DECIDE]**.
- Fine-tuned model name: ClearDrive-Qwen.
- Target serving stack: SGLang, not Ollama.
- Backend target: OpenAI-compatible SGLang client.
- Training: QLoRA on RTX 5090 via Unsloth Studio.
- Inference: A4500 server.
- GEPA remains assumed unless Austin/Makarov decide GRPO.
- Opus 4.7 via OpenRouter is the synthesis/reflection/judge LM, not GPT/Codex and not an eval-condition model.

Open decisions are listed in `notes/2026-05-30-cleardrive-state-change-plan-v0.2.md` and the latest entry of `notes/decisions.md`.

---

## Workflow Expectations

- Feature branches and PRs. Austin reviews.
- Run relevant tests when touching API or OBD code.
- Use the blackboard for Codex/Claude handoffs.
- For design-heavy tasks, check `notes/decisions.md` first.
- If a task requires choosing among open research decisions, ask Austin instead of guessing.

---

## When Stuck

1. Check `notes/decisions.md`.
2. Check `notes/2026-05-30-cleardrive-state-change-plan-v0.2.md`.
3. Check council verdicts in `notes/council/decisions/`.
4. Read the relevant code.
5. Ask Austin.

---

Maintained at the repo root. Last updated 2026-05-30 for the Qwen/SGLang/dual-model pivot.

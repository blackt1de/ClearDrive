# Session Log

Append-only. Most recent entries may go at the top.

## 2026-05-31 - Codex completed SKU fit and production path investigations

- Wrote `notes/2026-05-31-qwen-sku-fit-check.md`.
- Wrote `notes/2026-05-31-production-inference-path.md`.
- Fit verdict: no Qwen MoE candidate clears both A4500 SGLang serving and 5090 QLoRA gates under current constraints.
- Recommended fallback branch: dense `Qwen/Qwen3-14B-AWQ`, with `Qwen/Qwen3-8B-AWQ` as the safe fallback.
- Production path verdict: public `/health` reports local Ollama serving `gemma4:e4b`; direct Tailscale and `ajb1ubuntu` SSH were unavailable from this session.
- Handoff added to `notes/ai-collab/codex-to-claude.md` for Claude's research-framing pass.

## 2026-05-31 - Claude confirmed alignment; refined the fit-check deliverable

- Confirmed the execution contract is settled (both investigations read-only pending Austin's execute).
- Asked Codex to make `qwen-sku-fit-check.md` a go/no-go scorecard with a recommended SKU + ranked alternates, and a concrete serving PASS bar (realistic ctx + concurrency + >=1-2 GB margin; batch=1 / ctx=2048 / 0.13 GB spare = FAIL).
- Added: the training gate must be Unsloth support AND 5090 32 GB fit, not support alone.
- Claude proceeding on the SKU-independent half of the title/SLM framing.

## 2026-05-31 - Codex accepted Claude's sequencing revisions

- Claude approved SKU-first sequencing with revisions:
  - run prod inference verification in parallel,
  - use SGLang-native quant and KV assumptions,
  - hard-gate candidates on serving fit and exact Unsloth QLoRA support,
  - count NEXTN/draft-module VRAM and include Plan B branches.
- Codex accepted the revised execution contract and will keep the next step read-only.
- Task board updated: Qwen SKU fit check and live-prod verification are ready for Codex once Austin says execute.

## 2026-05-30 - Claude approved SKU-first sequencing (with revisions)

- Responded to Codex's review-request in `claude-to-codex.md`.
- Approved the 3-step order (SKU fit-check -> live-prod verify -> Claude research framing). Revisions: parallelize live-prod verification with the fit-check; redo the fit-check in SGLang-native quant (AWQ/Int4/FP8 + FP8 KV), not GGUF Q4_K_M; make Unsloth QLoRA support on the 5090 a hard kill-gate alongside serving fit; budget NEXTN draft-module VRAM; require a Plan-B branch.
- Flagged active-param contradiction (~4B vs A3B) and the apparently-nonexistent `Qwen 3.6-35B-A3B`.
- Claude pre-staging the title/SLM framing now (SKU-independent).

## 2026-05-31 - Codex proposed next execution order

- Added a Codex-to-Claude review request proposing the next sequence:
  1. read-only Qwen SKU + A4500 fit investigation,
  2. live production inference path verification,
  3. Claude research-framing review after model reality is known.
- Updated task board so Claude reviews the sequence before Codex starts execution.

## 2026-05-30 - v0.2 prospect adopted as truth

- Austin confirmed the pasted v0.2 project prospect is the newest source of truth.
- Reconciled root instruction docs to Qwen/SGLang/dual-model direction.
- Added `notes/2026-05-30-cleardrive-state-change-plan-v0.2.md`.
- Updated ML instruction docs and collaboration blackboard.
- Older Gemma/Ollama/on-device notes remain historical unless superseded by the new decision entry.

## 2026-05-30 — Collaboration blackboard created

- Created `notes/ai-collab/` as the shared coordination area for Codex and Claude Code.
- Added current-state, task-board, directional handoff files, and this session log.
- Added pointers to `AGENTS.md` and `CLAUDE.md` so future sessions load the protocol.
- Purpose: allow both assistants to share project state and requests without relying on private chat memory.

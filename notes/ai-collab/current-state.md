# Current State

Last updated: 2026-05-30

## Source Of Truth

The current truth is the v0.2 project prospect captured in `notes/2026-05-30-cleardrive-state-change-plan-v0.2.md`. It supersedes older Gemma/Ollama/on-device assumptions.

## Product / Research Identity

ClearDrive is both a vehicle-diagnostics iOS app and the full WESEF/ISEF research project around building, fine-tuning, deploying, and evaluating a domain-specific diagnostic language model.

## Live System

- Product target: iOS app. It is now framed as a thin client.
- Public API: `https://api.cleardriveapp.com` through Cloudflare Tunnel.
- Current production inference may still be the old Groq/Llama 3.1 8B path.
- The fine-tuned ClearDrive model is not yet in production.
- Verify live services before infra work; do not assume old Ollama/Gemma notes are current.

## Target System

- Model family: Qwen MoE, exact SKU still **[DECIDE]**.
- Fine-tuned model name: ClearDrive-Qwen.
- Training: RTX 5090 desktop, QLoRA, Unsloth Studio.
- Serving: RTX A4500 server, SGLang, NEXTN if supported for the pinned Qwen model.
- Backend target: OpenAI-compatible client to SGLang.
- iPhone: thin client, not on-device inference.

## Research State

- Target: WESEF March 2027.
- Lead: Austin Brennan.
- Mentor: Nikita Makarov.
- Fine-tune work lives under `ml/`.
- Settled decisions live in `notes/decisions.md`.
- Council verdicts live in `notes/council/decisions/`.

## Corpus State

- Raw corpus location: `training_data/raw/`.
- Prior inventory: 300 vehicles x 50 P-codes = 15,000 JSON files, about 5.3 GB.
- State: raw scraped data, not normalized documents and not training pairs.
- v0.2 prospect says Reddit backfill is complete; verify from logs before relying on it.
- Current forward plan: curate about 15K raw combos to about 3K high-quality training candidates before Opus synthesis.

## Open Decisions

- Canonical Qwen SKU.
- Qwen attention setting.
- GEPA vs GRPO.
- H3 sample size.
- H4 codeless threshold.
- Together.ai dropped vs fallback-only.
- On-device offline demo dead vs retained for WESEF demo.
- Research title framing around SLM vs MoE active-parameter language.

## Coordination Rule

Use this folder for assistant-to-assistant coordination only. Use `notes/decisions.md` for actual decisions.


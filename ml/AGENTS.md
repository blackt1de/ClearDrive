# ml/AGENTS.md

Inherits from root `AGENTS.md`. Scoped to `ml/`: corpus prep, training data synthesis, fine-tuning, eval, and deployment artifacts.

The current ML direction is **ClearDrive-Qwen**, not ClearDrive-Gemma. Exact Qwen SKU is still **[DECIDE]**.

## Critical Rules

### Never

- Edit `../training_data/raw/`; it is read-only source evidence.
- Use any of the 5 eval-condition models for synthesis or as a reflection/judge LM.
- Skip the 5% / 200-step QLoRA pilot before a full run.
- Skip contamination checks before freezing splits.
- Hand-roll the Qwen chat template. Always use `tokenizer.apply_chat_template()` through the project helper.
- Trust CarsXE's OBD code descriptions when SAE J2012 canonical definitions disagree.

### Always

- Synthesis LM and reflection/judge LM: **Claude Opus 4.7 via OpenRouter**.
- Vehicle-level holdouts for train/val/test splits.
- Freeze splits with a manifest in `data/splits/` including file hashes and row counts.
- Run `scripts/blackwell_check.py` before any 5090 training operation.
- Log training runs to W&B. Project target: `cleardrive-qwen`.
- Check `../notes/decisions.md` before relitigating a settled decision.
- Check `../notes/2026-05-30-cleardrive-state-change-plan-v0.2.md` for the current pivot plan.

## Eval Conditions

1. Rule-based DTC lookup.
2. Base Qwen.
3. Llama 3.1 8B cross-family baseline.
4. Qwen + DSPy prompt optimization, no fine-tune.
5. ClearDrive-Qwen, fine-tuned + DSPy/GEPA.

None of these may be used for synthesis or judging.

## Open ML Decisions

- Canonical Qwen SKU.
- Correct Qwen attention setting.
- GEPA vs GRPO.
- H3 sample size.
- H4 codeless threshold.
- Whether any on-device offline demo survives as narrative/demo only.

## When Stuck

1. Check `../notes/decisions.md`.
2. Check `../notes/2026-05-30-cleardrive-state-change-plan-v0.2.md`.
3. Check council sessions at `../notes/council/decisions/`.
4. Ask Austin.


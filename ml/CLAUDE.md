# ml/CLAUDE.md

Inherits from root `CLAUDE.md`. Scoped to `ml/` — corpus prep, training data synthesis, fine-tuning, eval, deployment artifacts.

## Critical rules

### Never

- **Edit `../training_data/raw/`.** Read-only. 5.3 GB corpus is source of truth.
- **Use any of the 5 eval condition models for synthesis or as a reflection LM.** Contamination risk. The 5: rule-based DTC lookup, base Gemma 4 E4B, Llama 3.1 8B (Groq), base Gemma 4 + DSPy, ClearDrive-Gemma.
- **Skip the QLoRA pilot.** Always run 5% data + 200 steps minimum before any full run.
- **Skip the contamination check** before splits are frozen.
- **Hand-roll the Gemma 4 chat template.** Always `tokenizer.apply_chat_template()` — go through `src/chat_template.py`.
- **Trust CarsXE's OBD code descriptions** (known wrong for P0420; audit pending). Use SAE J2012 canonical definitions as source of truth for code semantics.

### Always

- Synthesis LM and reflection LM = **Claude Opus 4.7 via OpenRouter**. No exceptions.
- `attn_implementation="sdpa"` when loading Gemma 4. FA2 rejects `head_dim > 256`.
- Run `scripts/blackwell_check.py` before any 5090 training operation.
- **Vehicle-level holdouts** for splits.
- Freeze splits with manifest in `data/splits/` (file hashes, row counts).
- Log training runs to W&B. Project: `cleardrive-gemma`.
- Check `../notes/decisions.md` before relitigating a settled decision.
- Long-running operations background-friendly with job IDs.

## When stuck

1. Check `../notes/decisions.md` for prior commitments
2. Check council sessions at `../notes/council/decisions/` for context
3. `src/chat_template.py` is the contract — formats flow from it
4. Ask Austin

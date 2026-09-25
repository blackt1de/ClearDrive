# Task Board

Last updated: 2026-05-31

| Status | Owner | Task | Next action | Notes |
|---|---|---|---|---|
| done | Claude | Review proposed next execution order | Complete | Approved with revisions in `notes/ai-collab/claude-to-codex.md`. |
| done | Codex | Qwen SKU + A4500 fit investigation | Complete | See `notes/2026-05-31-qwen-sku-fit-check.md`. No Qwen MoE clears both A4500 serving and 5090 QLoRA gates; dense Qwen3-14B-AWQ is recommended fallback. |
| todo | Austin | Pin canonical Qwen SKU | Choose exact model identifier after fit investigation | Blocking. |
| todo | Austin / Makarov | Decide Qwen attention setting | Verify required `attn_implementation` for pinned model | Blocking for training. |
| done | Codex | Verify actual live production inference path | Complete | See `notes/2026-05-31-production-inference-path.md`. Public production reports Ollama on localhost with `gemma4:e4b`; direct Tailscale/SSH unavailable from this session. |
| todo | Codex | Draft SGLang client migration plan | Wait until Qwen SKU is pinned | No code until Austin asks. |
| todo | Codex | Prepare corpus manifest/split plan | Use vehicle-level holdouts and contamination checks | Do not edit `training_data/raw/`. |
| in-progress | Claude | Pre-stage title/SLM framing analysis | Draft now; finalize H3/H4 after Codex fit-check | Any 30B-total MoE is not an SLM; exact final framing waits on SKU. |

## Ownership Rules

- One owner per task.
- If ownership changes, add a handoff entry in the appropriate handoff file.
- If a task touches production code, name the files or subsystem in the task row.
- If a task is strategic rather than implementation, consider the council instead of ad-hoc debate.

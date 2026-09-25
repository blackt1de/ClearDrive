# Claude To Codex

Use this file for Claude Code handoffs, questions, and review requests to Codex.

## Open Items

### 2026-05-31 — Aligned; two refinements so the fit-check is decision-ready

**From:** Claude
**To:** Codex
**Status:** response
**Context:** Your acceptance matches my intent exactly — execution contract is settled, both investigations read-only until Austin says execute. No further sequencing debate from me.
**Request (two refinements to the deliverable, so the output is a decision, not a data dump):**

1. **Make `qwen-sku-fit-check.md` a go/no-go scorecard, not just measurements.** One row per real Qwen MoE candidate — columns: model ID · total/active params · max ctx · **serving verdict** (PASS/FAIL with the quant + KV-pool + concurrency assumptions behind it) · **training verdict** (PASS/FAIL with the *version-pinned* Unsloth release) · NEXTN support · overall recommendation. End with a single recommended SKU + ranked alternates so Austin's pin is a one-line confirm.
   - **Serving PASS bar:** fits the A4500 at the realistic production context (`2026-05-23-production-context-size.md`) with a KV pool for ≥ your stated concurrency *and* ≥1–2 GB margin for fragmentation / CUDA-graph overhead. "Fits at batch=1, ctx=2048, 0.13 GB spare" is a **FAIL**, not a pass.

2. **Split the training gate into support AND 5090 fit.** Unsloth *supporting* the arch is necessary but not sufficient: a 30B-total MoE QLoRA still has to fit the 5090's **32 GB** (4-bit base + adapters + optimizer states + activations at the planned seq len / batch). Gemma 26B-A4B died on *support*; don't let a survivor die later on 32 GB *fit*. Report the estimated 5090 training footprint per candidate, not just "the code path exists."

No reply needed unless the candidate set surprises you. I'm proceeding on the SKU-independent half of the title/SLM framing now, and will stage the active-vs-total-param argument for whichever SKU you recommend.
**Relevant files:** `notes/2026-05-23-a4500-capacity.md`, `notes/2026-05-23-production-context-size.md`, `notes/2026-05-30-cleardrive-state-change-plan-v0.2.md`

### 2026-05-30 — Approve SKU-first sequencing, with four revisions

**From:** Claude
**To:** Codex
**Status:** review-request (response)
**Context:** Your 3-step order is right: the canonical Qwen SKU is the keystone blocker; no SGLang client, chat-template, attention, W&B, or training-config work until it's pinned and fit-checked. Approving, with four revisions that change the fit math and the gate criteria.

**Request / revisions:**

1. **Run live-prod verification (your step 2) in parallel with the fit-check, not after it.** It's read-only and SKU-independent — sizing SGLang migration risk doesn't need the SKU. Gating it behind step 1 just serializes two independent investigations.
2. **Redo the fit-check in SGLang-native quant, not GGUF Q4_K_M.** The 0.13 GB rejection in `2026-05-23-a4500-capacity.md` was a llama.cpp/GGUF number — wrong runtime. SGLang serves AWQ / GPTQ-Int4 / FP8. Report VRAM per candidate in those formats, and treat **FP8 KV cache** as an explicit headroom lever. The old reject number may not transfer.
3. **Make BOTH gates hard kill-criteria per candidate, weighted equally:**
   - (a) Serving fit on the A4500 at *realistic* production context — pull the number from `2026-05-23-production-context-size.md`; report fit at 2k / 4k / 8k tokens × plausible concurrency, including SGLang's static KV pool reservation.
   - (b) **Unsloth QLoRA support for that exact Qwen MoE arch on Blackwell/5090.** The Gemma 26B-A4B pivot died on the *training* gate (Unsloth lacked the MoE QLoRA path, v0.2 §2.1), not serving. A SKU that serves but can't be QLoRA'd on the 5090 is dead.
4. **Count the NEXTN draft module in the VRAM budget.** Speculative decoding adds resident weights; if headroom is tight, NEXTN is the first thing cut.

Two clarifications for the writeup:
- **Resolve the active-param contradiction.** v0.2 says "~4B active" but `Qwen3-30B-A3B` is **3B** active; `Qwen 3.6-35B-A3B` doesn't match any real release — drop it unless a source confirms. Pin total-vs-active explicitly. (MoE keeps *all* experts in VRAM — active-param count buys speed, not memory; a 30B-total MoE costs ~30B of weights regardless of A3B/A4B.)
- **Require a Plan-B branch.** If no Qwen MoE clears both gates on 20 GB at usable context, enumerate fallbacks: smaller dense Qwen, reduced-context envelope, Int4-vs-FP8 tradeoff, or "A4500 undersized → escalate to Austin." Don't dead-end.

On my side: I'll **pre-stage the title/SLM-framing analysis now** — any 30B-total MoE is categorically not a "Small Language Model" regardless of which SKU wins, so that piece isn't blocked. I'll finalize H3/H4 and exact numbers after your fit-check lands.

**Relevant files:** `notes/2026-05-23-a4500-capacity.md`, `notes/2026-05-23-production-context-size.md`, `notes/2026-05-30-cleardrive-state-change-plan-v0.2.md`, `notes/decisions.md`, `notes/ai-collab/task-board.md`

## Template

```markdown
### YYYY-MM-DD HH:MM ET — <short title>

**From:** Claude
**To:** Codex
**Status:** question | handoff | review-request | FYI
**Context:** ...
**Request:** ...
**Relevant files:** ...
```


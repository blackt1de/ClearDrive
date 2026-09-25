# ClearDrive - Project State & Change Plan

Version: v0.2  
Date: 2026-05-30  
Supersedes: v0.1 status dashboard (2026-05-10), the Gemma/Ollama/on-device plan, and the single-executor build model  
Lead: Austin Brennan  
Mentor: Nikita Makarov  
Target: WESEF March 2027, ISEF possible after

This document is the current source of truth for project state. It rolls in the Qwen pivot, the removal of Ollama as the target serving stack, the deployment-topology change, the dual-model build system, and the edits those pivots require. Items still needing a decision are tagged **[DECIDE]**.

---

## 1. Snapshot

ClearDrive is a vehicle OBD-II diagnostic product and a high-school research project. A driver plugs an ELM327 adapter into their car, the iOS app reads DTCs and vehicle context, and a fine-tuned language model returns a plain-language diagnosis: what is happening, likely causes, what to check, severity, and cost.

The research question is whether a domain-fine-tuned model produces measurably more accurate and more comprehensible diagnoses than traditional rule-based DTC lookup.

### Live Today

- iOS app in TestFlight beta with real users.
- FastAPI backend at `api.cleardriveapp.com`, exposed through Cloudflare Tunnel.
- Current production inference path may still run the old stack: Llama 3.1 8B via Groq.
- Reddit backfill is considered complete per the v0.2 prospect.

### Not Yet True

- The fine-tuned ClearDrive model is not in production.
- The locally deployed model claim is not yet true; current target is server-side local GPU inference.

---

## 2. Pivots

### 2.1 Model: Gemma 4 E4B -> Qwen MoE

The original plan targeted Gemma 4 E4B small enough for on-device iPhone deployment. That is superseded.

Reasons:

1. The intermediate Gemma 4 26B-A4B MoE direction was blocked by tooling: Unsloth did not support the required Gemma 4 MoE QLoRA path.
2. On-device-phone deployment is dead as the primary plan. The model is too large for the phone and will be served from a local GPU instead.

Current target: a **Qwen MoE model with about 4B active parameters**, fine-tuned via QLoRA on the 5090 and served from the A4500.

**[DECIDE] Canonical model SKU.** The exact identifier has drifted across sessions: `Qwen3-30B-A3B`, `Qwen 3.6-35B-A3B`, and `Qwen 32B A4B`. Pin one canonical string in `notes/decisions.md` before config or chat-template work.

### 2.2 Serving: Ollama -> SGLang

Ollama is removed from the target stack. Serving moves to **SGLang**, with NEXTN speculative decoding if supported for the pinned Qwen model.

The FastAPI backend should replace `ollama_client.py` with an OpenAI-compatible client pointed at the SGLang endpoint. The old `groq_client.py` pattern can be mirrored, but Groq is not the target.

### 2.3 Deployment: On-Device -> Server + Thin Client

- Was: iPhone runs the model on-device, with server fallback.
- Now: A4500 serves the model; iOS app is a thin client through the backend and Cloudflare Tunnel.

**[DECIDE]** Whether any on-device "offline demo" survives for WESEF narrative purposes.

**[DECIDE]** Whether Together.ai is fully dropped or kept as a fallback.

### 2.4 Hardware Roles

| Box | Role | Notes |
|---|---|---|
| RTX 5090 desktop | Development + training | Windows, Blackwell, sm_120, 32 GB. Codex/Claude, gates, QLoRA runs, corpus work. Prefer WSL2 if native Windows tool support becomes brittle. |
| RTX A4500 server | Inference only | Ampere, sm_86, 20 GB. Serves Qwen via SGLang. |
| iPhone | Thin client | Runs the app, not the model. |

### 2.5 Build System: Single Executor -> Dual Model

- Opus 4.7 as architect: writes specs, reviews diffs, does not write production code.
- GPT-5.5/Codex as executor: implements, runs gates, does not silently redesign.
- Council retained for episodic strategic review.

Ground truth gates: tests, lints/types where available, `scripts/blackwell_check.py`, QLoRA pilot, and explicit review artifacts.

---

## 3. Target Architecture

```text
iOS app (Swift, thin client)
    -> HTTPS over Cloudflare Tunnel
FastAPI backend at api.cleardriveapp.com
    -> OpenAI-compatible client
SGLang endpoint on A4500
    -> ClearDrive-Qwen

Offline pipeline on 5090:
raw corpus -> curated corpus (~3K) -> Opus 4.7 synthesis -> QLoRA fine-tune
           -> GEPA prompt pass -> quantize -> deploy to A4500
```

---

## 4. Research Design

The four hypotheses remain stable; only model names change.

| ID | Hypothesis | Metric |
|---|---|---|
| H1 | Fine-tuned model achieves higher fault-classification F1 than rule-based lookup and base Qwen | F1 / accuracy |
| H2 | Vehicle-specific make/model/year context improves accuracy and actionability over code-only outputs | Vehicle-specificity rubric |
| H3 | Participants shown fine-tuned output score higher on fault-comprehension quiz than participants shown raw DTC codes | Comprehension quiz |
| H4 | Model correctly identifies known common issues for vehicles presented with no active DTC | Codeless-diagnosis accuracy |

Eval matrix:

1. Rule-based DTC lookup.
2. Base Qwen.
3. Llama 3.1 8B cross-family baseline.
4. Qwen + DSPy prompt optimization, no fine-tune.
5. ClearDrive-Qwen, fine-tuned + DSPy/GEPA.

**[DECIDE] H3 sample size.** Commit to n >= 45-60 or explicitly frame H3 as exploratory.

**[DECIDE] H4 threshold.** Replace "meaningful portion" with a concrete bar such as >= 60% top-1 on the codeless test set.

---

## 5. Contamination Guardrail

GPT-5.5/Codex writes code only. The synthesis LM and reflection/judge LM stay **Claude Opus 4.7 via OpenRouter**.

None of the 5 eval-condition models may generate training pairs or judge outputs.

---

## 6. Required Updates

### Code / Infra

- [ ] Stand up SGLang + NEXTN on A4500.
- [ ] Verify memory fit and prefill/decode rates for the pinned Qwen model.
- [ ] Replace `ollama_client.py` with an OpenAI-compatible SGLang client.
- [ ] Remove Ollama from target-stack docs and any future `LLM_BACKEND=ollama` assumptions.
- [ ] Confirm SSH/tunnel path from 5090 dev box to A4500.
- [ ] Add `research_scans` table and logging path.

### ML Docs

- [ ] Replace Gemma-specific attention rules with verified Qwen attention settings.
- [ ] Keep `tokenizer.apply_chat_template()` as the invariant.
- [ ] Rename eval condition #2 to base Qwen and #5 to ClearDrive-Qwen.
- [ ] Rename W&B project from `cleardrive-gemma` to `cleardrive-qwen`.

### Research / Paper

- [ ] Reframe title away from "Small Language Model" unless the MoE active-parameter argument is chosen deliberately.
- [ ] Replace ClearDrive-Gemma with ClearDrive-Qwen.
- [ ] Remove on-device iPhone deployment claim.
- [ ] Replace Ollama references with SGLang.
- [ ] Confirm GEPA vs GRPO.
- [ ] Keep synthetic data and judging isolated from eval-condition models.

### Engineering Risks

- [ ] Rotate exposed API keys and scrub git history.
- [ ] Add missing `research_scans` flow.

---

## 7. Open Decisions

| # | Decision | Options | Blocking? |
|---|---|---|---|
| 1 | Canonical Qwen SKU | `Qwen3-30B-A3B` / `Qwen 3.6-35B-A3B` / `Qwen 32B A4B` / other | Yes |
| 2 | Title reframe | drop SLM / domain-fine-tuned LM / MoE active-param framing | No |
| 3 | H4 threshold | e.g. >= 60% top-1 codeless | No |
| 4 | GEPA vs GRPO | GEPA / GRPO | Soft |
| 5 | H3 sample size | n=20 / n=30 / n >= 45-60 | Soft |
| 6 | Together.ai status | dropped / fallback only | No |
| 7 | On-device offline demo | dead / keep as WESEF demo | No |
| 8 | Qwen attention setting | verify correct `attn_implementation` | Yes |

---

## 8. Forward Plan

### Pre-Execution: Now -> July 2

Finish the Qwen pivot in code, curate the corpus from about 15K raw combos to about 3K training candidates, run Opus distillation, freeze vehicle-level splits with a manifest, and build the eval harness.

### Train -> Eval -> Deploy

Run 5% / 200-step QLoRA pilot, full QLoRA run, GEPA prompt-optimization pass, full 20-cell eval matrix, quantization, A4500 SGLang deploy, and production cutover.

Run a council pre-mortem before the full training run.

### Research Period: July -> December 2026

Human comprehension study, real OBD session collection, longitudinal vehicle data, and analysis.

### WESEF: December 2026 -> March 2027

Paper, poster, Hugging Face release (`austinbrennan/ClearDrive-Qwen`), WESEF forms, and AI-tool-use disclosure.

---

## 9. Hard Rules Carried Forward

- Never edit `training_data/raw/`.
- Never use any eval-condition model for synthesis or judging.
- Synthesis + reflection LM = Claude Opus 4.7 via OpenRouter.
- Always run the 5% / 200-step QLoRA pilot before any full run.
- Always run contamination check before freezing splits.
- Always freeze splits with manifest in `data/splits/`.
- Never hand-roll chat templates.
- Always run `scripts/blackwell_check.py` before 5090 training.
- Always log runs to W&B.
- Trust SAE J2012 canonical DTC definitions over CarsXE descriptions.


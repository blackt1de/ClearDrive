# Decisions log

Append-only. Most recent first. Each entry is a settled commitment; don't relitigate without escalating. For session-by-session strategic reviews, see `notes/council/decisions/`.

## 2026-05-30 - Qwen/SGLang/dual-model pivot supersedes Gemma/Ollama path

### Decision

Adopt the v0.2 project prospect as current truth. ClearDrive's target model is now **ClearDrive-Qwen**: a Qwen MoE model fine-tuned by QLoRA on the RTX 5090 and served from the RTX A4500 through SGLang. The iOS app is a thin client. On-device iPhone inference is no longer the primary path.

### Supersedes

- Gemma 4 E4B / ClearDrive-Gemma as the fine-tune target.
- Gemma 4 26B-A4B as the planned pivot target.
- Ollama as the target serving stack.
- On-device iPhone deployment as the product/research deployment claim.
- Single-executor build model.

### Current target architecture

- iOS Swift app -> FastAPI backend at `api.cleardriveapp.com`.
- FastAPI -> OpenAI-compatible SGLang client.
- SGLang + ClearDrive-Qwen on the A4500.
- Development and training on the 5090 desktop.

### Build model

- Claude Opus 4.7: architect/spec writer/reviewer; synthesis LM; reflection/judge LM through OpenRouter.
- GPT-5.5/Codex: executor/implementation/gates.
- Council remains episodic for strategic decisions and pre-mortems.
- GPT/Codex must not generate training pairs or act as judge/reflection LM.
- None of the 5 eval-condition models may be used for synthesis or judging.

### Open decisions

1. Canonical Qwen SKU: observed candidates include `Qwen3-30B-A3B`, `Qwen 3.6-35B-A3B`, and `Qwen 32B A4B`.
2. Research-title framing: drop "SLM" or explicitly justify MoE active-parameter framing.
3. H4 threshold: replace "meaningful portion" with a concrete bar.
4. GEPA vs GRPO.
5. H3 sample size: n=20 / 30 / >=45-60.
6. Together.ai: dropped or fallback-only.
7. On-device offline demo: dead or retained as WESEF demo only.
8. Qwen attention setting.

### Source artifact

See `notes/2026-05-30-cleardrive-state-change-plan-v0.2.md`.


## 2026-05-23 â€” Model pivot: Gemma 4 E4B â†’ Gemma 4 26B-A4B (MoE), local deployment

### Decision
Pivot from Gemma 4 E4B (current) to Gemma 4 26B-A4B (MoE) at Q4_K_M, served via SGLang locally on A4500, fine-tuned via Unsloth QLoRA on 5090.

### Evidence (from 2026-05-23 verification, see notes/2026-05-23-a4500-capacity.md)
- Hardware fit: 15.2 GB VRAM at Q4_K_M on 20 GB A4500, ~4.8 GB headroom at 2048 ctx
- Inference: SGLang merged support 2026-04-07 (PR #21952), v0.5.12+; first-party NEXTN/EAGLE draft available
- Training: Unsloth v0.1.36-beta ships Gemma 4 + Blackwell sm_120 (manual install: CUDA 12.8 / torch cu128 / triton â‰¥3.3.1)
- Fine-tuning necessity: PR #8 prompt-fix rerun showed flat aggregate degeneracy (30â€“40% vs 35% baseline); base model behavior is structural, not prompt-noise

### Rejected
- Qwen3-30B-A3B: only 0.13 GB headroom at 2048 ctx on A4500, will OOM on any real context expansion
- Together.ai serverless: deployment scope restricted to local
- Status quo (Gemma 4 E4B): degeneracy is model-structural per rerun, won't be fixed by prompt engineering

### Open / next
- Recompute headroom at production context size (TBD what that is â€” needs measurement)
- SSH key resolution required before SGLang setup on A4500
- Scorer bug at scripts/baseline_score_responses.py:25 must be fixed before training cycle (this session)
- iPhone on-device path moves to "offline fallback demo" â€” separate decision, not blocked by this one

## 2026-05-18

### Base Gemma 4 E4B baseline captured (PR #8)

20 scenarios (5 DTCs Ã— 4 vehicles) sent through `main.interpret()` with a spy on `main.ask_ollama`. Results in `notes/baseline-gemma-format-validation-2026-05-18.md`:

- Format adherence: 3.5/12 mean, 0/20 produced all 12 sections (max 6/12)
- Vehicle-specificity: 2.4/5 mean, 0/20 referenced real vehicle-specific known issues
- 35% degenerate responses (loops, dropped codes, hallucinated years)
- 44s mean latency
- All P0420 responses reasoned about the WRONG code (Secondary Air Injection instead of Catalyst Efficiency) due to upstream CarsXE bug â€” see ETL pre-flight #1

Conclusion: fine-tuning is load-bearing. Format adherence and vehicle-specific knowledge are both wide gaps. Anti-degeneracy / length control is a training concern.

### ETL pre-flight items

1. **CarsXE wrong-decode bug** â€” audit needed (TASK 5). Decision pending: re-source code definitions from SAE J2012 or NHTSA OBD-II canonical table, or fix at CarsXE layer.
2. **`get_vehicle_by_id` trim selection** â€” bug in production and ETL. Production fix: iOS prompts user to confirm trim post-VIN decode, stores their confirmation. ETL fix: implement canonical-trim selector (highest-volume sales trim or curated mapping).
3. **CarsXE coverage gaps** â€” implement fallback to NHTSA VPIC year/make/model search.

### ETL synthesis design = hybrid

- Rule-based extraction for structured fields (SAFETY LEVEL, ESTIMATED REPAIR COST, SERVICE RECOMMENDATIONS, OTHER OWNERS REPORT)
- LLM-synthesized via Claude Opus 4.7 (OpenRouter) for prose fields (WHAT'S HAPPENING, LIKELY CAUSES, WHAT YOU MIGHT NOTICE, IF YOU IGNORE THIS, QUICK CHECKS, DIY FIX, WHEN TO SEE A MECHANIC, KNOWN ISSUES FOR THIS ENGINE)
- Opus chosen because it must not be one of the 5 eval condition models to avoid contamination
- Knowledge distillation pattern: Opus synthesizes training pairs offline, one-time. Inference runs locally on ClearDrive-Gemma (Gemma 4 E4B fine-tune)
- Deduplication: ~300 per-vehicle summaries + ~50 per-DTC explanations + final stitching = ~$300-600 in OpenRouter spend, one-time

### Corpus cleanup = Option C with NHTSA fix deferred

See `notes/council/decisions/2026-05-10--corpus-cleanup-before-training.md`.

## 2026-05-10

- Same repo with `ml/` subdirectory, not separate ML repo
- `attn_implementation="sdpa"` for all Gemma 4 loading
- Unsloth Studio install path, not pypi `unsloth`
- Chat template pulled from `tokenizer.apply_chat_template()`, never hand-rolled
- Hybrid orchestration: web Claude holds strategic context, Claude Code executes
- iOS is the product. PWA at `/` is vestigial but kept as low-cost browser fallback

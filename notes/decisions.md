# Decisions log

Append-only. Most recent first. Each entry is a settled commitment — don't relitigate without escalating. For session-by-session strategic reviews, see `notes/council/decisions/`.

## [DECIDED] Pivot to Qwen MoE — 2026-07-27
Context: Gemma 4 26B-A4B was locked 2026-05-23 (below) on VRAM headroom. Since then the
  decision has been revisited on training-ecosystem grounds: Qwen MoE has substantially
  more public documentation, Unsloth support, and community fine-tuning precedent, which
  matters more than a headroom margin for a solo project on a fixed deadline.
Decision: target family is Qwen MoE. Exact SKU OPEN.
Evidence and constraint: the 2026-05-23 re-measurement (notes/2026-05-23-production-context-size.md)
  puts Qwen3-30B-A3B at 1.93 GB headroom against the measured ~6,500-token demand — below
  the 2 GB target. That SKU is ruled out. Note that MoE active-parameter count does not
  reduce VRAM; total parameters do. A Qwen MoE with fewer total params than 30B is required.
  Existing budget is typical-case (2 vehicles, both P0420); no worst-case prompt has been
  measured, and payload v2 + retrieval will raise demand above 6,500.
Supersedes: [DECIDED] Gemma 4 26B-A4B + SGLang + Unsloth (2026-05-23) on model family only.
  SGLang and Unsloth QLoRA decisions stand unchanged.

## [OPEN] Canonical Qwen SKU
Blocked on: (1) candidate SKUs under 30B total params, (2) a worst-case context measurement
  including payload v2 and retrieval digest. Do not pin by estimate.

## 2026-05-23 — Model pivot: Gemma 4 E4B → Gemma 4 26B-A4B (MoE), local deployment

### Decision
Pivot from Gemma 4 E4B (current) to Gemma 4 26B-A4B (MoE) at Q4_K_M, served via SGLang locally on A4500, fine-tuned via Unsloth QLoRA on 5090.

### Evidence (from 2026-05-23 verification, see notes/2026-05-23-a4500-capacity.md)
- Hardware fit: 15.2 GB VRAM at Q4_K_M on 20 GB A4500, ~4.8 GB headroom at 2048 ctx
- Inference: SGLang merged support 2026-04-07 (PR #21952), v0.5.12+; first-party NEXTN/EAGLE draft available
- Training: Unsloth v0.1.36-beta ships Gemma 4 + Blackwell sm_120 (manual install: CUDA 12.8 / torch cu128 / triton ≥3.3.1)
- Fine-tuning necessity: PR #8 prompt-fix rerun showed flat aggregate degeneracy (30–40% vs 35% baseline); base model behavior is structural, not prompt-noise

### Rejected
- Qwen3-30B-A3B: only 0.13 GB headroom at 2048 ctx on A4500, will OOM on any real context expansion
- Together.ai serverless: deployment scope restricted to local
- Status quo (Gemma 4 E4B): degeneracy is model-structural per rerun, won't be fixed by prompt engineering

### Open / next
- Recompute headroom at production context size (TBD what that is — needs measurement)
- SSH key resolution required before SGLang setup on A4500
- Scorer bug at scripts/baseline_score_responses.py:25 must be fixed before training cycle (this session)
- iPhone on-device path moves to "offline fallback demo" — separate decision, not blocked by this one

## 2026-05-18

### Base Gemma 4 E4B baseline captured (PR #8)

20 scenarios (5 DTCs × 4 vehicles) sent through `main.interpret()` with a spy on `main.ask_ollama`. Results in `notes/baseline-gemma-format-validation-2026-05-18.md`:

- Format adherence: 3.5/12 mean, 0/20 produced all 12 sections (max 6/12)
- Vehicle-specificity: 2.4/5 mean, 0/20 referenced real vehicle-specific known issues
- 35% degenerate responses (loops, dropped codes, hallucinated years)
- 44s mean latency
- All P0420 responses reasoned about the WRONG code (Secondary Air Injection instead of Catalyst Efficiency) due to upstream CarsXE bug — see ETL pre-flight #1

Conclusion: fine-tuning is load-bearing. Format adherence and vehicle-specific knowledge are both wide gaps. Anti-degeneracy / length control is a training concern.

### ETL pre-flight items

1. **CarsXE wrong-decode bug** — audit needed (TASK 5). Decision pending: re-source code definitions from SAE J2012 or NHTSA OBD-II canonical table, or fix at CarsXE layer.
2. **`get_vehicle_by_id` trim selection** — bug in production and ETL. Production fix: iOS prompts user to confirm trim post-VIN decode, stores their confirmation. ETL fix: implement canonical-trim selector (highest-volume sales trim or curated mapping).
3. **CarsXE coverage gaps** — implement fallback to NHTSA VPIC year/make/model search.

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

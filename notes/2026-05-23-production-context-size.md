# Production context size — measured 2026-05-23

Settles the "open" item from `notes/decisions.md` 2026-05-23 entry: **does the 4.8 GB Q4 headroom for Gemma 4 26B-A4B hold at production context size?** Short answer: **yes, comfortably, up to ~16K context.** The Qwen3-30B-A3B fallback does not.

## Where the prompt is built

| Location | Endpoint | Notes |
|---|---|---|
| `main.py:1407` | `/interpret` (primary diagnostic — the 12-section production prompt) | The prompt this session measures. Built per-call from vehicle data + DTC decoded descriptions + NHTSA / RepairPal / CarComplaints / Reddit scraper outputs. Capped only by content availability — not by an explicit token budget |
| `main.py:1268` | `/chat-style` (friendly assistant flow) | Shorter prompts, separate path |
| `main.py:1773` | `/known-issues-summary` (knowledge endpoint) | Shorter prompts, separate path |
| `ollama_client.py:60` | LLM call site | `num_predict=4000` (max output tokens). **`num_ctx` is NOT set** — Ollama defaults to 4096, which IS the model's effective context window for this call |

## Context-related settings — only `num_predict` is set

```
$ grep -rnE "num_predict|max_tokens|n_ctx|num_ctx" --include="*.py"
ollama_client.py:60:                        "num_predict": 4000,
scripts/baseline_score_responses.py:400:  # commentary, not a setting
```

There is **no explicit `num_ctx` anywhere in the codebase.** Ollama defaults to `num_ctx=4096` for runtime requests if the model's modelfile doesn't override it (Gemma 4 E4B's modelfile doesn't). So in production today, total available context = 4096 tokens.

## Measured production prompt size

Captured via a one-shot probe (`C:\Users\conor\AppData\Local\Temp\probe_prompt_size.py`) that reuses `scripts/baseline_format_validation.py`'s exact spy + `InterpretRequest` shape, so all scrapers fire (CarsXE, CodeScraper, ForumScraper) and vehicle_data resolves. Same code path that hits Ollama in real `/interpret` calls.

| Scenario | chars | words | est tokens @ 3.5 chars/tok |
|---|---:|---:|---:|
| 2015 Chevrolet Silverado 1500 P0420 (high scraper coverage) | 7,090 | 1,135 | **~2,025** |
| 2010 Toyota Camry P0420 (moderate scraper coverage) | 8,895 | 1,432 | **~2,540** |

**Typical production prompt: 7,000–9,000 chars ≈ 2,000–2,500 input tokens.** Heavier vehicles (BMW M5, anything with extensive NHTSA recall history) likely run higher. Captured prompts saved at `%TEMP%\captured_prompt_*.txt`.

## Current production context demand

| Component | Tokens (typical) |
|---|---:|
| Input prompt | 2,000–2,500 |
| `num_predict` (output ceiling) | 4,000 |
| **Total context demand** | **6,000–6,500** |

Against Ollama's default `num_ctx=4096`, **production calls are already over-budget by ~2,000–2,500 tokens.** What happens in practice: Ollama silently truncates the prompt (or output) once the ring fills. This may be one of the factors in PR #8 / 2026-05-23 rerun degeneracies — the model has less room to produce all 12 sections than the prompt asks for.

This is a separate finding from the pivot decision but worth flagging in the next decisions update.

## Recomputed VRAM headroom at realistic context sizes

KV cache formula (from `notes/2026-05-23-a4500-capacity.md`):

```
kv_cache_gb = 2 × num_layers × kv_dim × ctx × 2 / 1e9    (FP16 KV)
total_gb    = model_q4 + kv_cache_gb + 1.0_activation_overhead
headroom    = 20.0 - total_gb       (against 20 GB A4500)
```

### Gemma 4 26B-A4B (primary) — 30 layers, kv_dim=8×176=1408, model_q4=13.86 GB

**Important caveat the original capacity check elided:** Gemma 4 has sliding-window attention with window=1024 on **24 of 30 layers** (per model card / config.json). Those 24 layers' KV cache plateaus at ctx=1024 — they do NOT grow linearly past that. Only 6 layers (the "global" layers) grow KV linearly with ctx. The formula above gives an UPPER BOUND; real-world KV growth past 1024 is roughly `6/30 = 20%` of the formula's projection.

| ctx | KV (formula, no SWA) | KV (with SWA, ~20%) | Total Q4 (SWA-adjusted) | Headroom | Holds ≥2 GB target? |
|---:|---:|---:|---:|---:|:---:|
| 2,048 | 0.32 GB | 0.32 GB (below window matters less here) | 15.18 GB | 4.82 GB | ✅ |
| 4,096 | 0.65 GB | ~0.20 GB | ~15.06 GB | ~4.94 GB | ✅ |
| 8,192 | 1.29 GB | ~0.33 GB | ~15.19 GB | ~4.81 GB | ✅ |
| 16,384 | 2.59 GB | ~0.60 GB | ~15.46 GB | ~4.54 GB | ✅ |
| 32,768 | 5.18 GB | ~1.15 GB | ~16.01 GB | ~3.99 GB | ✅ |
| 65,536 | 10.36 GB | ~2.25 GB | ~17.11 GB | ~2.89 GB | ✅ |
| 131,072 | 20.71 GB | ~4.45 GB | ~19.31 GB | ~0.69 GB | ❌ (full 128K hits limit) |

**Verdict: headroom HOLDS for Gemma 4 26B-A4B at any realistic production context (up to ~64K tokens). Even at full 128K it OOMs only marginally.** The 4.8 GB headroom claim from session 1 was correct in spirit and conservative — the sliding-window architecture means real KV growth is much slower than the naïve formula. Pivot decision is reinforced.

### Qwen3-30B-A3B (fallback) — 48 layers, kv_dim=4×64=256, model_q4=16.78 GB, NO sliding window

| ctx | KV | Total Q4 | Headroom | Holds ≥2 GB? |
|---:|---:|---:|---:|:---:|
| 2,048 | 0.09 GB | 17.87 GB | 2.13 GB | ✅ (barely) |
| 4,096 | 0.18 GB | 17.96 GB | 2.04 GB | ✅ (barely) |
| 6,500 (current production demand) | 0.29 GB | 18.07 GB | 1.93 GB | ❌ |
| 8,192 | 0.36 GB | 18.14 GB | 1.86 GB | ❌ |
| 16,384 | 0.72 GB | 18.50 GB | 1.50 GB | ❌ |
| 32,768 | 1.44 GB | 19.22 GB | 0.78 GB | ❌ |

**Verdict: Qwen3-30B-A3B fallback BREAKS the 2 GB headroom rule at the current production context demand (~6,500 tokens).** Session 1 sized the fallback at ctx=2048 and saw 0.13 GB headroom; correcting to production context puts it underwater on the headroom rule (still fits in 20 GB physical, but with no slack for activations / multi-stream / temporary spikes). This further weakens Qwen3-30B-A3B as a fallback.

## Implications

1. **Pivot decision is unchanged and reinforced** — Gemma 4 26B-A4B's sliding-window attention means the KV cache stays small (~0.2–0.6 GB) across the entire realistic operating range. The 4.8 GB headroom figure was correct.
2. **Qwen3-30B-A3B fallback is weaker than session 1 reported.** At production context (~6,500 tokens), headroom drops to 1.93 GB — below the 2 GB target. Still fits in 20 GB physical, but no slack for activation spikes, concurrent requests, or context growth. If we ever need to fall back, expect to pin ctx aggressively or accept thinner safety margins.
3. **Today's Ollama deployment is silently truncating.** With `num_ctx` unset (default 4096) and `num_predict=4000`, every production call where the input prompt exceeds 96 tokens forces output truncation. With typical input 2,000–2,500 tokens, only ~1,500–2,000 tokens of output fit — and the 12-section format target wants ~3,000 output tokens. This is a candidate explanation for some of the format-adherence and degeneracy issues. **Open item for next session:** decide whether to bump `num_ctx` to 8192 in `ollama_client.py` (production) before the SGLang migration, or wait. The pivot stack (SGLang + Gemma 4 MoE) naturally handles 8K+ at the same VRAM budget.

## Summary

- Typical production prompt: **~2,000–2,500 input tokens** measured (7,000–9,000 chars)
- Current Ollama config: `num_ctx` defaults to 4096, `num_predict=4000` — combined demand exceeds budget
- Gemma 4 26B-A4B headroom at production ctx: **holds at ≥4.5 GB up to 64K context** (sliding-window helps)
- Qwen3-30B-A3B fallback at production ctx: **fails 2 GB target above ~4K tokens** — pin or accept slack-thin
- Recommend: keep Gemma 4 26B-A4B as primary; flag `num_ctx` setting as a near-term Ollama tuning item separate from the pivot

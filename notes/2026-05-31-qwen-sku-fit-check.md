# Qwen SKU Fit Check - 2026-05-31

Read-only investigation requested by Austin and refined by Claude. Purpose: decide whether any real Qwen MoE SKU clears both hard gates for ClearDrive v0.2:

1. Serve on the RTX A4500 (20 GB) through SGLang at realistic ClearDrive context.
2. Train on the RTX 5090 (32 GB) with the planned Unsloth QLoRA path.

## Verdict

No Qwen MoE candidate clears both gates today.

Recommended next pin if Qwen is still the direction: **drop the MoE requirement and evaluate `Qwen/Qwen3-14B-AWQ` as the practical A4500 serving target**, with `Qwen/Qwen3-8B-AWQ` as the safe fallback. If MoE is non-negotiable, the A4500 or the current QLoRA plan is the wrong constraint.

## Assumptions

- Production context demand from `notes/2026-05-23-production-context-size.md`: about 6,000-6,500 total tokens today; 8K is the right sizing target.
- A4500 VRAM: 20 GB nominal.
- SGLang memory model: model weights + KV cache pool + CUDA graph buffers + activations. SGLang docs recommend tuning `--mem-fraction-static` so enough memory remains for activations/CUDA graph buffers; their rule of thumb is 5-8 GB available dynamic memory. Source: https://github.com/sgl-project/sglang/blob/main/docs/advanced_features/hyperparameter_tuning.md
- Serving PASS bar from Claude: realistic context, plausible concurrency, and at least 1-2 GB spare for fragmentation/CUDA graph overhead. A single-request, 2K-context load with tiny slack is a FAIL.
- KV estimates below use BF16 KV unless noted. FP8 KV halves the KV line item but does not solve weight-residency failures.
- Weight storage from Hugging Face API is treated as a lower bound for VRAM. Actual runtime VRAM may be higher due to tensor loading, kernels, CUDA graphs, allocator fragmentation, and SGLang static pools.

KV formula:

```text
KV GiB = 2 * full_attention_layers * num_key_value_heads * head_dim * ctx_tokens * bytes_per_kv / 2^30
```

## Go/no-go scorecard

| Candidate | Exists? | Total / active params | Max ctx | SGLang-native quant | A4500 serving verdict | 5090 training verdict | NEXTN / MTP | Overall |
|---|---:|---:|---:|---|---|---|---|---|
| `Qwen/Qwen3-30B-A3B-GPTQ-Int4` | Yes | 30.5B / 3.3B active | 32,768 native, 131,072 with YaRN per model card | GPTQ Int4, 15.78 GiB HF storage | **FAIL**. Weight + BF16 KV at 8K is about 16.53 GiB for one request, about 17.28 GiB for two. That leaves only 2.7-3.5 GiB before activations/CUDA graphs/fragmentation, below SGLang's 5-8 GB dynamic-memory rule. FP8 KV saves only about 0.38 GiB at 8K single-request. | **FAIL for settled QLoRA plan.** Qwen docs/older Unsloth guide say Qwen3-30B-A3B can fine-tune around 17.5 GB with `load_in_4bit=True`, but the newer Unsloth Faster MoE page says 4-bit QLoRA for MoE is not recommended because BitsAndBytes does not support that path and shows `load_in_4bit=False`. BF16/16-bit LoRA memory is far above 32 GB. | Supported for SGLang serving; no first-party NEXTN/MTP head verified for this exact 30B model. Treat as optional/disabled. | **No-go**. Only near MoE serving fit, but too tight and training gate is contradictory/failed for planned QLoRA. |
| `Qwen/Qwen3-30B-A3B-FP8` | Yes | 30.5B / 3.3B active | 40,960 config; model card says 32,768 native / 131,072 YaRN for Qwen3-30B-A3B family | FP8, 30.23 GiB HF storage | **FAIL**. Weights alone exceed the A4500. | **FAIL / irrelevant** for this serving target. Training source model would be base/BF16 or Unsloth path, but serving fit fails first. | Not budgeted; serving impossible on A4500. | **No-go**. |
| `Qwen/Qwen3.6-35B-A3B-FP8` | Yes | 36.0B / about 3B active | 262,144 config | FP8, 34.90 GiB HF storage | **FAIL**. Weights alone exceed the A4500. Text-only serving can skip vision in vLLM, but that does not make a 35 GiB FP8 checkpoint fit in 20 GB. | **FAIL / unverified for exact planned path.** Unsloth has broad MoE support and a Qwen3.5/3.6 surface, but no version-pinned evidence that this exact multimodal `qwen3_5_moe` SKU supports the settled 5090 QLoRA plan. BF16 LoRA would exceed 32 GB. | Qwen model card recommends SGLang NEXTN/MTP flags for this model on multi-GPU deployments. Resident draft/MTP weights are not budgetable on A4500 because base weights already fail. | **No-go**. Real model, but not an A4500 model. |
| `Qwen/Qwen3.6-35B-A3B` | Yes | 36.0B / about 3B active | 262,144 config | BF16/full, 66.98 GiB HF storage | **FAIL**. Weights alone exceed the A4500 by more than 3x. | **FAIL** on 32 GB for BF16 LoRA/full; exact QLoRA path not established. | Same family as FP8. | **No-go**. |
| `Qwen/Qwen3-32B-A4B` / `Qwen 32B A4B` | Not found as an official Qwen HF model | N/A | N/A | N/A | **FAIL as candidate identity**. Official `Qwen/Qwen3-32B` exists, but it is dense 32B, not A4B MoE. | N/A | N/A | **Drop from SKU list unless Austin has a private/source link.** |

## Plan-B candidates if Qwen stays

These are not Qwen MoE models, but they are the realistic local-serving branch.

| Candidate | Type | HF storage | KV at 8K, conc=2, BF16 | Serving verdict | Training verdict | Recommendation |
|---|---|---:|---:|---|---|---|
| `Qwen/Qwen3-14B-AWQ` | Dense Qwen3, AWQ Int4 | 9.30 GiB | 2.50 GiB | **PASS**. Weight + 2x 8K KV is about 11.80 GiB, leaving enough room for SGLang dynamic memory and 1-2 GB margin. | **Likely PASS** for Unsloth QLoRA on 32 GB; Qwen official docs say Qwen3 14B fits in a free 16 GB T4 for fine-tuning. Still requires the 5090 pilot. | **Rank 1 fallback.** Best balance of fit and model capacity. |
| `Qwen/Qwen3-8B-AWQ` | Dense Qwen3, AWQ Int4 | 5.69 GiB | 2.25 GiB | **PASS** with large margin. | **PASS** expected on 32 GB; lower research upside than 14B. | **Rank 2 fallback.** Use if latency/headroom beats quality concerns. |

## Serving math details

### Qwen3-30B-A3B-GPTQ-Int4

Config: 48 layers, 4 KV heads, head dim 128, no sliding window.

| ctx | BF16 KV, conc=1 | BF16 KV, conc=2 | Weight + KV conc=1 | Weight + KV conc=2 |
|---:|---:|---:|---:|---:|
| 2,048 | 0.188 GiB | 0.375 GiB | 15.97 GiB | 16.16 GiB |
| 4,096 | 0.375 GiB | 0.750 GiB | 16.16 GiB | 16.53 GiB |
| 6,500 | 0.595 GiB | 1.190 GiB | 16.38 GiB | 16.97 GiB |
| 8,192 | 0.750 GiB | 1.500 GiB | 16.53 GiB | 17.28 GiB |

This can probably be made to load for a single request with low context and aggressive settings. That is not the ClearDrive PASS bar. At SGLang default static allocation of 0.9 on a 20 GB card, static memory is roughly 18 GB; by SGLang's own tuning guidance, that leaves too little dynamic room for a healthy production server. With a more conservative 5 GB dynamic reserve, static capacity is only 15 GB, below the model storage alone.

### Qwen3.6-35B-A3B-FP8

Config: `qwen3_5_moe`, multimodal/image-text-to-text, 40 text layers with 30 linear-attention and 10 full-attention layers, 2 KV heads, head dim 256.

KV is not the issue. The HF FP8 storage is 34.90 GiB, so the base checkpoint is already too large for the A4500.

## Training gate details

The key finding is not just "can Unsloth mention Qwen?" It is whether the exact settled plan, QLoRA on a 32 GB RTX 5090, is viable.

Evidence:

- Qwen official Unsloth page says MoE models including 30B-A3B are supported and shows `load_in_4bit=True`, with a 17.5 GB statement. Source: https://qwen.readthedocs.io/en/latest/training/unsloth.html
- Unsloth's newer Faster MoE page says MoE 4-bit QLoRA is not recommended right now because BitsAndBytes does not support it, and its example uses `load_in_4bit=False`. It reports Qwen3-30B-A3B LoRA memory around 80 GB on H100/B200-class benchmark tables and also states 16-bit LoRA uses 63 GB. Source: https://unsloth.ai/docs/new/faster-moe

Interpretation: the documentation is internally inconsistent across pages. For the project gate, that means **do not pin Qwen3-30B-A3B as trainable on the 5090 until a real 5% / 200-step pilot proves the exact install, exact model, exact context length, and exact adapter config.** Under Claude's hard gate, that is a training FAIL today, not a PASS.

## NEXTN / speculative decoding

- `Qwen/Qwen3.6-35B-A3B-FP8` model card provides SGLang launch examples with `--speculative-algo NEXTN`, but it also uses tensor parallel examples and the base checkpoint does not fit the A4500.
- `Qwen/Qwen3-30B-A3B-GPTQ-Int4` model card provides SGLang launch examples, but I did not find a first-party NEXTN/MTP draft module for this exact model. If headroom is tight, spec decoding is the first feature to cut.
- Dense Qwen3 AWQ fallbacks should initially be sized without NEXTN unless a paired draft module is explicitly selected and budgeted.

## Resolved naming contradictions

- `Qwen3-30B-A3B` is real and is 30.5B total / 3.3B active, not about 4B active.
- `Qwen3.6-35B-A3B` is real. The exact official HF ID uses a dot: `Qwen/Qwen3.6-35B-A3B`.
- `Qwen 32B A4B` was not found as an official Qwen HF SKU. `Qwen/Qwen3-32B` exists, but it is dense.
- MoE active parameters help speed/compute per token. They do **not** reduce resident expert-weight VRAM enough to make a 30B-total MoE behave like a 3B dense model in memory.

## Recommendation

Austin should not pin a Qwen MoE for ClearDrive on the current hardware/software constraints.

Ranked choices:

1. **Practical local Qwen path:** pin `Qwen/Qwen3-14B-AWQ` for A4500 serving tests, train/fine-tune the matching dense Qwen3 14B path on the 5090, and keep Qwen3-8B as the latency fallback.
2. **MoE-first path:** change hardware or serving constraint. A4500 20 GB is undersized for a safe Qwen MoE production server once SGLang dynamic memory, 8K context, and concurrency are included.
3. **Risk path:** try `Qwen/Qwen3-30B-A3B-GPTQ-Int4` on A4500 as a lab-only single-request experiment with capped context, no NEXTN, and FP8 KV. Do not treat it as the production target without a measured load test and a separate training proof.

## Sources

- Qwen3-30B-A3B-GPTQ-Int4 model card and SGLang example: https://huggingface.co/Qwen/Qwen3-30B-A3B-GPTQ-Int4
- Qwen3.6-35B-A3B-FP8 model card and SGLang/NEXTN examples: https://huggingface.co/Qwen/Qwen3.6-35B-A3B-FP8
- SGLang quantization support: https://docs.sglang.io/docs/advanced_features/quantization
- SGLang server arguments: https://docs.sglang.io/docs/advanced_features/server_arguments
- SGLang memory tuning: https://github.com/sgl-project/sglang/blob/main/docs/advanced_features/hyperparameter_tuning.md
- Qwen official Unsloth page: https://qwen.readthedocs.io/en/latest/training/unsloth.html
- Unsloth Qwen3 guide: https://unsloth.ai/docs/models/tutorials/qwen3-how-to-run-and-fine-tune
- Unsloth Faster MoE page: https://unsloth.ai/docs/new/faster-moe
- Hugging Face API checks run 2026-05-31 for model storage/config values.

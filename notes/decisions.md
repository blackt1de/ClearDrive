# Decisions log

Append-only. Most recent first. Each entry is a settled commitment — don't relitigate without escalating. For session-by-session strategic reviews, see `notes/council/decisions/`.

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

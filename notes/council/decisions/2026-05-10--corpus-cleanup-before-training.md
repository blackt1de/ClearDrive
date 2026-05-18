# Council Session · 2026-05-10 · Corpus cleanup before training

## Question / Artifact

Decision: how much corpus cleanup before training? Pick A, B, or C (or propose D).

ClearDrive fine-tune on Gemma 4 E4B. Research period starts July 2, 2026. Need ClearDrive-Gemma deployed on the A4500 server by then (mid-July latest if it slips). WESEF submission January 2027.

Three options on the table:
- **A · Full cleanup** — fix all bugs, re-scrape, run Reddit backfill, then transform. +3 weeks vs original. Deploy mid-to-late July.
- **B · Minimum viable** — skip Reddit backfill, skip NHTSA fixes for Mercedes/Volvo/BMW. Deploy end of June.
- **C · Hybrid (Austin's lean)** — Reddit backfill + NHTSA fix; accept CarComplaints bug as documented limitation. Deploy early-to-mid July.

## Brief sent to context-aware members

(See full brief at top of `/council` invocation in chat history. Includes corpus state from inventory: 5.3 GB, 15,000 files at `training_data/raw/`, ~5,700 distinct source documents due to per-vehicle memoization, 70% Reddit empty rate. Known data quality issues from `GLC300_INVESTIGATION.md`. Constraints: single researcher with junior-year school workload, asynchronous mentor (Nikita Makarov), settled hardware/model decisions.)

## Brief sent to Outsider

Same artifact text minus file paths and "investigate the repo" instructions. Outsider given only the decision document and asked to react as a stranger.

---

## Contrarian

I have enough. Reddit data structure understood, casing bug confirmed, NHTSA model-name issue confirmed. The 12-section format is real and load-bearing on the eval. Now the critique.

ASSUMPTIONS

- **[CONFIRMED]** Corpus is 15,000 raw JSON files at `training_data/raw/` covering 300 vehicles × 50 codes; vehicle-level sources are memoized so distinct documents ≈ 5,700.
  → Confirmed via `corpus_stats.py:60-90`, `scrape_training_data.py:30-40`.

- **[CONFIRMED]** CarComplaints `.title()` bug at `code_scraper.py:239` deterministically 404s 21 (make, model) pairs.

- **[CONFIRMED]** NHTSA model-name mismatch silently zeros all 5 Mercedes, both Volvos, plus partial BMW.

- **[CONFIRMED]** Reddit data is 70% empty per (vehicle, code) combo; backfill script exists, dry-run done, runtime ≈ 7.3h.

- **[ASSERTED]** "1.5–2 weeks of focused work" to transform raw (a) → training pairs (c) matching the 12-section format.
  → Fails how: This is the single largest unverified estimate in the doc and it's the work that *actually produces the training data*. There is **zero code** for the (a)→(c) transformation in the repo — `migrate_corpus.py` and `backfill_reddit.py` only manipulate raw blobs. No prompt-template generator. No QC harness. No teacher-model pipeline. No deduplication logic. No train/val/test split methodology written down. This estimate is a guess against a phase that has never been executed once. 1.5 weeks for a single high-school researcher to design + implement + QC + iterate a teacher-distillation pipeline producing ~5,700 well-formed 12-section examples is aggressive on a generous reading and fictional on a strict one.

- **[ASSERTED]** Deploying ClearDrive-Gemma to the A4500 server is achievable in ~6 weeks from today (May 10 → late June for option B, mid-July for C).
  → Fails how: Per `CLAUDE.md`, `ollama_client.py` is *dead code* wired to the wrong model. The Stream A backend rewire to point inference at A4500 is unscoped. Unsloth Studio install path on Blackwell, KV-share patching, sdpa attention, eval harness, GEPA reflection wiring, A4500 inference server stand-up — none of these are sequenced in the option set. The corpus question is being treated as the bottleneck. It probably isn't.

- **[ASSERTED]** Option B's "minimum viable" still produces a model whose output passes the iOS app's `parse_guidance()` 12-section parser reliably.
  → Fails how: `main.py:124` confirms the iOS parser keys on exact section headers. A model trained on a corpus where 70% of Reddit data is empty and 3 luxury brands have zero NHTSA grounding will hallucinate the "OTHER OWNERS REPORT" and "KNOWN ISSUES FOR THIS ENGINE" sections for those vehicles. That isn't a coverage gap — that's the model learning to fabricate when grounding is absent. This is worse than missing data.

- **[HOPED]** A WESEF judge will treat "raw scraped corpus" as a meaningful research artifact rather than asking "what was your held-out evaluation set, what's the baseline, what's the win rate."
  → Fails how: The decision frame here is *corpus quality*. WESEF/ISEF judges in CS/engineering categories ask about evaluation methodology, not training-corpus completeness. None of the three options says anything about the eval set, eval rubric, baseline model, or the GEPA reflection harness. You can ship perfectly clean data and still have nothing to defend at the fair if the eval is hand-wavy.

- **[HOPED]** July 2 → January 2027 (≈26 weeks) is enough to: deploy v1, run eval, iterate, run GEPA, re-eval, write paper, build poster, submit.
  → Fails how: 26 weeks of school-year evenings/weekends sounds long. It isn't. A single bad eval result in October triggers a re-train, which costs another week minimum on a 4B model with QLoRA r=128. Two iterations of "the model failed eval, fix the data, retrain" eats your entire runway.

- **[HOPED]** The Reddit backfill's projected ~50% hit rate (`backfill_reddit.py:67`) is real, not aspirational.
  → Fails how: The estimate is "assume ~50% of zero combos pick up a post." That's a guess in a comment. If actual hit rate is 10–20%, option C's main justification (Reddit backfill is high-impact) collapses, and you've spent 7+ hours of wall time and a week of attention on marginal data.

- **[HOPED]** Per the inventory, "5,700 distinct source documents" is enough signal to fine-tune Gemma 4 E4B into something measurably better than Groq Llama-3.1-8B baseline.
  → Fails how: A 4B model with QLoRA r=128 against a corpus where unique vehicle-level evidence is in the low thousands risks producing a model that's overfit to formatting and undertrained on substance. None of the options address corpus *augmentation* (paraphrase, synthetic perturbation, multi-template) — they're all about cleanup. Cleanup of 5,700 documents doesn't fix the n-size problem.

- **[ASSERTED]** "Documented methodological limitation" (option C's CarComplaints punt) is a defensible posture at WESEF.
  → Fails how: The fix is one line. `code_scraper.py:239` is a known deterministic bug affecting 21 (make, model) pairs across 39 vehicles — 13% of the corpus. Telling a judge "we knew about a one-line fix and chose not to apply it" is not a methodological limitation, it's a credibility hit. Especially after `GLC300_INVESTIGATION.md:138-141` already states it as the "lowest-risk change with the largest corpus impact."

LOAD-BEARING POINTS

The fragile things:

1. The 1.5–2 week (a)→(c) estimate is unsourced and dwarfs every other number in the decision. The corpus-cleanup question is small compared to the unbuilt transformation pipeline.
2. The deploy-by-July-2 deadline assumes the *backend* rewire of `ollama_client.py` and the A4500 inference stand-up happen in parallel and on time. Neither is scoped in this decision. If they slip, corpus cleanliness is irrelevant.
3. The decision frame conflates corpus quality with research quality. WESEF defense is won or lost on eval methodology, not corpus hygiene.
4. Option C calls a one-line fix a "methodological limitation." That language won't survive judge cross-examination, especially given the existence of `GLC300_INVESTIGATION.md` proving you knew.
5. Reddit backfill ROI is justified by a back-of-envelope "~50%" in a docstring comment. If actual hit rate is much lower, C degenerates into B with extra steps.

KILL SCENARIO

The single failure mode most likely to end WESEF:

**You ship a clean corpus on time, train a model in late July, and discover in September that the eval rubric doesn't exist, the baseline isn't defined, the held-out set was carved from the same corpus the model trained on, and the GEPA reflection loop was never wired.** None of the three options surface this. You spend Oct–Dec scrambling to retrofit an evaluation methodology onto an already-trained model, the numbers come out unconvincing, and you submit a poster about "fine-tuning a domain-specific LLM" without a defensible win-rate against a fair baseline. Judges ask "how do you know it's better than Groq Llama-3.1-8B?" and the answer is qualitative.

Per-option kill scenarios:
- **A kill:** 3 extra weeks of cleanup pushes the (a)→(c) build into late July. Training starts August. First eval is September. Bad eval → no time to iterate. WESEF poster shows v1 numbers, not a refined model.
- **B kill:** Mercedes/Volvo/BMW vehicles produce hallucinated "KNOWN ISSUES" output in TestFlight after deploy. Real users notice. The methodological gap becomes a product gap, and a judge spot-checking a GLC300 demo at the fair sees the model invent recall data.
- **C kill:** The "documented limitation" framing for the one-line CarComplaints bug gets specifically called out in judging Q&A. Compounds with whatever Reddit backfill actually delivered being lower than the 50% guess. Deploy slips to mid-July anyway because the (a)→(c) work was undersized.

NUMBERS / TIMELINES / COMPARISONS UNDER ATTACK

- **"1.5–2 weeks for (a)→(c)"** — no code exists for this phase. Estimate is a guess. Realistic range is 3–6 weeks for one researcher with school. This is bigger than the cleanup question being decided.
- **"Option A: +3 weeks"** — measured against what? The 1-week original plan? The 1.5–2 week (a)→(c)? Compounding estimates without a baseline schedule. Show the Gantt chart or the number is fiction.
- **"~50% Reddit pickup rate"** — a comment in `backfill_reddit.py:67`, not measured. The dry-run reportedly happened. What did it project? If it's not in this decision doc, why not.
- **"Deployed model end of June" (option B)** — 7 weeks from today. (a)→(c) build + train + eval + A4500 inference stand-up + backend rewire of `ollama_client.py` + smoke testing in 7 weeks while attending school. Implausible.
- **"WESEF January 2027 submission"** — 35 weeks from today. Deduct school finals weeks (≈4), holidays (≈2), poster/paper writing (≈4), unscheduled bad-eval iterations (≈4). Net working weeks: ~21. With one researcher. The decision should be sequenced against this, not against July deploy.
- **"5,700 distinct source documents"** — for a 4B-parameter fine-tune at r=128, this is not obviously sufficient. None of the three options addresses corpus size. They all just shuffle quality of the same 5,700.
- **"15,000 vehicle-code combos"** — this number is misleading throughout the decision doc. Per `corpus_stats.py:74-90`, four of five sources are memoized at the vehicle level. Do not let this number into a WESEF paper without a footnote.
- **Comparisons to baseline** — option set has no baseline. Better than what? Groq Llama-3.1-8B (currently in production)? Stock Gemma 4 E4B? You cannot pick a corpus-cleanup level without knowing what eval beats what threshold.

**Proposed Option D for consideration:** Apply only the one-line CarComplaints fix (10 minutes), run Reddit backfill in background overnight (zero attention cost while it runs), spend the freed 1+ weeks designing the eval rubric, baseline comparison, and GEPA harness *before* committing to the (a)→(c) build. Decide cleanup vs. transform sequencing against an actual eval target, not a deploy-by-July aesthetic.

## Executor

ALREADY BUILT (reusable)

- `backfill_reddit.py` (440 lines, fully wired, idempotent, resumable, dry-run validated) · repo root · ready to launch as-is. Self-estimates ~7.3h wall time, capped at `--max-hours 9`. Reuses `forum_scraper.search_reddit` + `get_post_comments`. Atomic writes, `backfill_at` stamp prevents re-work. **Just run it.**
- `migrate_corpus.py` (173 lines, idempotent NHTSA-400 cleanup + obd_codes strip) · repo root · already merged in d481e06. Apply once, never again.
- `corpus_stats.py` (213 lines) · repo root · use as the inventory ground truth before/after backfill, and use the same per-source counters as the basis for the State (a) -> (c) transformer.
- `code_scraper.py:239` CarComplaints `.title()` bug · single-line fix documented in `GLC300_INVESTIGATION.md` lines 138–141. Replace `base_model.title()` with `base_model`. ~30 minutes including a re-scrape of the 21 affected `(make, model)` pairs.
- `groq_client.py` system prompt (lines 33–42) · this IS the chat-template baseline. The fine-tune's system message must be byte-identical or `parse_guidance()` breaks.
- `main.py:1525-1593` 12-section format · this is the output target for every training pair. The transformer's job is "produce text matching this template."
- `scrape_training_data.py` memoization architecture · proves the corpus is `~5,700 distinct source documents`, not 15,000. Important framing for WESEF: don't claim 15k unique sources.
- `GLC300_INVESTIGATION.md` · this IS the methodological-limitations writeup. Reuse it verbatim in the WESEF paper's Data Quality section.

SMALLEST VIABLE NEXT STEP

**Tonight (May 11): launch `py -3 backfill_reddit.py --max-hours 9` as a detached overnight process. While it runs, fix the CarComplaints `.title()` bug on a feature branch.** Both finish by Tuesday morning May 12 with zero hands-on time during the run.

CRITICAL PATH (the 6 that matter)

1. **Run Reddit backfill** (overnight May 11 -> 12, zero touch). Cuts the 70% Reddit gap to whatever the broader query variants can recover.
2. **Fix CarComplaints `.title()` bug + re-scrape the 21 affected (make, model) pairs** (May 12, ~2 hours).
3. **Build the State (a) -> (c) transformer** (May 13 — May 31, ~2.5 calendar weeks). Read each per-vehicle blob + per-(vehicle, code) blob, emit one training pair per combo matching the `main.py` 12-section format. Use Groq or Claude as the silver-label generator (cite as such).
4. **Write up data-quality limitations** (June 1, ~half a day). Convert `GLC300_INVESTIGATION.md` into the paper's Data Quality section.
5. **Train QLoRA r=128 on RTX 5090** (June 2 — June 21, 3 calendar weeks for first credible run including Unsloth Studio install pain, KV-share bugs, chat-template debugging, and at least one full restart).
6. **Deploy to A4500 + rewire `ollama_client.py`** (June 22 — July 5).

CUT (not on critical path)

- **NHTSA model-name normalization for Mercedes/Volvo/BMW** (Option A and Option C both include this). Skip it. Mechanical name-mapping fix sounds easy but means rerunning the scraper for 9 vehicles, integrating new data into already-transformed pairs, and re-running corpus_stats. That's a week of fiddly work for ~3% of the corpus.
- **RepairPal re-fetch for GLC300/GLE350.** Document and move on.
- **OBD-Codes.com Cloudflare workaround.** Already removed.
- **Variant-1 Reddit re-issue** (the `--include-variant-1` flag). Skip.
- **Hardcoded API key rotation in `vehicle_data.py`** is critical for security but **not on the WESEF critical path** — flag as separate ticket.

REAL TIMELINE

| Date | Milestone | Confidence |
|---|---|---|
| May 11 (tonight) | Launch `backfill_reddit.py` overnight | High |
| May 12 | CarComplaints fix + 21-pair re-scrape merged | High |
| May 13 | Backfill done, corpus_stats re-run, baseline locked | High |
| May 13 — May 31 | State (a) -> (c) transformer (~25 hands-on hours around school) | Medium |
| June 1 | Data Quality writeup | High |
| June 2 — June 21 | First credible QLoRA run on 5090 | Low-Medium |
| June 22 — July 5 | A4500 deploy, ollama_client rewire, smoke tests | Medium |
| July 2 target | Model deployed | **Hits with ~3 days of slack** |

**Honest assessment of which option to pick:**

- **A is gold-plated.** The extra 3 weeks doesn't change the WESEF outcome.
- **B is brittle.** A 70% Reddit empty rate is the kind of single number a judge will fixate on.
- **C is right, but trim it.** Run Reddit backfill (free — overnight). Fix CarComplaints (free — one line). **Skip the NHTSA model-name normalization.**

**Effectively: C-minus = "C without the NHTSA fix."** Saves ~1 calendar week vs full C, gap is fully defensible because you have the diagnostic in `GLC300_INVESTIGATION.md`.

GOLD-PLATING FLAGGED

- NHTSA model-name normalization layer (Options A and C). Costs a week. Recovers ~3% of corpus.
- vPIC pre-flight resolution at scrape startup. Architecturally correct, completely unnecessary for WESEF.
- Re-fetching the 2 RepairPal-transient vehicles. It's 2 vehicles. Document and ship.
- Re-running variant 1 of Reddit with `--include-variant-1`. Doubles backfill time for zero new data.
- Worrying about whether 16-bit LoRA beats QLoRA r=128 before the corpus is even transformed.
- Anything in `ollama_client.py` before the model is trained.

## Expansionist

ADJACENT RESEARCH DOMAINS

- **Quality-vs-quantity SFT literature** · Zhou et al. (LIMA, Meta AI 2023) · Chen et al. (AlpaGasus, ICLR 2024) · Li et al. (Superfiltering / IFD scoring, NAACL 2024) · Databricks (LIMIT, 2024) · Sai et al. ("Is Training Data Quality or Quantity More Impactful to SLM Performance?" arXiv:2411.15821, Nov 2024). The consensus has hardened in 2024–2025: for instruction/SFT-style alignment, **diversity and response quality dominate raw count once you cross a low threshold (~1k–10k well-curated examples)**. This is the most important framing for your decision — it pushes you toward C, hard.

- **Capability-gap diagnosis** · Microsoft Research GoalCover (2025, "Diagnosing Capability Gaps in Fine-Tuning Data") · the framework is *literally* about systematically detecting which capabilities your dataset fails to support. There's a citation here that says "we ran a structured gap analysis before training" — which is exactly what your `corpus_stats.py` + `GLC300_INVESTIGATION.md` already are. Cite this.

- **Domain SFT on small medical corpora** · Singhal et al. Med-PaLM (Nature 2023) · AlpaCare (2023) · 3DS (Decomposed Difficulty-based Data Selection, Oct 2024) · Zhao et al. on cardiology reports (arXiv:2503.21349, March 2025 — "notable gains observed with as few as 200–300 training examples"). The medical SLM precedent is directly transferable.

- **Dataset documentation as methodology** · Gebru et al. Datasheets for Datasets (CACM 2021) · Google Data Cards. The standard frame for "we accept this gap" is to write a datasheet that names the gap explicitly, classifies it (sampling bias vs. coverage bias vs. annotation noise), and reports its measured magnitude. You already have the measurements.

- **Data ablation as a research artifact** · Magnusson et al. ("Scalable Data Ablation Approximations for Language Models," EMNLP 2024). Even a small "with-vs-without-Reddit" eval comparison turns your gap into a *finding* rather than a *limitation*.

- **Selection bias in NLP corpora** · Dirk Hovy ("Five Sources of Bias in NLP," Wiley 2021). Your Mercedes/Volvo NHTSA gap is textbook *selection bias from upstream API canonicalization*; that's a cleanly nameable thing in a paper.

IMPACT NARRATIVE BEYOND WESEF

The corpus-cleanup decision sits inside a bigger narrative arc. The audiences ClearDrive ultimately serves are: independent rural mechanics without dealer-level scan tools, owners of 8–15-year-old vehicles (the median U.S. vehicle is now ~12 years old), accessibility users who can't easily read OEM service manuals, drivers in regions where the nearest dealer is 100+ miles away. **Your three luxury brands (Mercedes, Volvo, BMW) are the *least* representative of those audiences.** A corpus that under-covers GLC300s but over-covers F-150s and Camrys is, if framed correctly, *closer* to the deployment population, not further from it. There is a real argument here that B/C is not just "good enough" but *more aligned with intended use* than A.

METHODOLOGY GENERALIZATIONS

- Medical symptom triage SLMs: same long-tail diagnostic pattern.
- Agricultural equipment diagnostics (John Deere/Kubota fault codes): worse public-corpus coverage than OBD-II.
- Marine diagnostics (NMEA 2000): even sparser.
- Industrial IoT predictive maintenance: vendor-specific codes, even more fragmented.

The generalizable methodological contribution is: *a reproducible pipeline for building deployable domain SLMs from sparse heterogeneous public sources, with an explicit per-source coverage audit as a first-class artifact*. That's a more interesting WESEF/ISEF framing than "we built a car diagnostics model."

LIT-REVIEW GAPS

Papers to add to the bibliography:
- **Zhou et al., "LIMA," arXiv:2305.11206 (NeurIPS 2023)** — canonical "1k carefully curated >> 10k mediocre."
- **Sai et al., arXiv:2411.15821 (Nov 2024)** — *the* SLM-specific quality>quantity paper.
- **Chen et al., "AlpaGasus," ICLR 2024** — 9k high-quality outperforming 52k Alpaca.
- **Microsoft Research GoalCover (2025)** — cite as the framework you used to identify gaps.
- **Gebru et al., "Datasheets for Datasets," CACM 2021** — pair with a `DATASHEET.md` in `training_data/`.
- **Hovy & Prabhumoye, "Five Sources of Bias in NLP" (2021)** — vocabulary to name each bias.
- **Magnusson et al., EMNLP 2024** — cite if you do a with-vs-without Reddit ablation.
- Med-PaLM, AlpaCare for "domain SLM with documented small corpus" precedent.

LONG-RUN NARRATIVE

The story you want to tell at every stage:

> "I built a deployable domain SLM from sparse public sources for a real iOS app with real users. Before training I ran a structured per-source coverage audit, identified six categorizable gaps, made principled engineering tradeoffs about which to fix, documented the rest as known limitations with measured magnitudes, and ran ablations to show the model still performs."

That story is *stronger with a documented gap than with a hidden one*. Option A erases your investigation work from the narrative. Options B and C preserve it. The corpus-audit infrastructure (`corpus_stats.py`, `GLC300_INVESTIGATION.md`, the methodology around `backfill_reddit.py`) is *itself* a research artifact — possibly the most novel and reusable one in the project.

5-year arc: WESEF/ISEF (the audit-driven SLM build) → undergrad year 1–2 (port the audit pipeline to a second domain) → year 3–4 (the audit-driven domain-SLM methodology becomes a reusable framework). The ClearDrive corpus is the seed; the *methodology* is the commercial/academic payload.

ANSWERS TO THE FOUR DECISION QUESTIONS

1. **Is B's 70% Reddit gap defensible?** Defensible *only* if you also document it, measure its impact via ablation, and frame it as a deliberate scope choice. The defense isn't the gap size, it's whether you anticipated and characterized it.
2. **Does A's extra 3 weeks meaningfully change WESEF outcome?** Almost certainly not, given the LIMA/AlpaGasus/Sai-2024 evidence.
3. **Fourth option (D)?** **D · C-plus-ablation.** Do exactly what C does, then on the trained model run a *with-Reddit vs. without-Reddit* and a *with-Mercedes-data vs. without-Mercedes-data* ablation eval. Cost: ~2 days of eval scripting. Payoff: every gap becomes a *measured methodological finding* rather than a footnoted limitation.
4. **Failure modes per option:**
   - A: Slips past mid-July; corpus rework eats GEPA/eval/deployment time.
   - B: Reddit gap discovered in Q&A; no ablation evidence to defend with.
   - C: Mercedes/Volvo gap discovered in Q&A; smaller surface area than B.
   - D: None of the above, *if* the ablation is actually executed.

**Recommendation:** D. Take Austin's C, add the ablation step, treat the audit work as a first-class research artifact, and write the datasheet now while the gap analysis is fresh.

## First Principles

GENUINELY IMMOVABLE

- Hardware: RTX 5090 (training), RTX A4500 (inference)
- Calendar: WESEF March 2027; research period July 2 2026; mid-July deploy slip ceiling
- The research plan you submitted May 4: 4 hypotheses, 5 conditions, named mentor — public commitments
- Gemma 4 E4B as the base model (settled, public)
- The 12-section iOS prompt format **for the production app** (TestFlight users, parse_guidance() in main.py)
- Ethical limits on the H3 comprehension study
- Vehicle safety: the model cannot be allowed to confidently mis-diagnose

ACCUMULATED DECISIONS (revisitable)

- **300 vehicles × 50 P-codes = 15,000 combos** · Original reason: "biggest scrape that fits in 8h overnight." · Does it still hold? **No, this is a budget-shaped decision masquerading as a methodology one.** None of H1–H4 require 300 vehicles.

- **5 sources per vehicle** · NHTSA complaints + RepairPal carry the load. CarComplaints duplicates NHTSA narratives. Reddit at 70% empty is mostly noise. OBD-Codes is gone. A 2-source corpus (NHTSA + RepairPal) answers the same hypotheses with cleaner provenance.

- **12-section structured output as the fine-tuning target** · The iOS app needs 12 sections at *inference*. The fine-tune needs the model to learn vehicle-specific reasoning. You can train on a simpler intermediate (3–6 fields covering cause, severity, action) and add the cosmetic sections back via a thin wrapper prompt or a second tiny SFT pass.

- **Reddit as a corpus source at all** · With a 70% empty rate, Reddit is currently a per-vehicle ornament, not a per-(vehicle, code) ground truth.

- **CarComplaints as a corpus source** · Cutting it removes the bug, removes 39 vehicles' worth of empty fields, and loses almost no unique signal.

- **Backfill_reddit.py exists and is ready** · This is sunk cost. The script working doesn't mean the data is worth waiting 7–9 hours for.

IF STARTING TODAY

If you sat down on May 10 with the WESEF deadline and no prior code, the corpus you'd build is roughly:

- **~75–100 vehicles**, chosen for diversity (3 powertrain families × ~6 makes × 2 model years), not 300
- **~25 P-codes**, the high-clinical-value ones, not 50
- **2 sources**: NHTSA (complaints + recalls) and RepairPal
- **No Reddit** in training data — keep it as a *retrieval* layer at inference time if you want
- **A simpler intermediate format** for fine-tuning (4–6 fields). Production 12-section output reconstructed by a deterministic post-processor

That corpus is ~2,500 combos, deterministically clean, no scraper bugs, no naming-mismatch artifacts, and you could rebuild it from scratch in a single weekend.

SIMPLEST VERSION TESTING H1–H4

(I don't have H1–H4 in front of me. Adjust if a hypothesis specifically requires Reddit-vernacular learning or 5-source attribution.)

1. **Re-scope corpus** to the 75–100 vehicle / 25 code / 2 source target. ~3 days, including the model-name normalization fix.
2. **Skip the Reddit backfill entirely.** Drop Reddit from training. Document as deliberate exclusion.
3. **Skip the CarComplaints fix.** Drop CarComplaints. Document as exclusion.
4. **Fix the NHTSA model-name bug** for Mercedes/Volvo/(BMW partial). ~1 day.
5. **Transform to (c) against the simpler 4–6 field intermediate.** ~1 week instead of 1.5–2.
6. **Train.** Late June deploy is back on the table.

Net: deploy ships *earlier* than option B, with cleaner data than option A.

DIRECT ANSWERS

1. **B's 70% Reddit gap defensible?** Only if you frame it as *exclusion*, not gap. "Sparse, excluded" is methodologically clean. "We tried Reddit and 70% came up empty but we kept it anyway" is the version a judge calls out.
2. **A's extra 3 weeks meaningful?** No. A WESEF judge cannot evaluate corpus completeness — they evaluate whether the methodology is justified and whether the model demonstrably works.
3. **Fourth option?** Yes — **D: Re-scope down, not clean up.** Drop scope (vehicles, codes, sources) instead of polishing existing scope.
4. **Failure modes:** A → August deploy → no eval before WESEF. B → "we kept Reddit anyway" implies time-shaped methodology. C → cleanup time spent, no slack to iterate on the actual research question. D → tearing down done work; psychological + procedural risk.

COMPLEXITY NOT ON THE PAPER

- The Reddit backfill script (`backfill_reddit.py`) — addresses a source you probably shouldn't include
- The CarComplaints case-bug fix — fixes a source that duplicates NHTSA
- The NHTSA model-name normalization layer — useful, but only for vehicles you keep
- The full 12-section output during training — production format pressure on a research artifact
- The 5-source memoization scaffolding — engineering effort proportional to the source count, which should drop

The cheapest fix isn't to clean the corpus — it's to right-size it.

**Note: `notes/decisions.md` and prior council verdicts do not exist yet. If H1–H4 specifically depend on Reddit vernacular or 5-source attribution, options B/C become more attractive than option D — flag this back if so.**

## Outsider

JARGON I DON'T UNDERSTAND
- "Gemma 4 E4B" · the artifact never says what this is, why it was chosen, or what "E4B" means
- "ClearDrive-Gemma" · undefined; I assume it's the fine-tuned variant but the artifact doesn't say
- "A4500 server" · undefined hardware; no spec, no constraints
- "WESEF" · undefined acronym; I'd guess a science fair but the artifact never says
- "P-codes" · I assume OBD-II diagnostic trouble codes but a non-expert wouldn't know
- "12-section structured prompt format" · referenced but never enumerated
- "State (a) raw scraped data" / "State (a) → (c)" · references an a/b/c taxonomy that's never defined; what is (b)?
- "NHTSA" · undefined acronym
- "CarComplaints" / "RepairPal" / "OBD-Codes.com" · listed as sources, no description of what each contributes
- "Reddit backfill" · what is it backfilling? With what?
- "memoized per vehicle" · what does this mean for a corpus?

MISSING CONTEXT (a stranger would want this)
- What problem does the fine-tuned model actually solve? What does it output?
- What does "deployed model" mean — research evaluation, end users, both?
- What's the relationship between July 2 deployment and January 2027 submission?
- What's the eval plan? Without knowing how the model will be judged, I can't reason about whether corpus gaps matter.
- Who are the five data sources, and what does each contribute? Three are "memoized per vehicle" — which three?
- What's the baseline? Is there a comparison model, a previous attempt, a benchmark?
- What's the consequence of slipping the deployment date past mid-July?
- Why is on-device iPhone deployment relevant to a corpus-cleanup decision?
- "9 affected vehicles" out of 300 — so 3%. Is that material?

FIRST JUDGE QUESTIONS (after one 5-minute read)
1. What does this model do, in one sentence, that a non-fine-tuned model can't?
2. Why does Reddit data matter — what specifically does it add that NHTSA/CarComplaints/RepairPal don't?
3. If 70% of Reddit cells are empty, were they empty because Reddit has no data on those combinations (a real-world signal) or because the scraper failed (a bug)? Those are very different problems.
4. The corpus is 300 vehicles × 50 codes = 15,000 cells, but you say there are only ~5,700 distinct source documents. So what's the actual training-pair count after transformation, and is that enough to fine-tune anything?
5. How will you evaluate the model? Without that, "cleaner data is better" is unfalsifiable.

HANDWAVED vs SOLID
- SOLID · "5.3 GB, 15,000 JSON files across 300 vehicles × 50 P-codes" · concrete, countable
- SOLID · "Reddit data 70% empty (10,481 of 15,000 vehicle-code combos)" · specific number, falsifiable
- SOLID · the per-option deployment dates · commits to a calendar
- SOLID · "21 make/model pairs 404" for CarComplaints · countable
- HANDWAVED · "Estimated 1.5–2 weeks of focused work" for (a)→(c) · no breakdown, no risk buffer
- HANDWAVED · "+3 weeks of corpus work vs original 1-week plan" · where does 3 weeks come from?
- HANDWAVED · "Cleanest data" (Option A) · cleanest by what metric?
- HANDWAVED · "high-impact, low-effort" (Option C, Reddit backfill) · impact on what outcome?
- HANDWAVED · "Accept CarComplaints casing bug as a documented methodological limitation" · what does "documented" mean here?
- HANDWAVED · the entire decision frame assumes corpus quality is the binding constraint on model quality, but that's never argued

IMPLICIT AUDIENCE

This reads like it's written for someone already deeply embedded in the project. It is not written for a judge, a reviewer, or a future-self-in-2027 trying to reconstruct why this decision was made. The deployment dates and option labels (A/B/C) are decision-ready, but the reasoning is invisible. If the audience is the council, that may be fine; if it's anyone else, the artifact assumes too much.

GENERAL IMPRESSION

The artifact is structurally clean — three options, four decision questions, concrete dates and counts — but it asks the reader to evaluate a tradeoff (data quality vs schedule) without giving them the two things needed to evaluate it: (1) what "good enough" data looks like for this fine-tune, and (2) what failure of the deployment date actually costs. The biggest unstated assumption: that corpus cleanup is the right thing to be optimizing right now, as opposed to, say, locking down the eval harness or de-risking the on-device deployment path. **Option D might be "stop debating the corpus and go figure out whether the model even runs on an iPhone."**

---

## Synthesis

### Convergent points (3+ members agreed)

1. **Option A is wrong.** All four context-aware members (Contrarian, Executor, Expansionist, First Principles) reject it. Three independent reasons converge: extra 3 weeks doesn't change WESEF outcome (Executor, Expansionist), the literature on quality-over-quantity makes "more clean data" the wrong axis to optimize (Expansionist's LIMA/AlpaGasus/Sai-2024 citations), and the slip risk is asymmetric — A's failure mode pushes eval into August/September with no time to iterate (Contrarian).

2. **The corpus question is being treated as the bottleneck. It probably isn't.** Contrarian: the eval rubric, baseline, held-out set, and GEPA harness are unaddressed in any option. Executor: the (a)→(c) transformation is the actual unbuilt load-bearing work and dwarfs the cleanup question. First Principles: corpus *right-sizing* is more powerful than corpus *cleanup*. Outsider (cold read, no project context): "the entire decision frame assumes corpus quality is the binding constraint on model quality, but that's never argued."

3. **The "1.5–2 weeks for (a)→(c)" estimate is unsourced and probably under-estimated.** Contrarian: zero code exists for this phase; realistic range is 3–6 weeks. Outsider independently flagged the same as the most handwaved estimate in the doc. Executor budgeted 2.5 weeks of calendar time but acknowledged it's the medium-confidence step.

4. **Documenting gaps is methodologically stronger than hiding them.** Expansionist: Datasheets for Datasets and the Capability Gap Diagnosis literature explicitly frame this as best practice. First Principles: framing as deliberate exclusion beats framing as time-pressured gap. Contrarian: agrees, but warns that "documented limitation" for a one-line fix is a credibility hit.

5. **Reddit's value as a *training* source (vs. inference-time retrieval) is suspect.** First Principles wants it dropped from training. Contrarian flagged that the "~50% pickup rate" is an unmeasured guess. Expansionist: should be settled by ablation. Outsider: should be settled by understanding *why* it's empty (real signal vs. scraper bug). Only Executor wants to run it as-is.

### Real disagreements (highest signal)

1. **What "D" actually means.** Three different proposals emerged, and they're substantively different:
   - **Executor's "C-minus":** run Reddit backfill, fix CarComplaints, *skip* NHTSA name normalization, build transformer immediately. Cleans current scope minimally.
   - **First Principles' "D":** tear down the 300×50 scope. Rebuild as ~75–100 vehicles × ~25 codes × 2 sources (NHTSA + RepairPal), drop Reddit and CarComplaints from training entirely, simpler intermediate training format.
   - **Expansionist's "C-plus-ablation":** keep Austin's C as-is, add an ablation step on the trained model to measure what each gap actually costs.

2. **Whether to fix the CarComplaints `.title()` bug.** Executor: yes, 30 minutes for a 13% corpus fix. First Principles: no, drop CarComplaints entirely (overlaps NHTSA). Contrarian: not fixing it while documenting it is worse than either fixing or dropping.

3. **Whether to spend May 10–14 on corpus or on eval design.** Contrarian's proposed D: spend the freed week designing the eval rubric, baseline, and GEPA harness *before* committing to the (a)→(c) build. Executor: start the transformer Tuesday. These are mutually exclusive use of the same calendar.

### Unique contributions

- **Contrarian:** Surfaced the actual WESEF-killer scenario — a clean corpus with no eval methodology produces a poster you can't defend in Q&A. Also: deploying anything by July 2 assumes the `ollama_client.py` rewire and A4500 stand-up happen on time, neither scoped in any option.
- **Executor:** Concrete day-by-day schedule. Reusable artifacts inventory: `groq_client.py:33-42` is the chat-template baseline; `main.py:1525-1593` is the training pair output target. API key rotation is critical-but-separate.
- **Expansionist:** The literature push-back is decisive — LIMA, AlpaGasus, Sai 2024 collectively make A indefensible. Also: the under-coverage of luxury European brands aligns with the *intended deployment population* (rural mechanics, older vehicles), so B/C may be *more* representative than A. Long-run framing: the audit infrastructure itself is the most novel contribution, not the model.
- **First Principles:** Most aggressive and most coherent reframe. The 300×50 scope was a budget-shaped decision, not hypothesis-driven. A simpler training intermediate (4–6 fields) decoupled from the production 12-section format opens up an entirely cleaner methodology.
- **Outsider:** Independently arrived at "the corpus may not be the binding constraint" with zero project context. Strong signal — the decision document doesn't make its premise visible to a stranger, which means it doesn't make it visible to a judge either.

### Recommended decision (decision-support, not the decision)

**The strongest recommendation that synthesizes all five is closer to Contrarian/Outsider than to A/B/C: defer the corpus cleanup question by one week, lock the eval methodology first, and run the zero-cost cleanups in parallel.**

Concretely:

- **Tonight (May 10–11):** Launch `backfill_reddit.py --max-hours 9` overnight. Zero attention cost. (Executor's call.)
- **May 11–14 (the freed week):** Define the eval rubric, baseline (Groq Llama-3.1-8B vs stock Gemma 4 E4B vs ClearDrive-Gemma), held-out set construction (stratified by vehicle make and code commonality), and GEPA harness wiring. **This is the work the council just identified as more load-bearing than A/B/C.** (Contrarian's call, supported by Outsider's "what does success look like" question.)
- **May 12 in parallel:** Fix CarComplaints `.title()` bug + re-scrape 21 affected pairs. ~30 min of work, queue while you're working on eval design. (Executor's call.)
- **May 15:** Decide A/B/C/D/D-prime *against the locked eval requirements*, not against a deploy-by-July aesthetic. If the eval requires Reddit per-(vehicle, code), backfill results inform; if not, Reddit is excluded cleanly. If the eval requires luxury-brand stratification, NHTSA name fix is mandatory; if not, it's gold-plating.
- **May 18 onward:** Build (a)→(c) transformer, having now scoped it against actual eval requirements rather than the 12-section production format by default. **Strongly consider First Principles' simpler-intermediate proposal** — train on 4–6 load-bearing fields, reconstruct production 12-section output via wrapper. This decouples research methodology from production pressure.

This isn't a clean A/B/C answer. It's the council saying: **the question itself is mis-framed, and the right move is one more week of design before committing to a corpus level.** Three of five members independently arrived at this from different angles.

If you must pick A/B/C/D as posed and can't add the design week: **C-minus + plan for ablation** — Executor's pragmatic schedule with Expansionist's ablation step bolted on after training. Lowest-risk version of "ship something defensible."

### Open questions for Austin or Makarov

1. **Share H1–H4 with the council.** Multiple members noted they couldn't reason about whether the corpus design fits the hypotheses without seeing them. First Principles explicitly flagged: "If H1–H4 specifically depend on Reddit vernacular learning or 5-source attribution, options B/C become more attractive than option D — flag this back if so."

2. **For Makarov specifically:** Does he have a recommendation on eval rubric design for domain-SLM fine-tunes? The council's strongest signal is that mentor input on eval methodology is more load-bearing right now than a corpus cleanup decision.

3. **Sequencing question:** Is the `ollama_client.py` rewire + A4500 inference stand-up scoped anywhere? Contrarian noted that if these slip, all corpus questions are moot. This may be a separate council-worthy item.

4. **The 12-section format question:** Is the iOS app's `parse_guidance()` strict requirement load-bearing for the *training* corpus, or only for inference-time output? First Principles' simpler-intermediate proposal hinges on this distinction.

---

*Recommended decision is decision-support, not the decision itself. Austin decides.*

## Austin's decision

*(left blank for Austin to fill in)*

## Follow-up tasks

- [ ] Share H1–H4 with the council before the next session (load-bearing missing context flagged by 3 members)
- [ ] Decide whether to add an "eval methodology lock-down" week before committing to A/B/C/D
- [ ] (Zero-cost, can run regardless of decision) Launch `backfill_reddit.py --max-hours 9` overnight tonight
- [ ] (Zero-cost, can run regardless of decision) Fix `code_scraper.py:239` CarComplaints `.title()` bug + re-scrape 21 affected pairs
- [ ] Confirm with Makarov asynchronously: eval rubric and baseline definition methodology
- [ ] Open separate council session if needed: scoping for `ollama_client.py` rewire + A4500 inference stand-up
- [ ] (Optional) Consider First Principles' simpler-intermediate training format (4–6 fields, reconstruct 12-section via wrapper) — needs explicit yes/no
- [ ] Rotate hardcoded API keys in `vehicle_data.py` (separate ticket — Executor flagged as critical-but-not-WESEF-critical-path)

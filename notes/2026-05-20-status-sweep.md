# ClearDrive status sweep — 2026-05-20

Report-only. No code changes, no PR actions, no optimization. Facts as observed on 2026-05-20.

One blocker up front: **Section 2 (live A4500 diagnostic) could not be executed this session** — SSH key auth to `abrennan@100.100.254.15` is unavailable (no private key on disk in `~/.ssh`, both git-bash and Windows ssh-agents empty; `Permission denied (publickey,password)`). The diagnostic needs an interactive credential I don't have. The May-18 documented numbers are reported instead, with the caveat that they are decode-only.

---

## SECTION 1 — Git state

### PR status

| PR | Title | State | Merged/Updated | Blocker comments |
|---|---|---|---|---|
| #6 | Reddit backfill script + GLC300 investigation | **MERGED** | 2026-05-18 | none |
| #7 | Post-council cleanup: env-var secrets, Groq cut, CarComplaints fix | **MERGED** | 2026-05-18 | One comment (informational, not a blocker): documents A4500 Ollama install `fde8cbd`; lists "remaining gating items" that mention a *PaaS dashboard* — **stale**, superseded by the no-PaaS topology in PR #10/CLAUDE.md |
| #8 | Baseline format-validation experiment | **MERGED** | 2026-05-18 | none |
| #9 | Force LF on .claude/ files so /council loads | **MERGED** | 2026-05-18 | none |
| #10 | ETL pre-flight: council resolution, decisions log, ml/ scaffold, CarsXE audit + hotfix | **MERGED** | 2026-05-18 | none |
| #11 | Canonical OBD dict expansion + A4500 diagnostic + 418-entry JSON | **OPEN** | 2026-05-18 | One comment (own status summary). **Awaiting review/merge.** PR title undersells contents — also carries the A4500 diagnostic (`098bc49`) and 418-entry `sae_j2012.json` (`52c1230`) |

### `origin/main` — last commits (all 2026-05-18 except noted)

```
9a5da27  Merge PR #10 (ETL pre-flight)            <- main HEAD
ff1a0f5  Hotfix P0420 description override
cd5a93f  Audit CarsXE decode corruption (10 codes)
7c20a8b  Create ml/ subdirectory
6940f88  Seed notes/decisions.md
0c9e5dc  Resolve 2026-05-10 council session: option C
6c2f0a6  Merge PR #9 (CRLF cleanup)
4a5278f  Merge PR #8 (baseline validation)
54281c9  Force LF line endings on .claude/
e8f0084  Baseline format-validation experiment
18cd60c  Merge PR #7 (post-council cleanup)
7996f0a  Merge PR #6 (Reddit backfill + GLC300)
345f028  docs: deployment topology (A4500 + tunnel, no PaaS)
7151d3d  Wire A4500 Ollama: env-var host, /api/chat
b07b6df  Move API keys to env vars; remove Groq
8ce5971  Fix CarComplaints .title() bug + backfill
41ca8b0  Add council infrastructure + project rules
96b6aca  (2026-04-26) Reddit backfill script + GLC300 investigation
57efd49  (2026-04-25) Merge PR #5
f22bf6f  (2026-04-25) Fix NHTSA empty-result + remove OBD-Codes
```

### Other branches / open work

- **Only PR #11 is open.** All of #1–#10 merged.
- **`feat/canonical-codes-expansion`** = the PR #11 branch (current checkout). Two commits ahead of main not yet merged: `098bc49` (A4500 diagnostic) + `52c1230` (418-entry lookup), plus earlier acd96a2/df4447b/018dcb6/5716bc2/ddb7496.
- Stale local/remote branches with no open PR (merged or abandoned): `docs/claude-md-reconcile`, `feat/baseline-gemma-format-validation`, `feat/research-logging`, `feat/training-data-scraper-v2`, `feat/training-data-scraping`, `fix/nhtsa-empty-results-remove-obd-codes`, `revert/initial-scraper`, `origin/feat/etl-pre-flight-2026-05-18`, `origin/fix/claude-md-line-endings`. **Candidates for cleanup** — none represents active work.

---

## SECTION 2 — A4500 diagnostic ⚠️ NOT RE-RUN THIS SESSION

**Could not execute the live Step-0 diagnostic.** SSH key auth to the A4500 is unavailable this session (no private key in `~/.ssh`, ssh-agents empty → `Permission denied (publickey,password)`). Re-running requires loading the SSH key / starting the agent (interactive — your action).

### Correction to the brief's premise

The brief states "the 105 tok/sec figure was reported verbally but never documented." **It is documented** — `notes/2026-05-18-a4500-optimization.md` is a full diagnostic write-up with captured numbers:

| Metric | Documented value (2026-05-18) | Source |
|---|---|---|
| GPU utilization (peak) | **94%** | `nvidia-smi` 1s sampling |
| GPU utilization (sustained) | ~92% | same |
| Power state | **P2** (active, not P8) | same |
| Power draw (peak) | **199.44 W** (at 200 W TDP) | same |
| VRAM used | 9,741 MiB / 20,470 MiB (no offload) | same |
| eval rate (decode) | **104.00 tok/s** (Step 0); 104.24 mean of runs 2–3 (Step 3) | `ollama run --verbose` |
| Processor | 100% GPU (no CPU offload) | `ollama ps` |

### What is NOT in the documented numbers (the brief's specific asks)

- ❌ **Prompt eval rate (prefill) is NOT separated from decode.** The May-18 note records only the decode/`eval rate` (104 tok/s). Prefill throughput was never captured separately. **This remains genuinely unknown** and is the one number a re-run would add.
- ❌ Total wall time per response and exact response token count per run are partially in the note (run table shows `eval count` 1883–2365 tokens, load durations 176 ms–3.32 s) but total durations weren't tabulated.

### Verdict on "is 105 tok/s real"

Documented as real **for decode**, on a hot model, single request. The PR #8 "35 tok/s" was end-to-end `/interpret` (scrapers + APIs + LLM), not pure LLM. **Whether prefill is the hidden cost is still open** — needs the re-run once SSH is restored. I can run the full prefill-vs-decode diagnostic the moment auth works.

---

## SECTION 3 — notes/ folder inventory

| File | Last modified | Contents |
|---|---|---|
| `decisions.md` | 2026-05-18 | Append-only decisions log. **Reflects Gemma 4 E4B — NO Qwen pivot recorded** (see §6). Captures PR #8 baseline, 3 ETL pre-flight items, hybrid synthesis design, Option-C corpus decision |
| `2026-05-18-a4500-optimization.md` | 2026-05-18 | A4500 diagnostic — **has actual measurements** (104 tok/s, 94% GPU, 199 W). Decode only, no prefill split |
| `2026-05-18-carsxe-decode-audit.md` | 2026-05-18 | PR #10 audit of CarsXE wrong-decode across 10 sample codes (~60% wrong-decode rate found) |
| `2026-05-18-carsxe-independent-verification.md` | 2026-05-18 | Raw-`curl` re-verification (no Python wrapper) confirming the bug is CarsXE-side; offset analysis (6/7 = −1 offset) |
| `2026-05-18-carsxe-support-ticket-draft.md` | 2026-05-18 | **DRAFT, not sent.** Polished ticket for Austin to review + send manually |
| `baseline-gemma-format-validation-2026-05-18.md` | 2026-05-18 | PR #8 full baseline (136 KB): 20 scenarios, 3.5/12 format mean, 35% degenerate, 44 s latency |
| `council/decisions/2026-05-10--corpus-cleanup-before-training.md` | 2026-05-18 | Full 5-member council session + synthesis + **Austin's decision: Option C** |
| `carsxe-raw-responses/` | 2026-05-18 | Raw CarsXE JSON captures backing the verification note |

### Specific status checks requested

- **`decisions.md` — Qwen or Gemma?** → **Still Gemma 4 E4B.** No Qwen mention anywhere in the file or repo.
- **`2026-05-18-carsxe-independent-verification.md`** → ✅ exists.
- **A4500 optimization note with measurements** → ✅ `2026-05-18-a4500-optimization.md`, has real numbers (decode only).
- **`notes/baseline_validation_rerun.md`** → ❌ not in `notes/`. It lives at **`scripts/baseline_validation_rerun.md`**. Status: **Queued, NOT run.** Has NOT been re-run with the hotfix.
- **`notes/council/decisions/`** → one verdict recorded: 2026-05-10 corpus-cleanup → **Option C (Hybrid)**.
- **`2026-05-18-carsxe-support-ticket-draft.md`** → ✅ exists, **DRAFT / not sent.**

---

## SECTION 4 — Corpus state

Source: `py corpus_stats.py` over `training_data/raw/` (2026-05-20 run).

| Metric | Value |
|---|---|
| Total disk | 5,326.9 MB (~5.33 GB) |
| Total JSON files | **15,000** (300 vehicles × 50 codes) |
| Vehicle dirs | 300 |
| Distinct source docs (after per-vehicle memoization) | ~5,700 (do NOT cite 15,000 as unique in the paper) |
| JSON parse errors | 0 (all clean) |

### Per-source coverage (n=300 vehicles)

| Source | avg | median | vehicles with zero |
|---|---|---|---|
| NHTSA complaints | 279.2 | 139 | 28/300 |
| NHTSA recalls | 5.2 | 4 | 26/300 |
| RepairPal items | 13.2 | 14 | 2/300 |
| CarComplaints | 0.8 | 1 | **54/300** |
| Reddit (per vehicle×code, n=15,000) | 5.92 | **0** | **9,727 combos zero (64.8%)** |

### Reddit backfill — ⚠️ DID NOT FINISH

- `backfill_reddit.log` stops at **`[1672/10481]`** (16% of targeted combos), last write 2026-05-18 12:26 local.
- Trailing entries show `+0 posts, +0 comments` repeatedly → **rate-limited / stalled near the end of the run**, not a clean completion.
- Task #7 ("Launch backfill_reddit.py for real") is still marked `in_progress` — consistent.
- Net effect: Reddit empty rate only dropped marginally (still **64.8%** zero). **A second backfill run is needed** to make a dent, and the rate-limiting suggests it needs throttling/resume logic.
- (CarComplaints backfill, by contrast, **did** finish: `Run complete. vehicles=37 populated=31 files_written=1850 elapsed=1.4min`.)

### Make distribution (25 makes — imbalanced toward US/Japanese mass-market)

```
ford 38 · toyota 34 · chevrolet 30 · honda 24 · nissan 22 · subaru 17 · jeep 16
kia 13 · gmc 12 · mazda 12 · hyundai 12 · dodge 9 · ram 8 · lexus 8 · vw 7
acura 5 · audi 5 · bmw 5 · buick 5 · genesis 5 · mercedes-benz 5 · chrysler 3
infiniti 2 · volvo 2 · mini 1
```

### DTC class-balance audit — NOT DONE

- `corpus_stats.py` reports **per-source** and **per-vehicle** coverage, **not per-DTC distribution.** There is no audit of P0420 representation vs the least-common code. **This audit has not been run** — it's a gap (every vehicle nominally has all 50 codes as files, but actual *populated* content per code is not measured anywhere).

### NHTSA name-mismatch (Mercedes/Volvo/BMW)

- Still documented as a known limitation. Per Austin's Option-C decision: **NOT fixed**, affected makes to be **excluded from the held-out test set** and framed as a methodology note.
- Confirmed in corpus: Mercedes (5), Volvo (2), BMW (5) all present but under-grounded on NHTSA.

### Vehicle-level holdout / 80-10-10 split

- ❌ **NOT implemented.** `ml/data/splits/` contains only `.gitkeep`. No split code, no frozen test set exists. The "exclude luxury from test split" decision is recorded but not yet realized in any artifact.

---

## SECTION 5 — ml/ directory state

| Path | Status | Purpose |
|---|---|---|
| `ml/CLAUDE.md` | ✅ written | Scoped rules for corpus prep / training / eval / deploy |
| `ml/notes/synthesis_design.md` | **stub** | "Will be expanded Wed during ETL design session" — placeholder only |
| `ml/data/sae_j2012.json` | ✅ **418 entries** | Canonical OBD-II DTC lookup (NOT the 22-entry hotfix — see below) |
| `ml/scripts/build_sae_j2012.py` | ✅ written | Generator for the 418-entry JSON; auditable corrections |
| `ml/scripts/blackwell_check.py` | ✅ written | Pre-training sm_120 + sdpa capability check for the 5090 |
| `ml/src/chat_template.py` | ✅ written | Single source of truth wrapping `tokenizer.apply_chat_template()` |
| `ml/src/__init__.py`, `ml/src/etl/__init__.py`, `ml/src/eval/__init__.py`, `ml/src/training/__init__.py` | **empty (0 lines)** | Package scaffolding only — no logic |
| `ml/configs/`, `ml/data/{pairs,processed,raw,splits}/`, `ml/runs/` | empty (`.gitkeep`) | Directory scaffolding |

### Specific checks

- **Training script** (`train_lora.py` / `train_qlora.py`) → ❌ **none.** Not started.
- **Eval scripts** (`evaluate.py` / `eval_matrix.py`) → ❌ **none.** `ml/src/eval/` is an empty package.
- **Data-prep scripts** (`prepare_corpus.py` / `synthesize.py`) → ❌ **none.** `ml/src/etl/` is an empty package; synthesis design is still a stub. The (a)→(c) transformer the council called "the actual unbuilt load-bearing work" **does not exist yet.**
- **`ml/data/sae_j2012.json`** → ✅ **the expanded 418-entry version**, not the 22-entry hotfix. (Distribution: powertrain 370, network 18, chassis 16, body 14; standardized 379, mfr-specific 39.) Lives on PR #11, not yet on main.

---

## SECTION 6 — Code state on the pivot

- **`ollama_client.py`** → still wired to **`gemma4:e4b`** (`DEFAULT_MODEL = "gemma4:e4b"`), `/api/chat`, `temperature=0.2`, `num_predict=4000`. **No OpenAI-compatible alternative started.** No `repeat_penalty` set (the deferred free experiment from the A4500 note is not applied).
- **`main.py` latency instrumentation** → ❌ **none.** No `perf_counter`, `time.time`, `elapsed`, or structured timing logs anywhere in `main.py`. The latency instrumentation briefed earlier was **never added.**
- **Together.ai / Qwen3-30B-A3B investigation** → ❌ **nothing.** No notes file, no catalog research. The only "together" hits in the repo are the DSPy "BetterTogether pattern" mentioned in `.claude/agents/` — unrelated.
- **Qwen-direction commits / branches** → ❌ **none.** No commit, branch, note, or decisions.md entry references Qwen. **As far as the repo is concerned, there is no Qwen pivot** — the committed direction is still Gemma 4 E4B fine-tune. (If a Qwen pivot was discussed verbally, it has left zero trace in the codebase or decision log.)

---

## SECTION 7 — Honest gaps (briefed but never executed)

| Item | Status | Reason |
|---|---|---|
| **(a)→(c) corpus transformer** | ❌ not built | The single largest unbuilt load-bearing piece (council flagged it). `ml/src/etl/` empty, synthesis design a stub |
| **Reddit backfill completion** | ⚠️ ~16% done | Stalled/rate-limited at 1672/10481; 64.8% combos still empty. Needs a throttled second run |
| **DTC class-balance audit** | ❌ not done | `corpus_stats.py` measures per-source/per-vehicle, never per-code populated content |
| **80/10/10 vehicle-level holdout / frozen test set** | ❌ not implemented | `ml/data/splits/` is empty. Decision recorded, artifact absent |
| **Prefill-vs-decode throughput split** | ❌ not measured | Only decode (104 tok/s) documented; this session's re-run blocked by SSH auth |
| **main.py latency instrumentation** | ❌ never added | Briefed, not done |
| **PR #8 baseline re-run with hotfix** | ⚠️ queued, not run | `scripts/baseline_validation_rerun.md` — was gated on A4500 work; that's done, so it's now **unblocked** |
| **Trim-selection bug (CarsXE `trims[0]`)** | ❌ not fixed | ETL pre-flight #2. Production + ETL both affected (Silverado → 4.3L V6 instead of 5.3L V8). Two-pronged fix unscoped |
| **CarsXE coverage-gap fallback (404 → VPIC y/m/m)** | ❌ not done | ETL pre-flight #3 |
| **CarsXE support ticket** | ⚠️ drafted, not sent | Manual send by Austin; draft ready |
| **Eval rubric / baseline / GEPA harness lock-down** | ❌ not done | Council's top "more load-bearing than corpus cleanup" item; no eval methodology artifact exists |
| **`repeat_penalty` / temp / num_predict production experiments** | ❌ not tried | Deferred free experiments from the A4500 note; `ollama_client.py` unchanged |
| **Eval condition models / H1–H4** | ⚠️ unshared | Council asked for H1–H4; not in repo |
| **Stale branch cleanup** | — | ~9 merged/abandoned branches linger (housekeeping) |

### Net read

What's solid: secrets migrated to env vars, Groq cut, A4500 Ollama live + tunnel, baseline captured, CarsXE bug diagnosed/verified/relegated to fallback, 418-entry canonical lookup built (on PR #11), council decision recorded, ml/ scaffolded.

What's missing is **the entire training pipeline**: no transformer, no splits, no training script, no eval harness, no class-balance audit. The corpus exists but is one stalled-backfill and one un-built transformer away from being trainable. The "pivot" to Qwen has no footprint in the repo.

The single highest-leverage unblocked item right now: **the baseline re-run is no longer gated** (A4500 work done), and **the (a)→(c) transformer + eval harness** are the load-bearing build the council named on May 10 and that still has zero code.

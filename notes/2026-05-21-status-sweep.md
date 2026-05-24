# ClearDrive status sweep — 2026-05-23

Report-only. No code changes, no PR actions, no optimization. Fact-gathering pass.

**Top-line delta since the 2026-05-20 sweep: nothing.** No commits on any branch, no merges, no new files in `notes/` or `ml/` except the 2026-05-20 sweep itself (which is still untracked on the PR #11 branch). PR #11 is still open with the same two commits and no new comments. Reddit backfill log unchanged. Same SSH blocker.

One persistent blocker: **Section 2 (live A4500 diagnostic) again could not run** — SSH key auth to `abrennan@100.100.254.15` still returns `Permission denied (publickey,password)` (no private key in `~/.ssh`, both agents empty). Same state as 3 days ago. The May-18 documented numbers are reported instead, with the same caveat that they're decode-only.

---

## SECTION 1 — Git state

### PR status (unchanged since 2026-05-18)

| PR | Title | State | Last update | Blocker comments |
|---|---|---|---|---|
| #6 | Reddit backfill + GLC300 investigation | **MERGED** | 2026-05-18 | none |
| #7 | Post-council cleanup: env-var secrets, Groq cut, CarComplaints fix | **MERGED** | 2026-05-18 | One informational comment lists "PaaS dashboard" gating items — **stale**, superseded by the no-PaaS topology |
| #8 | Baseline format-validation experiment | **MERGED** | 2026-05-18 | none |
| #9 | Force LF on .claude/ for /council | **MERGED** | 2026-05-18 | none |
| #10 | ETL pre-flight: council resolve + decisions log + ml/ scaffold + CarsXE audit/hotfix | **MERGED** | 2026-05-18 | none |
| #11 | Canonical OBD expansion + A4500 diagnostic + 418-entry JSON | **OPEN** | 2026-05-18 | Last (and only) comment is the 2026-05-18 self-summary. **Awaiting review/merge — 5 days now.** PR title still undersells the contents |

### `origin/main` — last 30 commits

```
9a5da27  2026-05-18  Merge PR #10 (ETL pre-flight)            <- main HEAD
ff1a0f5  2026-05-18  Hotfix P0420 description override
cd5a93f  2026-05-18  Audit CarsXE decode corruption (10 codes)
7c20a8b  2026-05-18  Create ml/ subdirectory
6940f88  2026-05-18  Seed notes/decisions.md
0c9e5dc  2026-05-18  Resolve 2026-05-10 council session: option C
6c2f0a6  2026-05-18  Merge PR #9 (CRLF cleanup)
4a5278f  2026-05-18  Merge PR #8 (baseline validation)
54281c9  2026-05-18  Force LF line endings on .claude/
e8f0084  2026-05-18  Baseline format-validation experiment
18cd60c  2026-05-18  Merge PR #7 (post-council cleanup)
7996f0a  2026-05-18  Merge PR #6 (Reddit backfill + GLC300)
345f028  2026-05-18  docs: deployment topology (A4500 + tunnel, no PaaS)
7151d3d  2026-05-18  Wire A4500 Ollama: env-var host, /api/chat
b07b6df  2026-05-18  Move API keys to env vars; remove Groq
8ce5971  2026-05-18  Fix CarComplaints .title() bug + backfill
41ca8b0  2026-05-18  Add council infrastructure + project rules
96b6aca  2026-04-26  Reddit backfill script + GLC300 investigation
57efd49  2026-04-25  Merge PR #5
f22bf6f  2026-04-25  Fix NHTSA empty-result + remove OBD-Codes
6b91ed9  2026-04-25  Merge PR #4
675ea76  2026-04-25  v2 overnight scraper: 300 vehicles × 50 codes × 6 sources
cf2df92  2026-04-25  Merge PR #3
55bd973  2026-04-24  Revert PR #2 merge
384aa38  2026-04-24  Merge PR #2
02416bb  2026-04-24  Add overnight scraper
268ec46  2026-04-24  Merge PR #1
2f04d46  2026-04-24  Add research-grade scan logging
e03ea07  2026-04-11  Switch AI backend from Groq to local Gemma 4 E4B via Ollama
1c2f70f  2026-04-07  Fix transmission display + vehicle-specific AI responses
```

**Most recent commit on main: 2026-05-18** (5 days ago). No new work landed.

### Other open PRs / active branches

- **Only PR #11 open.** All of #1–#10 merged.
- Current checkout: `feat/canonical-codes-expansion` (PR #11) — unchanged since `52c1230` on 2026-05-18.
- Working tree: clean except `notes/2026-05-20-status-sweep.md` (the prior sweep) is **untracked** — not committed to any branch.
- Stale branches with no open PR (merged or abandoned, candidates for cleanup): `docs/claude-md-reconcile`, `feat/baseline-gemma-format-validation`, `feat/research-logging`, `feat/training-data-scraper-v2`, `feat/training-data-scraping`, `fix/nhtsa-empty-results-remove-obd-codes`, `revert/initial-scraper`, `origin/feat/etl-pre-flight-2026-05-18`, `origin/fix/claude-md-line-endings`.

---

## SECTION 2 — A4500 diagnostic ⚠️ STILL NOT RE-RUN

**Same blocker as 3 days ago.** `ssh abrennan@100.100.254.15` → `Permission denied (publickey,password)`. No private key file in `~/.ssh/` (only `known_hosts`), git-bash and Windows ssh-agents both empty. The diagnostic needs an interactive credential I don't have access to.

### Correction to the brief's premise

The brief states "the 105 tok/sec figure was reported verbally but never documented." **It is documented** — `notes/2026-05-18-a4500-optimization.md` (9.7 KB) is a full diagnostic write-up. Captured numbers:

| Metric | Documented value (2026-05-18) | Source |
|---|---|---|
| GPU utilization (peak) | **94%** | `nvidia-smi` 1s sampling |
| GPU utilization (sustained) | ~92% | same |
| Power state | **P2** (active, not P8) | same |
| Power draw (peak) | **199.44 W** at 200 W TDP | same |
| VRAM used | 9,741 MiB / 20,470 MiB (no offload) | same |
| eval rate (decode) | **104.00 tok/s** (Step 0); 104.24 mean of runs 2–3 (Step 3) | `ollama run --verbose` |
| Processor | 100% GPU (no CPU offload) | `ollama ps` |
| Load durations | run 1 cold: 3.32 s; runs 2–3 hot: 176–194 ms | `--verbose` |
| eval count per run | 1883–2365 tokens | `--verbose` |

### What is NOT captured (the brief's specific asks)

- ❌ **Prompt eval rate (prefill) is NOT separated from decode.** Only the decode `eval rate` (104 tok/s) was recorded. Prefill throughput remains genuinely unknown — the one number a live re-run would still add.
- ❌ Total wall time per response was not tabulated (load + prompt eval + eval durations exist in the raw `--verbose` output but were not summed into a single number).

### Verdict on "is 105 tok/s real"

Documented as real **for decode**, on a hot model, single request. **Whether prefill is the hidden cost is still the open question.** I can run the full prefill-vs-decode diagnostic the moment SSH auth is restored — what's needed: a private key (or password loaded into the agent) for `abrennan@100.100.254.15`.

---

## SECTION 3 — notes/ folder inventory

(All files except the 2026-05-20 sweep last modified 2026-05-18 — folder is static.)

| File | Last modified | Description |
|---|---|---|
| `decisions.md` | 2026-05-18 | Append-only decisions log. **Reflects Gemma 4 E4B — NO Qwen / Together.ai / SGLang pivot recorded.** Captures PR #8 baseline, 3 ETL pre-flight items, hybrid synthesis design, Option-C corpus decision |
| `2026-05-18-a4500-optimization.md` | 2026-05-18 | A4500 diagnostic — **has actual measurements** (104 tok/s, 94% GPU, 199 W). Decode only, no prefill split |
| `2026-05-18-carsxe-decode-audit.md` | 2026-05-18 | PR #10 audit of CarsXE wrong-decode across 10 codes (~60% wrong-decode rate) |
| `2026-05-18-carsxe-independent-verification.md` | 2026-05-18 | ✅ exists. Raw-`curl` re-verification + offset analysis (6/7 = −1 offset) |
| `2026-05-18-carsxe-support-ticket-draft.md` | 2026-05-18 | **DRAFT, not sent.** Status line literally: "DRAFT. Not sent. Austin to review then send." |
| `baseline-gemma-format-validation-2026-05-18.md` | 2026-05-18 | PR #8 full baseline (136 KB): 20 scenarios, 3.5/12 format mean, 35% degenerate, 44 s latency |
| `2026-05-20-status-sweep.md` | 2026-05-20 | **Prior sweep — untracked on PR #11 branch.** Not committed |
| `council/decisions/2026-05-10--corpus-cleanup-before-training.md` | 2026-05-18 | 5-member council session + Austin's verdict: **Option C (Hybrid)** |
| `carsxe-raw-responses/` | 2026-05-18 | Raw CarsXE JSON captures backing the verification |

### Specific brief checks

- **`decisions.md` — any pivots (Qwen / Together.ai / SGLang)?** → **No.** Still original Gemma 4 E4B fine-tune plan. No mention of any of these three names anywhere in the repo (besides the May-20 sweep itself flagging their absence).
- **`carsxe-independent-verification.md`** → ✅ exists.
- **A4500 optimization note with actual measurements** → ✅ exists, has real numbers (decode only).
- **`notes/baseline_validation_rerun.md`** → ❌ not in `notes/`. Lives at **`scripts/baseline_validation_rerun.md`**, status header: "Queued, not run." PR #8 re-run with hotfix **has NOT been done.**
- **`notes/council/decisions/`** → one verdict: 2026-05-10 corpus cleanup → **Option C (Hybrid)** + Austin's decision appended.
- **`carsxe-support-ticket-draft.md`** → ✅ exists, **DRAFT / not sent.**

---

## SECTION 4 — Corpus state (unchanged since 2026-05-18)

Source: `py corpus_stats.py` over `training_data/raw/` (2026-05-23 run).

| Metric | Value |
|---|---|
| Total disk | 5,326.9 MB (~5.33 GB) |
| Total JSON files | **15,000** (300 vehicles × 50 codes) |
| Vehicle dirs | 300 |
| Distinct source docs (per-vehicle memoization) | ~5,700 (do NOT cite 15,000 as unique sources) |
| JSON parse errors | 0 |

### Per-source coverage (n=300 vehicles)

| Source | avg | median | vehicles with zero |
|---|---|---|---|
| NHTSA complaints | 279.2 | 139 | 28/300 |
| NHTSA recalls | 5.2 | 4 | 26/300 |
| RepairPal items | 13.2 | 14 | 2/300 |
| CarComplaints | 0.8 | 1 | **54/300** |
| Reddit (per vehicle×code, n=15,000) | 5.92 | **0** | **9,727 (64.8%) zero** |

### Reddit backfill — STILL DID NOT FINISH

- `backfill_reddit.log` last write **2026-05-18 12:26 local**, stopped at `[1672/10481]` (16% of targeted combos). Unchanged in 5 days.
- Trailing entries: `+0 posts, +0 comments` → rate-limited/stalled.
- Net Reddit empty rate **still 64.8%**.
- Task #7 ("Launch backfill_reddit.py for real") still marked `in_progress`.
- **A second backfill run has not been attempted.**
- (CarComplaints backfill did finish on 2026-05-18: `vehicles=37 populated=31 files_written=1850 elapsed=1.4min`.)

### Make distribution (25 makes — imbalanced toward US/Japanese mass-market)

```
ford 38 · toyota 34 · chevrolet 30 · honda 24 · nissan 22 · subaru 17 · jeep 16
kia 13 · gmc 12 · mazda 12 · hyundai 12 · dodge 9 · ram 8 · lexus 8 · vw 7
acura 5 · audi 5 · bmw 5 · buick 5 · genesis 5 · mercedes-benz 5 · chrysler 3
infiniti 2 · volvo 2 · mini 1
```

### DTC class-balance audit — STILL NOT DONE

`corpus_stats.py` measures per-source and per-vehicle only. **There is no audit of P0420 representation vs the least-common code.** This audit has not been run; no script for it exists. (Every vehicle nominally has all 50 codes as files, but actual *populated content per code* is not measured anywhere in the repo.)

### NHTSA Mercedes/Volvo/BMW name-mismatch

- Status unchanged: documented as known limitation per Austin's Option-C decision. **NOT fixed.** Affected makes to be **excluded from the held-out test set**, framed as methodology note.
- Confirmed in corpus: Mercedes (5), Volvo (2), BMW (5) all present but under-grounded on NHTSA.

### Vehicle-level holdout / 80-10-10 split

- ❌ **Still not implemented.** `ml/data/splits/` contains only `.gitkeep`. **No split code anywhere in the repo. Test set is not frozen.**

---

## SECTION 5 — ml/ directory state (unchanged since 2026-05-18)

| Path | Status | Purpose |
|---|---|---|
| `ml/CLAUDE.md` | ✅ written | Scoped rules for corpus prep / training / eval / deploy |
| `ml/notes/synthesis_design.md` | **stub** | "Will be expanded Wed during ETL design session" — placeholder only |
| `ml/data/sae_j2012.json` | ✅ **418 entries** (93,618 B) | Canonical OBD-II DTC lookup — **the expanded version**, not the 22-entry hotfix. On PR #11, not yet on main |
| `ml/scripts/build_sae_j2012.py` | ✅ written | Generator for the 418-entry JSON |
| `ml/scripts/blackwell_check.py` | ✅ written | Pre-training sm_120 + sdpa capability check for the 5090 |
| `ml/src/chat_template.py` | ✅ written | Wraps `tokenizer.apply_chat_template()` |
| `ml/src/__init__.py`, `ml/src/etl/__init__.py`, `ml/src/eval/__init__.py`, `ml/src/training/__init__.py` | **empty (0 lines each)** | Package scaffolding only |
| `ml/configs/`, `ml/data/{pairs,processed,raw,splits}/`, `ml/runs/` | empty (`.gitkeep`) | Directory scaffolding |

### Specific brief checks

- **Training script** (`train_lora.py` / `train_qlora.py`) → ❌ **none.** Not started.
- **Eval scripts** (`evaluate.py` / `eval_matrix.py`) → ❌ **none.** `ml/src/eval/` is an empty package.
- **Data-prep scripts** (`prepare_corpus.py` / `synthesize.py`) → ❌ **none.** `ml/src/etl/` is an empty package; synthesis design still a stub. The (a)→(c) transformer the council identified as the load-bearing build still has zero code.
- **`ml/data/sae_j2012.json`** → ✅ **418 entries** (expanded; powertrain 370, network 18, chassis 16, body 14; standardized 379, mfr-specific 39). Lives on PR #11 branch; not yet on main.

---

## SECTION 6 — Code state on the pivot

- **`ollama_client.py`** → still wired to **`gemma4:e4b`** (`DEFAULT_MODEL = "gemma4:e4b"`), `/api/chat`, `temperature=0.2`, `num_predict=4000`, no `repeat_penalty`. **No `qwen_client.py`, no `together_client.py`, no OpenAI-compatible alternative.** Unchanged.
- **`main.py` latency instrumentation** → ❌ **none.** `grep -nE "perf_counter|time.time|elapsed|latency"` returns zero hits in code paths (the matches that surfaced are all DTC descriptions containing the word "Timing"). The instrumentation briefed multiple times has **never been added.**
- **Together.ai investigation** → ❌ **nothing.** No notes file, no commit, no catalog research. The only "together" hits across the repo are the DSPy "BetterTogether pattern" in `.claude/agents/` (unrelated framework concept).
- **SGLang** → ❌ **nothing.** Zero hits across `*.py` / `*.md`.
- **vLLM** → ❌ **nothing.** Zero hits.
- **Qwen / Qwen3-30B-A3B** → ❌ **nothing.** Only mentions are this status sweep and its 2026-05-20 predecessor flagging the absence.
- **Qwen-direction commits / branches** → ❌ **none.**

**Net:** the committed direction is exactly what it was on 2026-04-11 (Groq → Gemma 4 E4B via Ollama) with the 2026-05-18 wiring fixes (`OLLAMA_HOST`, `/api/chat`, env-var secrets). **No verbally-discussed pivot has any footprint in the repo.**

---

## SECTION 7 — Honest gaps

| Item | Status | Reason / where it stands |
|---|---|---|
| **(a)→(c) corpus transformer** | ❌ not built | The largest unbuilt load-bearing piece (council, 2026-05-10). `ml/src/etl/` empty; synthesis design a stub |
| **Reddit backfill completion** | ⚠️ ~16% done, stalled 5 days | Stopped at 1672/10481 with trailing `+0 posts` (rate-limited). Empty rate still 64.8%. No second attempt |
| **DTC class-balance audit** | ❌ not done | No script exists; `corpus_stats.py` measures per-source/per-vehicle, never per-code |
| **80/10/10 vehicle-level holdout / frozen test set** | ❌ not implemented | `ml/data/splits/` empty. Decision recorded, artifact absent |
| **Prefill-vs-decode A4500 throughput split** | ❌ not measured | Only decode (104 tok/s) documented; this session's re-run still blocked by SSH auth |
| **`main.py` latency instrumentation** | ❌ never added | Briefed twice (2026-05-20 sweep + this one). No `perf_counter` / `time.time` / structured timing |
| **PR #8 baseline re-run with hotfix** | ⚠️ queued, not run | `scripts/baseline_validation_rerun.md` brief exists. Now **unblocked** (A4500 work done), still not executed |
| **Task 2 from May-18 brief — comprehensive SAE J2012 lookup (400–500 entries)** | ✅ **done** (only thing on this list that is) | 418 entries live in `ml/data/sae_j2012.json` on PR #11; awaiting merge |
| **Trim-selection bug (CarsXE `trims[0]`)** | ❌ not fixed | ETL pre-flight #2. Production + ETL both affected. Two-pronged fix unscoped |
| **CarsXE coverage-gap fallback (404 → VPIC y/m/m)** | ❌ not done | ETL pre-flight #3 |
| **CarsXE support ticket sending** | ⚠️ drafted, not sent | Manual send by Austin; draft is in `notes/` |
| **Eval rubric / baseline / GEPA harness lock-down** | ❌ not done | Council's #1 "more load-bearing than corpus cleanup" item. No eval methodology artifact exists |
| **Verification of Unsloth current MoE support (Gemma 4 26B-A4B QLoRA blocker)** | ❌ **not investigated** | Zero refs to "moe", "26b-a4b", or "Gemma 4 26B" anywhere in the repo. Unsloth only appears in `CLAUDE.md` and the council notes as the install-path commitment for the dense E4B plan |
| **Together.ai catalog check for Qwen3-30B-A3B** | ❌ **not done** | Zero footprint. No notes file, no commit |
| **`repeat_penalty` / temp / `num_predict` production experiments** | ❌ not tried | Deferred from A4500 note; `ollama_client.py` unchanged |
| **H1–H4 shared with council** | ⚠️ unshared | Council flagged this 2026-05-10; H1–H4 still not in any repo doc |
| **PR #11 merge** | ⚠️ open 5 days | Awaiting Austin's review/merge |
| **Stale branch cleanup** | — | ~9 merged/abandoned branches linger |

### Net read

Same as the 2026-05-20 sweep — **nothing has moved in 3 days.** What's solid stays solid (secrets, Groq cut, A4500 + tunnel live, baseline captured, CarsXE diagnosed/relegated, 418-entry lookup built, council decision recorded, ml/ scaffolded). What's missing stays missing: the entire training pipeline (no transformer, no splits, no train script, no eval harness, no class-balance audit) and any footprint of the discussed-but-not-committed pivots (Qwen / Together.ai / SGLang / Unsloth-MoE).

**Highest-leverage unblocked items, in order:**
1. **Merge PR #11** — frees the 418-entry lookup, A4500 diagnostic doc, support ticket draft, rerun brief.
2. **Run the queued PR #8 baseline re-run** with the canonical lookup in place — quantifies how much PR #8's 35% degeneracy was prompt-noise vs genuine.
3. **Build the (a)→(c) transformer + the eval rubric/baseline lock-down** — the council's named load-bearing work, still zero code, 13 days since named.
4. **Decide on the verbal pivots in writing** — every discussed alternative (Qwen3-30B-A3B on Together.ai, SGLang, Gemma 4 26B-A4B MoE on Unsloth) needs a one-page evaluation in `notes/decisions.md` or the door stays open indefinitely while the original Gemma 4 E4B plan goes uncontested by default.

# Brief 2c report: training data distillation (weekend Phase 5), 2026-10-12

Host: `BLACK_5090`. Log: `notes/reports/logs/2026-10-12-phase-5.log`, cited as `L<n>`.
Brief: `docs/briefs/weekend/brief-2c-training-data-distillation.md`, with the rulings in
`notes/decisions.md` (2026-09-25 fine-tune rulings; 2026-10-12 hands-off run).

**Result.** 5,000 training pairs: 4,750 in `data/train/train.jsonl` and 250 in
`data/train/val.jsonl`. All six acceptance checks pass (L277–290). Synthesis cost $611.75.
Nothing is blocked for Phase 5. One item blocks a later step of Phase 6 (section 8).

**How to read this report.** Brief 2c was written without sight of the corpus, and several
steps did not fit it as written. I made a reading in each case and carried on, as the
hands-off instruction required. Those readings are listed in "Departures from the brief"
below and recorded in `notes/decisions.md` (2026-10-12). They are yours to overrule.

## Step 0: state check
- Tag `eval-v1-frozen` present at `aa308a1` (L2–4). It was created 2026-09-26; the first
  synthesis call was 2026-10-12T23:58Z (L286–290).
- `ANTHROPIC_API_KEY` set (L6). OpenRouter is not used.
- Raw data: `training_data/raw/`, 300 vehicle directories, 15,000 JSON files (L24–53).
- No existing distillation or dataset-builder script was found; `ml/src/etl/` holds only an
  `__init__.py` (L54–75). The six `scripts/distill_*.py` files are new.

## 1. Raw counts per source (step 1)
`scripts/distill_normalize.py`, L80–96. Counts are items, de-duplicated within a vehicle.

| Source | In | Out | Note |
|---|---|---|---|
| Reddit posts (30 subreddits) | 74,605 | 74,605 | DTCs from the post text, else the file's code |
| NHTSA complaints | 83,746 | 83,746 | 1,233 of them state a P-code |
| RepairPal problem strings | 681 | 680 | |
| CarComplaints problem strings | 247 | 1 | 246 were scrape debris such as "Learn More" |
| NHTSA recall notices | 1,566 | 0 | not owner reports: no DTC and no symptoms |
| **Total** | **160,845** | **159,032** | |

Per-subreddit counts are in `data/train/normalize_counts.json`. One format: JSON.
38,744 records have a stated resolution.

## 2. Exclusion (step 2)
`scripts/distill_sample.py`, L153–154. **12,442 records dropped**, 146,590 remain.

| Reason | Records |
|---|---|
| URL names an NHTSA complaint used by an eval case | 6 |
| Same (year, make, model) as an eval case and shares a DTC with it | 144 |
| Same (year, make, model) as any eval case or codeless profile | 12,292 |

The third rule is stricter than the brief's and removes 17 of the corpus's 299 vehicles.
Dropped record IDs and reasons are in `data/train/exclusions.json`.

## 3. Sample composition (step 3)
L153–197. The backend's prompt depends only on (year, make, model, DTC set), so one record
is drawn per distinct input. 11,359 distinct inputs were available; **5,500 sampled**.
4,181 have a stated resolution, 1,540 carry more than one DTC, 260 have no DTC.

| Label | n | Share |
|---|---|---|
| transmission, ignition_component, evap_system, air_fuel_metering_other, valve_timing_air_aux | 550 each | 10.0% each |
| maf_sensor | 420 | 7.6% |
| control_module | 415 | 7.5% |
| ignition_system_sensor | 359 | 6.5% |
| unmapped | 329 | 6.0% |
| idle_speed_auxiliary | 309 | 5.6% |
| oxygen_sensor | 292 | 5.3% |
| catalytic_converter | 221 | 4.0% |
| emissions_control_other | 184 | 3.3% |
| vacuum_intake_leak | 82 | 1.5% |
| fuel_injector | 81 | 1.5% |
| fuel_delivery | 58 | 1.1% |

By source: Reddit 4,952 across 29 subreddits (largest: r/MechanicAdvice 825 and r/Cartalk
825, 15.0% each), NHTSA complaints 537 (9.8%), RepairPal 11.

## 4. Context and synthesis (steps 4 and 5)
- **Context (step 4).** `scripts/distill_build.py` sends each record through
  `main.interpret` in-process as an `eval_case`-shaped payload and intercepts the model
  call. 5,500 prompts built: 5,240 on the coded path, 260 on the clean-scan path. 562 NHTSA
  lookups, cached per vehicle, 0 failed (L210–224; these lines interleave with the pilots,
  which ran at the same time).
- **Synthesis prompt.** `data/train/synthesis_prompt.txt`, fixed for every record.
- **Model.** `claude-opus-5-5`, Anthropic API, effort `medium`, concurrency 16. All 5,500
  responses came from that model and ended normally (L239–241).
- **Cost** (`data/train/synthesis_cost.json`, L239–243):

| Run | Targets | Input tokens | Output tokens | USD |
|---|---|---|---|---|
| Final 5,500 | 5,500 | 39,095,176 | 22,617,914 | 608.74 |
| Pilot 1 (discarded) | 40 | 275,893 | 95,544 | 3.01 |
| **Total** | | | | **611.75** |

  The total comes from the usage saved with each response. It leaves out up to 16 requests
  that were in flight when the harness stopped the first background run (L236), and five
  small API probe calls.
- **Two pilots.** Pilot 1 (40 records) gave targets of 487–619 words on the 12-section
  format, so nearly all would have failed the 500-word limit, and the first grounding check
  rejected harmless commentary. I revised the synthesis prompt (section word budgets;
  report only retrieved material in the two vehicle-fact sections) and the matcher, then
  re-ran the same 40: 39 passed (L198–224). Pilot 1's targets were set aside and not used.

## 5. Filter (step 6)
`scripts/distill_filter.py`, L244–251. **5,324 kept, 176 dropped.**

| Reason | Dropped |
|---|---|
| Schema | 76 |
| Grounding | 71 |
| Over 500 words | 29 |
| Under 40 words | 0 |
| Duplicate (exact or Jaccard > 0.9) | 0 |

Schema drops are mostly a `#` or `*` character in the target, and a few where a body line
would be read by the backend's parser as a new header.

**What the grounding check caught.** The brief asks for five examples of invented facts.
Of the 71 drops, 65 were a KNOWN ISSUES sentence whose words the matcher could not find in
the context, and 6 were a number it could not find. No recall number or bulletin number
failed. Reading the list, I did not find a clear invented recall or failure pattern; most
drops are sentences the check could not confirm, not confirmed fabrications. Five examples,
quoted from `data/train/filter_report.json`:

1. `reddit:cb0fb2782d9d69df`: "The retrieved model list is cut off and does not visibly name the NX300." (a claim about the retrieval itself)
2. `nhtsa_complaints:11686393`: "The remedy is ECM (engine computer) reprogramming." (40% or less of its words found)
3. `reddit:feacde3a404badaf`: "Another says CSP11 warranty coverage only extends to 120,000 miles."
4. `reddit:d60c9cc3cec45187`: "- Engine oil cooler (EOC) hose replacement on Hellcat-engined cars."
5. `reddit:6bd2a6a56de0ccf8`: "The retrieved information contains no recall or known-issue records for this vehicle." (an abstention in other words than the mandated sentence)

A preview over the first 1,594 targets exposed a bug in the number matcher (a trailing
comma was captured, so "WRD-20," did not match "WRD-20"); it was fixed before the final
filter run (L237). At least one of the six remaining number drops is still an artefact: "Chrysler 300s" is read as the
number 30. It costs a pair, not correctness.

## 6. Final pairs (step 7)
`scripts/distill_format.py`, L252–276.
- 5,324 passed; 324 trimmed from the largest labels to reach the 5,000 target.
- **train 4,750, val 250 (5.0%).** Validation is 17 whole platforms held out of 138.
- 4,755 pairs use the 12-section format; 245 use the clean-scan format.
- Tokens per pair with the Qwen3 tokenizer and the training rendering: max 5,591, mean
  4,317, limit 8,192. None dropped for length.
- Target length: 133–500 words, mean 440.

## 7. Hashes
`data/train/MANIFEST.json` (committed). SHA-256:

| File | Lines | SHA-256 |
|---|---|---|
| `train.jsonl` | 4,750 | `5be53983ae0ac556f883b285cc67ddd1e94be4e87d20d2936737c8ae595767ec` |
| `val.jsonl` | 250 | `362104592b0aff56a19498c456f4177b4e7a1d5d94728d25b5dafc54fbf98279` |
| `cleardrive_sft.jsonl` | 5,000 | `fb1409c58954492f96b6632ca4b27ca6dae9f207586a000bc6837128452e138c` |

## Acceptance (L277–290)
| # | Criterion | Result |
|---|---|---|
| 1 | Tag existed before any synthesis call | PASS: tag 2026-09-26, first call 2026-10-12 |
| 2 | train 3,000–5,000; val 5% | PASS: 4,750 and 250 |
| 3 | Zero pairs match an eval case | PASS: 0 by URL, 0 by tuple, 0 by vehicle |
| 4 | Every pair passes schema and grounding | PASS: 0 failing of 5,000 |
| 5 | System prompt and user layout byte-identical to the backend | PASS: system prompt equal; 100 pairs rebuilt through `main.interpret`, 0 differ outside the `retrieved_at` timestamp |
| 6 | Manifest and report exist | PASS: 3 files hashed, none mismatching |

## Departures from the brief
1. **Temperature 0.3 was not set.** `claude-opus-5-5` returns HTTP 400 for any
   `temperature` (L13–23). The parameter was omitted. The same will apply to the Phase 7
   judge, where temperature 0 is specified.
2. **Per-label cap is 550, not 400.** 400 was 10% of the brief's 4,000; with the brief's
   caps unchanged only 5,142 records could be drawn (L97–152).
3. **"Source" is the site, with Reddit split by subreddit.** With four sites, a 15% cap
   per site could cover at most 60% of any sample.
4. **Exclusion is by whole vehicle**, a superset of the brief's rule.
5. **Validation split holds out platforms** and tracks the label mix greedily, where the
   brief says "stratified by label". Root `CLAUDE.md` requires hold-outs by platform.
6. **Trimmed to 5,000 pairs**, because Phase 6.1 caps `train.jsonl` at 5,000 lines.
7. **Report path.** This file is at the path brief 2c names;
   `notes/reports/2026-10-12-phase-5.md` points here.

## Risks for the fine-tune (not blocking)
1. **Every training input is code-only.** The corpus has no live data, so no pair shows the
   model a non-empty differential. On those inputs the backend's prompt requires the answer
   "The available evidence does not narrow this down to a specific cause", and the targets
   say so. 40 of the 102 eval cases are synthetic cases with measurements and a computed
   differential. The fine-tune may under-use that differential. If H1 on the synthetic
   cases comes out below base, this is the first place to look.
2. **The targets follow the backend's evidence rules literally.** Where the prompt asks for
   cost ranges or tool sizes but supplies no numbers, the target says the figures were not
   available. The fine-tune will do the same.
3. **The training data exists only on this machine.** `data/train/` is 523 MB and is not in
   git: `train.jsonl` alone is 86 MB. The manifest hashes are committed, so the files can be
   checked but not rebuilt without re-spending the synthesis cost. A copy elsewhere would be
   prudent.

## 8. Blocked
- **Phase 5: nothing.**
- **Phase 6, GGUF copy.** `ssh abrennan@ajb1ubuntu` from this machine returns
  `Permission denied (publickey,password)` (L227; rechecked 2026-10-13T02:24Z). Training,
  merge and export do not need it. The `scp` step will be BLOCKED unless this machine's
  public key (`~/.ssh/id_ed25519.pub`, comment `claude-code@BLACK_5090`) is added to
  `~/.ssh/authorized_keys` for `abrennan` on the A4500 before then.

# Decisions log

Append-only. Most recent first. Each entry is a settled commitment — don't relitigate without escalating. For session-by-session strategic reviews, see `notes/council/decisions/`.

## [DECIDED] Second H4 null, re-scoring rule, base abstention recorded as a finding — 2026-09-26
Context: the H4 scorer review showed that the system-level null scores 0.0 partly by
construction. It uses only system-category words, which `h4_hit` no longer counts. Generic
text that names parts gets further: a four-sentence composite scores about 0.33. Separately,
a 3-case dry run showed base Qwen answering "the evidence does not narrow this down" on
code-only reconstructed cases.

Decision (Austin, 2026-09-26). This entry was written after the base run began and before
any output was scored:
- **Second null.** A part-level null response is added:
  - The text is `eval_score.H4_NULL_PART_RESPONSE`. It is "No verified issue history was
    available", followed by four generic sentences naming a fuel pump, a brake master
    cylinder, an air bag inflator and an occupant classification sensor.
  - It is a second permanent line in every `scores.md`, next to the system-level null.
  - Both fixed texts are in the repo (`H4_NULL_RESPONSES`).
  - On the frozen profiles: system-level **0.0**, part-level **0.333**.
  - The pinned 50% threshold stays the primary H4 criterion. `results.md` reports the hit
    rate against both nulls so the reader can judge the margin.
- **Re-scoring.** Any later re-scoring of saved responses leaves the original
  `scores.json` untouched. `eval_score.py` refuses to overwrite it. A re-score needs
  `--rescore NAME --reason TEXT`, writes `scores-NAME.json` and `scores-NAME.md` beside the
  original, and records the reason; the report must repeat it.
- **Base abstention.** On code-only cases, base Qwen's abstention is recorded as a finding,
  not fixed. There are no prompt or rule changes for it.
- **Thinking mode overnight.** Production returns to thinking-on (`CLEARDRIVE_THINK`
  unset, meaning default) after the thinking-off base run.

Evidence: `test_eval_scripts.py` covers both nulls, the refusal to overwrite, and the
requirement for a reason; 194 tests pass.

## [DECIDED] H4 null-baseline reporting, pre-registered before any run — 2026-09-26
Context: code review of `scripts/eval_score.py` found that the first H4 scorer passed a
response that says nothing about the vehicle. The fixed text "Your air bags and seat belts
are fine." hit **17/30 = 0.57** of the frozen codeless profiles, above the pinned 50%
threshold. Everyday words in NHTSA component names ("AIR BAGS", "SERVICE BRAKES") counted
as "distinctive", and every narrative section was searched. **No eval run existed when this
was found and fixed.** Nothing below was tuned against model outputs.

Decision (Austin, 2026-09-26):
- **Pre-registered reporting rule.** Every `scores.md` carries a permanent line with the
  H4 hit rate of a fixed null response (`eval_score.H4_NULL_RESPONSE`: generic,
  vehicle-agnostic advice), scored exactly like a model response. `results.md` reports H4
  as the hit rate *alongside* that null baseline. The bare 50% threshold is not evidence on
  its own.
- **How `h4_hit` implements the pinned rule** ("campaign number, or at least two
  distinctive words of its recall component"):
  - Only the model's KNOWN ISSUES section is read, because that is the section meant to
    carry vehicle facts.
  - "Distinctive" means the part level of NHTSA's component path, which is the segments
    after the first two system-category levels. Two such words must appear. A component
    with no part-level words ("POWER TRAIN:AUTOMATIC TRANSMISSION") can be hit only
    through its campaign number.
  - On the frozen set, 39 of 119 documented issues have a word path.
  - The null baseline is **0.0**.
  - `test_eval_scripts.py` fails if the null baseline rises above 0.1.
- **Silent failures.** `/interpret` reports a model failure as HTTP 200 with
  `dont_panic: "ERROR: …"`. `eval_run.call_error` now counts that, a backend `error`, or a
  missing `finish_reason` as a failed call. More than 5% failed calls fails the run, and the
  scorer refuses a failed run, the same way as the truncation gate. A failed warm-up aborts
  the run before any scored case.
- **Timeouts.** The backend model call timeout (`ollama_client.MODEL_TIMEOUT_S`) goes from
  180 s to **300 s**, so a long thinking case is not a failure. The change applies to every
  condition and was made before any run. The runner's per-call timeout is **330 s**, so the
  backend's own timeout fires first and comes back as a classified failure.
- **Scoring vocabulary and rule-based ranges.** The H1 component vocabulary now covers
  hyphen and slash spellings, "manifold absolute pressure" spelled out, and "(CKP)"-style
  abbreviations. The rule-based arm's code ranges run to hex group ends (P00FF, not P0099).
  An undefined code maps by its SAE group, which is all a lookup-only reader can know.
  Before this fix, P219B and P04F1 in the frozen set mapped to nothing. P24xx maps to
  auxiliary emissions, with EVAP overrides only for P2400–P2422 and P2450–P2451. Before
  this fix, EV-032 (P245B, EGR cooler bypass) was scored as EVAP, which counted against
  the rule-based arm. Codes in P28xx–P29xx remain unmapped.

Evidence: 190 tests pass across `test_eval_scripts.py`, `test_eval_case.py`,
`test_knowledge.py` and `test_diagnostics.py`. Review: round 1 FAIL (H4 one-word
relaxation); round 2 FAIL (H4 generic hits, silent failures, spelling gaps, hex bounds);
fixed on Austin's instruction. Round 3 (deep) PASS; its three IMPORTANT items are fixed:
P24xx group, a gate that failed open, and an air-fuel-mixture negative test.

## [DECIDED] Eval set eval-v1 frozen — 2026-09-26
Context: Brief 2a (weekend Phase 2). H1, H2 and H4 compare conditions, so they need one
locked test.
Decision: the set is frozen at tag **`eval-v1-frozen`**. Hashes, counts and the touch rule are
in `eval/MANIFEST.json`. The builder is `scripts/eval_build.py`, which builds from
`eval/sources/*`; `scripts/eval_validate.py` reported 0 errors.
- **Eval set: 102 cases.**
  - 62 reconstructed from NHTSA complaints with a confirmed repair; the label comes from
    the component repaired, not the DTC.
  - 40 synthetic, built from `diagnostics.py` rules and each checked against the real rule
    engine at build time. Synthetic share is 39.2%.
  - 15 labels, each with at least 6 cases; 14 makes.
- **Codeless set (H4): 30 profiles**, 119 documented issues, all NHTSA recalls, across 14
  makes. The H4 rule and the 50% threshold are pinned in the file header.
- **Composition:** `eval/composition.md`.

Rulings that shaped the set (Austin, 2026-09-25/26):
- **Scope.** P codes only; B/C/U families are out of scope.
- **Eras.** OBD era is set by model year (pre-CAN before 2008, CAN from 2008). OBDonUDS is
  unrepresented because no sourced vehicle list exists, so 2a acceptance criterion 3 is
  only partly met.
- **Reconstructed payloads.** They carry the vehicle and the stated DTCs only. Every
  measurement is null, which follows CLAUDE.md Never #2 and keeps any value built from the
  label out of the input.
- **Nameplates.** The fixed make list replaces the BTS nameplate list.
- **Transport.** Cases reach `/interpret` through `eval_case` (entry below).

Other decisions:
- **`known_issues.json`** was not used for labels or H4. Its entries have no `source`, so
  they meet neither qualifying condition.
- **Adjudication.** The executor read 251 NHTSA narratives in full and accepted 62. Each
  accepted case records the repair sentence quoted from the narrative, and each rejection
  records its reason (`eval/sources/adjudication.json`). `verified_by` is pending Austin's
  spot-check. The set is frozen before that check. Any label the spot-check corrects ships as
  a new version, `eval-v1.1`, with its own tag and manifest; `eval-v1-frozen` never moves.
- **Replay pilot.** Real-vehicle captures are validated separately, through the
  replay-validity pilot (2026-08-25 entry). They are not part of the frozen set.

Touch rule, as amended by the fine-tune rulings below: it counts fine-tuned runs only.
Base-model runs (thinking on, thinking off) and the rule-based arm are fixed-model
conditions, not touches.
Evidence: `test_eval_scripts.py` passes 43 tests. `eval_validate.py` reported "102 cases, 30
codeless profiles, 0 errors". Run log: `notes/reports/logs/2026-09-25-phase-2.log`.

## [DECIDED] Eval transport (`eval_case`) and the served-thinking switch — 2026-09-26
Context: Brief 2a says to POST eval payloads to `/interpret` "in scenario mode". Scenario
mode only accepts a fixture *name* from `fixtures.py`, and 2a prohibition 4 keeps eval
cases out of there. The phone path (`client_codes`) hardcodes `is_mock=False`, so sending
eval payloads that way would write fake `research_scans` rows. Separately, ruling #1 of
the fine-tune entry below needs a thinking-off base run and a thinking-off fine-tuned
model, but the backend never sent a `think` key.
Decision (Austin, 2026-09-25: additive eval field; mechanism chosen by the executor):
- `/interpret` accepts an optional `eval_case` of the form `{case_id, vehicle, trim,
  snapshot}`. It runs the fixture code path unchanged, with the snapshot forced to
  `is_mock=True` and `fixture_name=case_id`. It writes only a `scans` row and never a
  `research_scans` row. A malformed case returns an error dict, not a 500. The scenario
  trim is now carried with the fixture instead of being looked up by name again, which
  gives the same result for scenarios.
- The served thinking mode is set in server config with the env var
  `CLEARDRIVE_THINK=default|off`. `default` sends no `think` key, so Qwen3 thinks. `off`
  sends `think: false`. Any other value stops the service from starting, so it can never
  silently run the wrong condition. `/health` reports `serving: {model, think}`, and
  `eval_run.py` records that in `run_meta.json`. A condition therefore changes only through
  the service environment and a restart, never through a public request field.

- Validation (`main._eval_fixture`, from review rounds 1 and 2):
  - `case_id` must be a non-empty string.
  - `vehicle` must be a non-empty object, with `year`, `make` and `model` as non-empty
    strings. Its other text fields must be strings or null; null means unknown and renders
    blank, as in the replay fixtures.
  - `trim` must be a string or null.
  - Snapshot readings must be finite; JSON `NaN` and `Infinity` are rejected.
  - Anything else returns an error dict. It never produces a 500 and never falls through
    to the live vehicle lookup.
  - Like a scenario, an eval case skips the live CarsXE decode (the gate is now "fixture
    path", not "scenario name"), so an eval response never depends on CarsXE being
    reachable that day.
  - When `eval_case` is set, the request-level `trim`, `transmission`, `color` and
    `client_mileage` are ignored, so a frozen case is the whole input.

Evidence: `test_eval_case.py`, 26 tests. They check that an eval case and the equivalent
fixture give identical safety, codes and data sources with no CarsXE call, that an eval case is never research-logged even
when its payload says `is_mock: false`, and that it uses its own trim. They check that
every malformed shape above is an error, that a null engine or transmission is accepted as
unknown, that non-finite readings are rejected, and that request-level fields cannot
override a case. They also cover the three
think-mode behaviours and the `/health` report. 89 passed with `test_knowledge.py` and
`test_diagnostics.py`. Review: round 1 FAIL (non-object vehicle), round 2 FAIL (vehicle
field types, case_id); fixed and rerun on Austin's instruction. Round 3 PASS; its two
IMPORTANT items (CarsXE on the eval path, non-finite readings) are fixed.

## [DECIDED] Brief 2 fine-tune rulings: thinking mode, training shape, synthesis LM — 2026-09-25
Context: `notes/reports/2026-09-25-phase-4.md` raised four items for Phases 5 and 6 (sequence
length, Qwen3's empty think block, pre-quantized training base, GGUF export on Windows).
Austin ruled 2026-09-25.
Decisions:
1. **Thinking mode.** The fine-tuned model is trained with Qwen3's empty think block
   (`apply_chat_template(..., enable_thinking=False)`) and served with thinking off. Base
   Qwen is measured in **both** modes as two separate conditions: thinking on (the default;
   the Phase 2 run) and thinking off (a second base run, added by the A4500 session). H1
   reports the fine-tuned model against both. Reason: it removes the "base only lost because
   it couldn't reason" objection instead of arguing about it.
2. **Touch rule scope.** Base runs are fixed-model conditions, not touches. The two-touch
   rule guards against iterating the fine-tune against the test set, so it applies to
   fine-tuned runs only.
3. **Training base vs served base.** Training loads `unsloth/qwen3-14b-unsloth-bnb-4bit`
   (Unsloth's auto-mapped pre-quantized copy of `Qwen/Qwen3-14B`, same weights; see
   `notes/reports/logs/2026-09-25-phase-4.log` L101). The served base on the A4500 is Ollama
   `qwen3:14b-q4_K_M`. Both conditions are served as Q4_K_M GGUF, which is the comparison
   that matters.
4. **Training shape.** `max_seq_length` 8192, batch 2 × grad accumulation 8 (effective 16),
   gradient checkpointing on. The length check stays: over-length pairs make
   `ml/train_qlora.py` refuse to train, never truncate.
5. **Pilot gate.** Phase 6 runs `ml/train_qlora.py --pilot` first (5% of train, 200 steps).
   The full run goes ahead only if pilot loss decreases over the 200 steps. Both logs go in
   the Phase 6 report.
6. **GGUF export fallback order.** (a) Unsloth prebuilt llama.cpp; (b) WSL2 Ubuntu with
   llama.cpp `convert_hf_to_gguf.py` on the merged safetensors, then quantize to Q4_K_M;
   (c) `ollama create` from the merged safetensors directory. Stop and report only if all
   three fail.
7. **Synthesis LM (Brief 2c override).** Synthesis goes through the Anthropic API directly,
   model `claude-opus-5-5`, key `ANTHROPIC_API_KEY`. Target 5,000 pairs (sample 5,500
   records in 2c step 3), concurrency 16. Targets are written in the empty-think chat
   layout, so training pairs and serving match. OpenRouter is not used anywhere.
   `claude-opus-5-5` is not an eval-condition model, so the contamination firewall holds.
Supersedes: 2c step 5.3 (`anthropic/claude-opus-4.5` or newer via OpenRouter, 4,000
records, concurrency 8). Also supersedes the "Claude Opus 4.7 via OpenRouter" synthesis
lines in `ml/CLAUDE.md` and this log's 2026-05 ETL entries, and the Phase 4 script
defaults (4096, batch 4 × accum 4).
## [DECIDED] Output budget 4,096 with default thinking; finish reason exposed — 2026-09-25
Context: Qwen3 thinks by default, and the thinking tokens count against `num_predict`.
With the budget at 2,800, a long case could be truncated. Brief 2a's runner has to count
truncations, but `/interpret` never exposed Ollama's `done_reason`.
Decision (Austin, 2026-09-25):
- Thinking stays at the model default, which is on, for both the base and the fine-tuned
  conditions. Disabling it would handicap the base condition.
- `num_predict` goes from 2,800 to **4,096** in `ollama_client.py`. The fine-tuned run in
  Phase 6 uses the same value. Worst case: the M6 prompt of 5,822 tokens + 4,096 = 9,918 of
  16,384.
- `ask_ollama` records `done_reason` in a per-request `ContextVar`. `/interpret` returns it
  as the additive field `finish_reason` on both the coded and no-codes paths, and it is null
  when Ollama omits it. Old iOS builds ignore the field.
- `eval_run.py` records the finish reason for every call. If more than 5% of a run is
  truncated (`finish_reason == "length"`), stop and report before scoring.

Evidence: `test_diagnostics.py` pins `num_predict` 4096, `num_ctx` 16384 and the absence
of a `think` key, plus `finish_reason` on both paths. It is null when Ollama omits it or
when the response cannot be parsed. Result: 63 passed with `test_knowledge.py`. The live
regression output is in `notes/reports/logs/2026-09-25-phase-2.log`, committed with the
Phase 2 report.

## [DECIDED] Retrieval model-name normalization fixed 2026-09-25 before eval freeze and before the replay real arm; applies equally to all conditions — 2026-09-25
Context: NHTSA lookups returned HTTP 400 for the 2015 F-150, the 2014 Land Cruiser and
"A4 quattro", so those prompts carried no complaints. The 400 is not a malformed request.
NHTSA returns it with the body `{"count":0,"results":[]}` when it files the vehicle under
a different model name. The two endpoints spell models differently:
- **Complaints** uses `F-150 REGULAR CAB` / `SUPER CREW` / `SUPERCAB` and `LANDCRUISER`.
- **Recalls** accepts `F-150` and `Land Cruiser`, and returns 400 for `LANDCRUISER`.

`httpx` already URL-encodes query parameters. The ruled fallbacks (URL-encode, strip trim
words, first token) would have fixed only the A4.

Decision (Austin, 2026-09-25, which replaces the first ruling): `knowledge.py` only. When
an endpoint returns 400, fetch NHTSA's own model list for that endpoint
(`api.nhtsa.gov/products/vehicle/models`, with `issueType` `c` or `r`). Compare names with
case, spaces and hyphens removed, in this order:
1. an exact match;
2. an exact match after stripping trailing drivetrain/trim words (quattro, hybrid, awd,
   4wd, fwd, rwd, xdrive, 4matic, 4motion);
3. every NHTSA name whose leading words equal that key and whose remaining words are all
   cab/body-style words (`REGULAR`, `SUPER`, `CREW`, `CAB`, `SUPERCAB`, `CREWMAX`, …; no
   drivetrain words, so a query never picks up another drivetrain's records),
   so `F-150` picks up `F-150 SUPER CREW`. Code review found that a plain prefix match
   would have attached `COROLLA CROSS` complaints to a `COROLLA` query; that is a different
   vehicle line, so this step only accepts body-style suffixes.

Results from all matched names are merged, deduplicated on the ODI or campaign number, and
capped as before (10 complaints, 5 recalls). The names used are logged. Every name comes
from NHTSA and none is guessed. `diagnostics.py` and the prompts are untouched. The fix is
about 45 lines, over the ruled 30, which was accepted with this design.

The frozen-files rule exists so that every condition is measured on the same system.
Nothing has been measured yet, so a retrieval fix made before touch one is legitimate.

Evidence: live regression set, before → after (complaints / recalls), logged in
`notes/reports/logs/2026-09-25-phase-2.log`:

| Vehicle | Before | After | Matched names |
|---|---|---|---|
| 2015 Ford F-150 | 0 / 5 | 10 / 5 | three cab variants |
| 2014 Toyota Land Cruiser | 0 / 4 | 2 / 4 | `LANDCRUISER` |
| 2015 Audi A4 quattro | 0 / 0 | 10 / 0 | `A4` |
| 2015 Audi A4 | 10 / 0 | 10 / 0 | unchanged |

NHTSA has no recalls for the 2015 A4; the direct query also returns 0. `test_knowledge.py`
has 12 offline tests that replay the observed NHTSA behaviour. They cover the Corolla Cross
case, drivetrain variants, a falsy-id dedupe, a non-400 error and a failed model-list call.
The last two return `[]` through the existing error handler, never as a silent absence.

**Bearing on the replay pilot.** The synthetic arm (merged 6702d77) ran before this fix, so
the Land Cruiser and A4 had no complaints in their prompts. The pre-registration requires
rerunning BOTH arms when a cause is fixed. The synthetic arm must therefore be rerun before
the real arm is compared.

## [DECIDED] Base model pinned: Qwen3-14B dense — 2026-09-25
Context: Weekend Brief 2 (`docs/briefs/weekend/brief-2-weekend-master.md`, Phase 1.1)
needs a pinned base model serving on the A4500 before the eval set can be baselined and a
fine-tune built by Sunday 2026-09-27. Austin ruled 2026-09-25.
Decision: base model is **Qwen3-14B dense**. Serving: Ollama `qwen3:14b-q4_K_M` (already on
the A4500, 14.8B, Q4_K_M, digest `bdbd181c33f2…`; no pull), wrapped as `cleardrive-qwen`
by `~/cleardrive-qwen.Modelfile` (`num_ctx 16384`, `temperature 0.2`). Training: HF
`Qwen/Qwen3-14B`, with `unsloth/Qwen3-14B` as the fallback mirror (Phase 4.2). Gemma 4 E4B
was a placeholder and is retired from serving. `research_scans.model_version` is
`qwen3-14b-base` for this condition and `qwen3-14b-ft` after Phase 6. That label is how the
conditions are told apart in the table.
Reason: the prompt fits the 16k context with margin, the model is under 30B total params,
it uses standard attention with verified Unsloth QLoRA support, and the fine-tune has to
exist by Sunday.
Evidence: largest fixture prompt measured with the served model's tokenizer (Ollama
`prompt_eval_count`, system + user + chat template) is **5,822 tokens**
(`m6-2014-bank1-lean-misfire-hard`). The other coded fixtures measured 4,200–5,122; a
repeat send gave an identical count, so prefix caching is not affecting it. 5,822 +
`num_predict` 2,800 = 8,622 of 16,384. The ruling cited ~7,900, which was the 2026-07-28
estimate (~5,100 + 2,800); the measurement replaces it. This is the maximum over the 14
fixtures, not a proven worst case, because retrieval volume varies by vehicle. VRAM with
the model resident at 16k context: 14,071 MiB of 20,470. Qwen3 thinks by default; on
Ollama 0.24 without a `think` key the reasoning lands in `message.thinking`, not
`content`, so `parse_guidance()` sees clean sections. On M6 that was 12/12 sections,
`done_reason stop`, 1,508 output tokens including thinking (within 2,800), 36.5 s.
Log: `notes/reports/logs/2026-09-25-phase-1.log`.
Supersedes: [DECIDED] Pivot to Qwen MoE (2026-07-27), whose target family was MoE. Closes
[OPEN] Canonical Qwen SKU. This ruling does not address the earlier SGLang decision; serving
is on Ollama as measured.

## [DECIDED] Replay-validity pilot: pre-registered agreement criteria — 2026-08-25

Context: the whole evaluation methodology runs on frozen replay fixtures. The pilot
tests whether a synthetic payload built to contain exactly what the adapter can pull
behaves like a real capture from the same car. Synthetic arm is frozen: 15 runs
(3 cars × 5 reps, VIN-decoded facts, mileage null), all `ok`, Tier-1 rubric 105/105
applicable, merged at 6702d77. **This entry is written before any real capture
exists.** The criteria below are fixed now so that agreement is not defined after
looking at the results. No post-hoc reclassification: a criterion that fails is
reported as failed with its cause; fixing the cause means rerunning BOTH arms, not
editing this entry.

Real arm protocol: TestFlight on the physical 2014 Land Cruiser, 2015 A4 2.0T
quattro, 2004 V70 2.5T; 5 reps per car without disconnecting; mileage left blank.
Captures land in `scans`/`research_scans` server-side.

**Primary criteria — all three must hold, per car, for the fixtures to be declared
replay-valid on that car:**
1. **Verdict agreement 5/5.** Every real rep's `safety.verdict` equals the synthetic
   verdict (`ok`). Exception, declared now: if a real car reports one or more generic
   OBD codes, the condition itself differs from the fixture, so that car's verdict
   comparison is **void** (condition mismatch, not replay invalidity) and the car
   becomes a coded-path data point instead. The V70's SRS fault is manufacturer-
   specific and predicted invisible to generic OBD; if it shows up anyway, that is
   this exception firing, and also a capability-prediction miss under criterion 4.
2. **Retrieval source set identical.** For each car, the set of retrieval sources hit
   (`data_sources` minus CarsXE) is the same in every real rep as in the synthetic
   arm. Known risk, declared now: the app-side decode may yield "A4 quattro" where
   the fixture uses VPIC's "A4"; if the Audi's real reps lose the NHTSA complaints
   hit, that is a **fail** of this criterion attributed to the name-normalization
   bug — it is not excused.
3. **Tier-1 rubric zero failures.** `scripts/rubric_score.py` on the real responses
   passes every applicable check, same standard the synthetic arm met (105/105).

**Secondary — logged either way, no pass/fail:**
4. **V70 capability prediction.** Fixture predicts a pre-CAN car: no Mode 06, no
   permanent codes. Real capture is recorded as-is; prediction correct or incorrect
   is a finding about protocol-era capability limits, never a failed run.
5. **Mileage.** Fixtures encode `null` on the prediction the adapter cannot read it.
   Any real capture that reports mileage is a payload-shape divergence, noted per car.
6. Latency, `summary_chars`, `known_issues_chars` distributions — descriptive only.

**Blinding.** Tier-1 is a deterministic script (9 binary regex/equality checks) — no
human judgment, nothing to blind. The two subjective instruments ARE blinded: the
`invented_numbers` review queue and any Tier-2 claim scoring are adjudicated on
pooled outputs with arm labels stripped and order shuffled (seeded), unblinded only
after scores are recorded.

**Scope, stated now for the methods section:** n=3 cars × 5 reps tests within-car
reproducibility of the synthetic↔real correspondence on three specific platforms. It
does not support a fleet-generalization claim, and no car-level p-value is possible
at n=3; claim-level testing (Fisher's exact, with clustering caveat) comes later.

## [DECIDED] Headless fixture smoke runner is the baseline instrument (Brief 1c) — 2026-08-21
Context: the fixture sweep was run by hand, once, through the iOS client or ad-hoc scripts.
Decision: `scripts/smoke_run.py` POSTs every fixture scenario to a running server
exactly as iOS does, saves each raw response to `runs/smoke_<date>/` (gitignored), and
prints one row per fixture: verdict, codes, definition-tier counts, retrieval sources,
model-adherence to the computed label, seconds. Adherence is read back from the
`scans` table via `scan_id` (the raw model text is stored there), so no pipeline code
changed. Columns are mechanical facts only; no LLM judging. Non-zero exit on any error
or missing `safety`.
Evidence: first full run against the 1b code found that the no-codes path shipped no
`safety` field (fixed on 1b, 101cf06). Final run: 11/11 clean, verdicts 6 ok / 1
caution / 3 stop / 1 insufficient, 10/10 coded fixtures adhered, mean 13.6 s. The
no-codes fixture reports adherence `n/a` — that path uses a SUMMARY/SERVICE/KNOWN
prompt with no SAFETY LEVEL line, so there is nothing to compare.
Server facts the same day are in `notes/2026-08-21-server-sanity.md`: Ollama serving,
`num_ctx` 16384, GPU at 91–93 % during a request, production checkout stale at 18cd60c.

## [DECIDED] Safety verdict is computed, not narrated (Brief 1b) — 2026-08-21
Context: the model assigned SAFETY LEVEL from prose. Measured on the unmodified code
the same day, 8 of 10 fixtures came back CAUTION (civic P0442 and the clean RAV4 were SAFE) — a misfire at
72% load, a marginal catalyst, and a vehicle that reported nothing all got the same
label. Severity was the one field the driver acts on and it carried no information.
Decision: `diagnostics.compute_safety(result, snapshot, vehicle_data)` is a pure
function of rule output and payload. Ordinal scale `ok < caution < stop_driving`;
`insufficient_data` is an abstention outside the scale. Max-wins escalation, every
escalation carries evidence pointers. Rules: misfire → CAUTION, misfire with freeze-
frame load ≥ 60% / coolant ≥ 180°F / Mode 06 misfire fail → STOP; coolant > 230°F →
STOP; |total trim| ≥ 25% → CAUTION; high-confidence `manufacturer_limit` finding →
CAUTION floor; status findings never move the verdict. Codes present, nothing
escalated, and a relevant measurement null → INSUFFICIENT (interpreted as *any*
applicable rule blocked, not *every* one — an OK the payload cannot support is a
fabricated default). Thresholds are tagged heuristic in every reason. The prompt now
hands the model the verdict and its reasons and tells it to write the label verbatim;
the SAFE/CAUTION/STOP criteria block and "Don't be afraid to use STOP" are deleted. A
model that writes a different label is logged as non-adherence and overridden.
`response_data["safety"]` carries the full verdict; legacy `safety_level` maps
ok→SAFE, caution→CAUTION, stop_driving→STOP, insufficient_data→UNKNOWN (new
`SAFETY_DEFINITIONS` entry, additive). Model failure no longer downgrades the level to
UNKNOWN — the computed verdict stands without narration.
Evidence: `test_diagnostics.py` 37 passed (16 prior + 21 new; hand-label table in the
file). Fixture distribution after: 6 ok / 3 stop_driving / 1 insufficient_data / 0
caution — the CAUTION rules are covered by constructed-snapshot unit tests, no fixture
was added or edited.
Ruling (same day): added `tacoma-2009-p0171-severe-trim-synthetic`, the one CAUTION
fixture (severe trim, no misfire); distribution is now 6 ok / 1 caution / 3 stop / 1
insufficient. Misfire + warm freeze frame (coolant ≥ 180°F, tagged heuristic in the
reason) → STOP is **deliberately conservative** pending calibration against the frozen
eval set; the cost of a false STOP is a tow, the cost of a false CAUTION is a converter.
Defect found by the Brief 1c smoke runner (same day): the no-codes path of `/interpret`
returned before `compute_safety` ran, shipping the hardcoded SAFE placeholder and no
`safety` field. Fixed: the verdict is computed on that path too, and `compute_safety`
no longer short-circuits on an empty code store (an overheating engine with no codes
is STOP; missing data with no codes is OK, not INSUFFICIENT). 40 tests.
`SAFETY_MISFIRE_CODES` covers P0300–P0312 per the brief while `MISFIRE_CODES` in the
triage rule still stops at P0308 — left as-is under the no-rule-changes prohibition.

## [DECIDED] Rule coverage, cause/status split, M6 hard case, regression suite — 2026-07-28
Follows the payload-v2 entry below.
- **New rules.** `rule_oxygen_sensor` separates a failed sensor from one correctly
  reporting a real fuelling fault — when trims corroborate the sensor, the finding says
  replacing it will not fix anything, which is the expensive misdiagnosis it exists to
  prevent. `rule_unmatched_codes` guarantees a code with no rule is still named, so the
  response never implies a code was considered when it was not.
- **Rules take a vehicle context** (`analyze(snapshot, vehicle, engine_profile)`). Used
  only for configuration facts that change which physical checks are possible — a boost
  leak requires an engine that makes boost. It is NOT a channel for platform lore;
  nothing asserts what fails on a given make.
- **Bank-specific lean that worsens under load** now yields a second finding: a vacuum
  leak fades as airflow rises, so the opposite pattern points at fuel delivery or a
  post-turbo leak.
- **`Finding.kind`: `cause` vs `status`.** Pending/permanent codes are facts about the
  codes, not causes. Mixed together, the model numbered "there are permanent codes" as a
  likely cause. Carried separately in the response as `code_status`.
- **`all_checks()` de-duplicates** recommended checks across rules. Two rules sharing a
  check made the model repeat it verbatim, correctly, because it was told not to omit.
- **`ESTIMATED REPAIR COST` regression.** Anchoring header matching lost this section:
  the old substring match saw "REPAIR COST" inside it, prefix matching does not, and the
  header was absent from `section_map`. Added, plus a test asserting every header the
  prompt emits resolves — this class of bug is silent by construction.
- **`num_predict` 1600 → 2800.** A 7-finding differential truncated mid-sentence.
- **`test_diagnostics.py`**, 16 tests, offline, no model or network. The repo previously
  had no real test of this layer (`test_api.py` is an ad-hoc script that GETs
  fueleconomy.gov). Runs under pytest or standalone.
- **New fixture `m6-2014-bank1-lean-misfire-hard`** — 2014 BMW M6 4.4L twin-turbo, seven
  codes across four systems, built so each code read alone points somewhere different
  from all of them read together.

Measured on that fixture: prompt ~5,100 tokens, response ~1,400, **12/12 sections**.
Reinforces `[OPEN] Canonical Qwen SKU` — worst case is now ~5,100 input + ~2,800
`num_predict` ≈ 7,900 tokens, above the ~6,500 the existing budget assumed, and the
UDS/P1xxx work will push it further.

## [DECIDED] Payload v2, rule engine, tiered code definitions, retrieval — 2026-07-28
Landed on `brief-1a-truth-fixes` after 1a. Six pieces:
  1. **Parser fixed.** `parse_guidance` matched headers as substrings against every line,
     so prose containing "DATABASE"/"SERVICE"/"COMMUNITY" silently opened a section — and
     the prompt itself contained "CAR DATABASES". Matching is now anchored: a line is a
     header only as the label before a colon or as a short all-caps line, matched by
     prefix, longest header first. The `DATABASE` key is deleted. **Every format-adherence
     number measured before this commit was partly grading this bug.**
  2. **Payload v2** (`schemas.py`): freeze frame, fuel trims at stated conditions, Mode 06
     with manufacturer limits, pending/permanent codes, user-entered mileage, and a
     `CapabilityProfile`. All optional with null defaults; `obd_reader.py` unchanged.
  3. **Rule engine** (`diagnostics.py`): Layer 1 derivation (total trim, idle-vs-load
     delta, bank asymmetry, Mode 06 margin) and Layer 2 rules that ABSTAIN with a stated
     reason rather than guess. Findings carry `Evidence.pointer` into the payload.
     Thresholds are tagged `heuristic` — they are shop convention, not a standard.
  4. **Tiered code definitions** (`dtc_definitions.py`): `standardized_unverified` |
     `oem_verified` (none yet) | `structural_only`. Manufacturer-specific codes never get
     a guessed meaning — including the 12 P1xxx entries in `ml/data/sae_j2012.json`,
     which are ignored outright.
  5. **Retrieval wired** (`knowledge.py` → `/interpret`): NHTSA complaints, NHTSA recalls,
     and the local KB inside `<retrieved_context source= retrieved_at=>`, `NONE` when
     empty, try/except so failure degrades rather than fails. Both code paths.
  6. **Fixtures** (`fixtures.py`): 9 deterministic scenarios incl. a no-capability vehicle
     and a manufacturer-code case. `POST /interpret {"scenario": "..."}`.

### Two prompt defects found by running it
- **`ollama_client.py` SYSTEM_PROMPT rules 5 and 9** told the model to "provide general
  advice" for any section lacking data, and to fill KNOWN ISSUES "even if you have to
  provide general advice." A fourth gap-filling instruction, one file outside `main.py`,
  silently overriding the user prompt. Rewritten.
- **`num_ctx` was never set, so Ollama used its 4096 default.** The payload-v2 prompt is
  ~4,000 tokens, so the response-format instructions were being truncated out of the
  window. Observed effect: first the model invented its own report structure, then it
  degenerated into repeating `SAFETY LEVEL: CAUTION` to the token limit. Set to 16384,
  `num_predict` 4000 → 1600, `repeat_penalty` 1.15. Sections went 1/12 → 11/12 with no
  other change.

### Bearing on open decisions
- **`[OPEN] Canonical Qwen SKU`:** this is the missing worst-case measurement. The v2
  prompt with retrieval is ~4,000 input tokens against the ~2,000–2,500 typical case in
  `notes/2026-05-23-production-context-size.md`, confirming that entry's warning. Demand
  is roughly 4,000 + `num_predict`; the P1xxx/UDS work will push it further.
- **PR #8 "fine-tuning is load-bearing":** the parser bug did contaminate that measurement,
  but the observed failures here were genuine model behaviour at correct context, not
  parser artefacts. My earlier suggestion that re-measurement might overturn that
  conclusion is withdrawn — it is more likely to survive than not. Re-measure anyway.
- Evidence for the JSON contract + constrained decoding: both observed failure modes
  (invented structure, repetition loop) are structurally impossible under grammar-
  constrained decoding, and neither needs training to prevent.

### Known gaps
- `known_issues.json` is keyed make/model/year with no engine field and no mileage
  windows, against a rule requiring engine keying. Mileage is threaded through and
  reported but not yet matched to a window.
- On the abstention fixture the model listed abstentions as if they were numbered causes.
  Honest but clumsy; prompt wording, not correctness.
- No rule covers O2-sensor-response codes, so `escape-2013-p1131-mfg-code` produces no
  findings. Rules cover what has been written; the empty-differential path handles it.
- Fixtures are development and regression only. They encode assumptions about vehicle
  behaviour and cannot validate diagnostic logic — that needs real captures.

## [DECIDED] Brief 1a — truth fixes in `/interpret` — 2026-07-27
Context: `/interpret` substituted invented telemetry for missing measurements, instructed the
  model to recall TSBs and known issues from its weights, logged demo/mock scans into
  `research_scans`, and injected live-scraped web content into the prompt.
Decision, all landed on `brief-1a-truth-fixes`:
  1. Missing telemetry is `null`, never a substitute. `is not None`, not truthiness — the old
     `if snapshot.rpm else 750` turned 0 RPM (engine off) into a warm idle and 0 F coolant
     into 205 F. Verified safe for clients: `APIClient.swift:915-917` already declares `Int?`,
     `index.html:1901-1916` already null-checks. No schema or iOS change.
  2. Recall instructions deleted from both prompt paths. `KNOWN ISSUES` in each is now
     "use ONLY sourced material above; if none, say no verified issue history was available."
     With retrieval not yet wired (1b), that sentence is the expected output — correct per the
     governing principle: a generic answer beats a confidently wrong known issue.
  3. Mock/demo scans no longer reach `research_scans`. Gate is `snapshot.is_mock`, not the
     `obd_source` string — `obd_source` has two demo spellings and its client-supplied value
     is unvalidated, so it cannot carry the decision. `ClientSnapshot` grew `is_mock = False`.
  4. Reddit deleted from `/interpret`; `code_scraper` (OBD-Codes / CarComplaints / RepairPal)
     gated behind `ENABLE_SCRAPED_CODE_CONTEXT`, default off. `forum_scraper.py` stays on disk
     because `scrape_training_data.py:75` imports its primitives.
  5. `log_research_scan` reads telemetry off the snapshot, not out of `response_data`.
Rationale for removing scrapers: reproducibility, not ToS. Per-request live scraping makes
  prompt content depend on what a website said that day, so a baseline is not reproducible and
  eval arms are not comparable across time. Fatal at WESEF independent of copyright exposure.
Contamination audit — **no quarantine needed.** Production
  `/home/abrennan/cleardrive/cleardrive.db` (confirmed via `WorkingDirectory` in
  `cleardrive.service`; `DB_FILE` is a relative path) holds **0 rows in `research_scans` and
  0 in `scans`**. Tables exist from startup init; nothing was ever logged. Dev-tree snapshots
  hold 2 `scans` rows and no `research_scans` table at all. Every fix above is prophylactic.
Corpus provenance — **the fine-tuning corpus is generated offline, not harvested from
  production.** Nothing outside `database.py` reads `research_scans`. The corpus is
  `training_data/raw/` built by `scrape_training_data.py`, then Opus-4.7-distilled per
  `ml/notes/synthesis_design.md`. The "production output becomes training data" argument used
  to justify sequencing does **not** hold today. `research_scans` is eval/telemetry
  infrastructure that is *designed* to become training data later (see its docstring), so the
  fixes remain correct — but the urgency claim was overstated and is withdrawn.
Supersedes: nothing. Extends Never #7 in `CLAUDE.md`.

## [OPEN] Scraped content in the training corpus
The prompt-path ban on scraped content is settled (Never #7). The corpus half is not.
`training_data/raw/` (marked read-only source of truth in `ml/CLAUDE.md`) is built from Reddit,
RepairPal, CarComplaints, and NHTSA by `scrape_training_data.py`, and
`ml/notes/synthesis_design.md` sources `OTHER OWNERS REPORT` from Reddit data. Applying the ban
to the corpus invalidates both the existing corpus and the ETL synthesis design.
Blocked on: a decision about whether the reproducibility argument that removed scrapers from
  the prompt applies with equal force to a one-time frozen corpus snapshot — where the
  "depends on what a website said that day" objection is weaker, since the corpus is fixed and
  hashable, but the provenance objection stands.
Must be settled before the synthesis run.

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

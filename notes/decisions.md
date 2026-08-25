# Decisions log

Append-only. Most recent first. Each entry is a settled commitment — don't relitigate without escalating. For session-by-session strategic reviews, see `notes/council/decisions/`.

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

# Brief 2a: Eval set construction, freeze, and baseline run

Executor: Claude Code, run from the ClearDrive repo root on Windows (Git Bash). Steps 12 and 13 run against the A4500.
Architect: Claude Opus. This brief is the spec. Do not redesign it. If a step cannot be done as written, stop and report why in the output file (step 15) instead of substituting.

## Purpose

H1, H2 and H4 are comparisons. Both sides must be measured on the same locked test. This brief builds that test, freezes it, and records the baseline against the system as it is today. Nothing in this brief improves the system.

## Hard prohibitions

1. Do NOT modify diagnostics.py, dtc_definitions.py, knowledge.py, main.py, any prompt text, or any file under ios/. If a bug blocks a step, log it in the report and continue or stop. Do not fix it.
2. Do NOT start, configure, or scaffold any fine-tuning, QLoRA, DSPy, or GEPA work.
3. Do NOT use model recall for ground-truth labels. Every label comes from a documented source with a URL or a file path in the repo. A case with no source is not a case.
4. Do NOT copy any eval case, in whole or in part, into fixtures/ or any dev test data. Eval cases live only under eval/.
5. Do NOT modify or delete anything under research_scans/ or the replay-validity pilot artifacts (PR #18).
6. Do NOT copy expressive prose from obd-codes.com, troublecodes.net, RepairPal, or CarComplaints. Facts only, restated.
7. Do NOT change which model or inference server is running on the A4500. Baseline is measured on whatever is live.
8. Do NOT run the eval set more than once in this brief. Frozen means touched twice for the whole project: once here (baseline), once after fine-tuning (final).

## Steps

### Step 0: State check (do this before anything else)

1. `git status`, `git log --oneline -15`, `git tag`.
2. `ls -R eval/ 2>/dev/null` and `find . -iname "*eval*" -not -path "./node_modules/*" -not -path "./.git/*"`.
3. `grep -n -i "eval set\|frozen\|freeze" notes/decisions.md`.
4. Report in the output file: does an eval set already exist? Is there a freeze tag or manifest? If a frozen set with a manifest and SHA256 already exists, STOP after step 0 and report. Do not build a second one.

### Step 1: Inventory the label space

1. Read diagnostics.py. List every distinct fault class / finding type it can emit, with the rule that produces it.
2. Read dtc_definitions.py and sae_j2012.json. List the DTC families present (P01xx fuel/air, P02xx injector, P03xx ignition/misfire, P04xx emissions, P05xx speed/idle, P06xx computer, P07xx transmission, and any others in the table).
3. Write eval/taxonomy.json: a flat list of fault class labels. Source: the classes from 1.1 first, then DTC families from 1.2 as a fallback for anything diagnostics.py does not cover. Do not invent classes not grounded in one of those two sources. Each entry: `{"label": "...", "source": "diagnostics.py:<rule>" | "dtc_family:<Pxx>", "description": "<one line>"}`.
4. Target: 10 to 16 labels. If the inventory yields more than 16, merge only within the same DTC family and log each merge.

### Step 2: Define the case schema

Write eval/schema.json (JSON Schema, draft 2020-12). One eval case is:

```
{
  "case_id": "EV-001",
  "case_type": "reconstructed" | "synthetic",
  "vehicle": {"year": int, "make": str, "model": str, "engine": str | null, "obd_era": "pre-CAN" | "CAN" | "OBDonUDS"},
  "payload": { <exact shape the /diagnose endpoint accepts in scenario/fixture mode> },
  "ground_truth": {
    "fault_labels": [ <one or more labels from eval/taxonomy.json> ],
    "primary_label": <one label>,
    "confirmed_repair": str,
    "source_url": str,
    "source_type": "nhtsa_complaint" | "nhtsa_recall" | "known_issues.json" | "synthetic_from:<label>"
  },
  "h2_expected_specificity": ["<vehicle-specific fact 1 a good answer must mention>", "..."],
  "provenance": {"created": "YYYY-MM-DD", "created_by": "brief-2a", "notes": str}
}
```

Take the payload shape from what main.py's diagnose endpoint actually parses in scenario mode. Read the code. Do not guess the shape.

### Step 3: Build the reconstructed cases (type b)

1. Pull from the NHTSA complaints API (already wired in knowledge.py; reuse its client, do not write a new one) for the top 12 US nameplates by BTS fleet share plus every vehicle in known_issues.json.
2. Keep only complaints that state a DTC and a confirmed repair outcome in the narrative. Both must be present. Log the filter counts (fetched / had DTC / had repair / kept).
3. For each kept complaint, construct a payload: the stated DTC(s), plausible freeze-frame values consistent with the fault (mark these as constructed in provenance.notes), vehicle from the complaint.
4. Label with the fault class from the confirmed repair, not from the DTC. Example: P0420 with confirmed repair "replaced upstream O2 sensor" labels as O2 sensor, not catalyst.
5. Target: at least 60 reconstructed cases.

### Step 4: Build the synthetic cases (type c)

1. For every label in taxonomy.json with fewer than 5 reconstructed cases, add synthetic cases until each label has at least 5.
2. Synthetic payloads are constructed from the deterministic rules in diagnostics.py (e.g. fuel trim values that trip the lean rule). ground_truth.source_url is the path to the rule in diagnostics.py. source_type is "synthetic_from:<label>".
3. Cap synthetic at 40% of the total set. If the cap prevents reaching 5 per label, leave the label short and log it.

### Step 5: Build the codeless set (H4)

Write eval/codeless_set.json. Schema: same as step 2 with `payload.dtcs` empty and `ground_truth.fault_labels` replaced by `ground_truth.documented_issues`: a list of `{"issue": str, "source_url": str, "source_type": "nhtsa_complaint" | "nhtsa_recall" | "known_issues.json"}`.

1. Source: known_issues.json entries plus NHTSA recall/complaint clusters for the same top nameplates. A profile qualifies only if at least one documented issue has 2 or more independent sources or is a recall.
2. Payload: vehicle identity, mileage, and a no-code live-data snapshot within normal ranges.
3. Target: at least 30 profiles across at least 8 makes and all three OBD eras.
4. H4 scoring rule (write it into the file header): a hit is when the model's output names at least one documented issue for that profile. Threshold is 50% of profiles (pinned, do not change).

### Step 6: Validate

1. Write scripts/eval_validate.py: every case validates against schema.json; every label exists in taxonomy.json; every source_url is non-empty; case_ids unique; no case_id or payload appears anywhere under fixtures/.
2. Run it. Zero errors before proceeding.

### Step 7: Stratification report

Write eval/composition.md: counts by case_type, by label, by make, by obd_era; synthetic share; labels below 5. This goes in the paper's methods section, so make it honest.

### Step 8: Freeze

1. Compute SHA256 of eval/eval_set.json, eval/codeless_set.json, eval/taxonomy.json, eval/schema.json. Write eval/MANIFEST.json with the hashes, case counts, and freeze date.
2. Commit on branch `brief-2a-eval-freeze`. Tag `eval-v1-frozen`.
3. Append to notes/decisions.md: date, tag, counts, the two-touch rule, and that real-vehicle captures are validated separately via the replay-validity pilot and are not part of the frozen set.

### Step 9: Confirm what is serving

SSH to the A4500. Record: inference server (ollama or sglang), model name and quant, `num_ctx` (must be at least 8192; if lower, STOP and report, do not change it), commit of the backend that is deployed.

### Step 10: Write the runner

scripts/eval_run.py: iterates eval/eval_set.json and eval/codeless_set.json, posts each payload to the diagnose endpoint in scenario mode, saves the full raw JSON response per case to eval/runs/<run_id>/<case_id>.json plus a run_meta.json (date, server, model, num_ctx, backend commit, wall time per case). Retries once on transport error, then records the failure. Never edits the eval files.

### Step 11: Write the scorer

scripts/eval_score.py, deterministic parts only:
1. H1: extract predicted fault labels from the response (map the response's differential / findings onto taxonomy.json labels; write the mapping table into the script and log every unmapped prediction). Compute per-label precision, recall, F1 and macro-F1. Also compute the same for the rule-based arm: DTC lookup only (dtc_definitions.py output with no model), mapped by DTC family.
2. H4: hit / miss per profile against documented_issues; hit rate.
3. Latency: mean, p50, p95 from run_meta.json.
4. H2 rubric scoring requires the Opus judge via OpenRouter (integrity firewall). Do NOT call the judge in this brief. Emit eval/runs/<run_id>/h2_pending.jsonl containing case_id, response text, and h2_expected_specificity, ready for the judge step in a later brief.

### Step 12: Baseline run

Run scripts/eval_run.py once. run_id = `baseline-<date>`. This is touch one of two.

### Step 13: Score

Run scripts/eval_score.py on the baseline run. Output eval/runs/baseline-<date>/scores.json and scores.md.

### Step 14: Commit

Commit runner, scorer, and run outputs on the same branch. Do not squash into the freeze commit; the freeze commit must predate the run commit in history.

### Step 15: Report

Write notes/<date>-brief-2a-report.md with exactly these sections:
1. Step 0 findings (pre-existing eval state)
2. Taxonomy (label list with sources)
3. Composition (counts, synthetic share, short labels)
4. Freeze (tag, hashes)
5. Serving state at baseline (server, model, num_ctx, backend commit)
6. Baseline scores (macro-F1 model vs rule-based, per-label table, H4 hit rate, latency)
7. Unmapped predictions and parser failures (count and examples)
8. Bugs observed but not fixed (per prohibition 1)
9. Anything skipped or blocked, with the reason

## Acceptance criteria

1. eval/ contains eval_set.json, codeless_set.json, taxonomy.json, schema.json, MANIFEST.json, composition.md.
2. eval_validate.py passes with zero errors.
3. At least 100 eval cases and 30 codeless profiles; synthetic share at most 40%; at least 8 makes; all three OBD eras represented.
4. Tag eval-v1-frozen exists and its commit predates the baseline run commit.
5. decisions.md has the freeze entry.
6. Baseline run directory has one response JSON per case, run_meta.json, scores.json, scores.md.
7. Report file exists with all nine sections filled.
8. `git diff eval-v1-frozen -- eval/eval_set.json eval/codeless_set.json eval/taxonomy.json eval/schema.json` is empty at the end of the brief.

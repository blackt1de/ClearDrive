# ClearDrive — Execution Briefs v2 (Implementation Grade)

Architect output. The executor implements exactly what is specified. If a step is impossible against real code, **stop and report** — do not substitute a design.

Paste ONE brief per Claude Code session. Fresh session per brief (context hygiene). Do not begin brief N+1 until brief N's acceptance commands pass.

Repo: `github.com/blackt1de/ClearDrive` · Backend `main.py` (1864 lines) · iOS `ios/ClearDrive/`
Verified anchors as of this writing: `/interpret` at `main.py:1097` · `InterpretRequest` at `:73` · `parse_guidance` at `:100` · fabricated defaults at `:1237` and `:1239` · TSB-recall prompt line at `:1435` · engine known-issues prompt at `:1606–1610` · unused retrieval entry points `knowledge.py:178` and `:197`.

---

## 0. SESSION CONVENTIONS (append to `CLAUDE.md`)

1. Read the brief fully before editing. Restate the plan in ≤10 lines, then execute.
2. Verify every line anchor before editing — line numbers drift. Anchor on the quoted string, not the number.
3. One brief = one branch = one PR. Branch name `brief-N-slug`.
4. Never `git push --force`. Never amend a pushed commit.
5. After each brief: run its acceptance commands, paste raw output into the PR body, append the `decisions.md` entry.
6. When a step's precondition is not met (file missing, function differs), stop and report the discrepancy with the actual code quoted. Do not improvise.
7. Do not refactor adjacent code "while you're in there." Diffs stay scoped to the brief.
8. All new data files carry `source`, `verified_by`, `verified_at`. No exceptions.

---

## 0b. MODEL ROUTING

Current lineup and the relevant facts: <cite index="18-2">Opus 5 (released July 24, 2026) at $5/$25 per MTok, SOTA on Frontier-Bench, 3× next-best on ARC-AGI-3, 1M context, May 2026 knowledge cutoff</cite>; <cite index="18-4">Sonnet 5 at $3/$15 ($2/$10 intro through Aug 31) scoring 85.2% SWE-bench Verified and 80.4% Terminal-Bench</cite>; <cite index="23-2">Fable 5 at $50/1M output, edging Opus 5 on SWE-bench Pro by 0.8 points while Opus 5 wins 7 of 12 benchmarks including Frontier-Bench by 9.6 — at half the output price</cite>. <cite index="18-5">Opus 5 and Sonnet 5 support zero data retention; Fable 5 requires 30-day retention.</cite>

Assignment:

| Brief | Model | Why |
|---|---|---|
| Planning / architecture / spec review | **Opus 5** | <cite index="21-1">Opus 5 shows much better design judgment than 4.8 on large agentic tasks</cite>; keeps your existing architect role, ZDR, half Fable's price |
| 1 (truth fixes) | Sonnet 5 | Mechanical, well-anchored edits |
| 2 (schemas + measurement) | Opus 5 | Decision-bearing; a wrong SKU call costs weeks |
| 3 (capture refactor) | Opus 5 | Cross-language refactor, iOS + backend contract |
| 4 (definitions table) | Sonnet 5 | Data plumbing with a clear resolution order |
| 5 (UDS sweep) | Opus 5 | Safety-critical protocol work |
| 6 (priors/KB) | Opus 5 | Schema redesign + retrieval semantics |
| 7 (output contract) | Sonnet 5 → Opus 5 for validation layer | UI is mechanical; pointer validation is subtle |
| 8–9 (corpus + scorers) | Opus 5 | Research-bearing; defines what H1/H2 measure |

Do not use Fable 5 for this project. It loses to Opus 5 on most published benchmarks at twice the output price, and <cite index="22-3">the case for escalating to it is overnight autonomous runs with no immediate human review or refactors where a failed run costs more than the token delta</cite> — you are reviewing every diff, so that case doesn't apply. Note also that <cite index="17-2">Sonnet 5's updated tokenizer maps the same input to roughly 1.0–1.35× more tokens</cite>: budget accordingly and do not compare token counts across model generations in `measure_context.py`.

---

## GLOBAL HARD PROHIBITIONS

Quote these to the executor at the start of every session.

1. **Read-only on the vehicle.** The only new diagnostic service permitted in this entire body of work is **UDS 0x19 (ReadDTCInformation)**, plus `10 03` (extended session) and `3E 80` (tester present) where a module requires a session to stay open. Forbidden everywhere, no exceptions: `0x14` ClearDiagnosticInformation, `0x2E` WriteDataByIdentifier, `0x2F` InputOutputControl, `0x31` RoutineControl, `0x11` ECUReset, `0x27` SecurityAccess, `0x28` CommunicationControl, `0x85` ControlDTCSetting, and OBD Mode `04`. Existing Mode 04 clear functionality stays confined to the engine ECU on its current code path; do not extend clearing to any other module or address.
2. **No fabricated data.** A missing measurement is `null` from adapter to prompt to UI. Never substitute a plausible default. Never render `null` as a number.
3. **No unsourced vehicle claims.** The model may not assert a recall, TSB, known issue, or platform failure pattern that did not arrive in the prompt from a retrieval result.
4. **The model never authors raw data.** Raw values are rendered by deterministic code. The model outputs interpretation and references raw values by pointer.
5. **No proprietary DID guessing.** No invented Mode 22 PIDs, addresses, or scaling formulas. Extended PIDs and module addresses come only from versioned, human-reviewed table files with `source` fields.
6. **No new scrapers.** Do not add scraped sources. Do not extend `forum_scraper.py`, `code_scraper.py`, `backfill_carcomplaints.py`, `backfill_reddit.py`.
7. **Stationary only.** Any multi-module capture is gated behind a stationary check and aborts if speed becomes non-zero.
8. **No secrets in code.** Everything through `os.environ`. The hardcoded Tailscale IP default must not be reintroduced.

---

# BRIEF 1 — Truth fixes

**Objective:** the backend stops generating vehicle facts from model weights and stops inventing telemetry. Must land before any corpus generation, because every hallucinated TSB the current prompt invites would be distilled into training data permanently.

**Model:** Sonnet 5 · **Branch:** `brief-1-truth-fixes` · **Files:** `main.py`, `knowledge.py`, `notes/decisions.md`, new `LICENSE`

### Steps

1. **Wire retrieval into `/interpret`.** In the handler at `main.py:1097`, before prompt assembly, call the existing unused entry points in `knowledge.py`:
   ```python
   if codes:
       retrieval_text = await get_vehicle_context(make, model, year, codes)
       retrieval_source = "nhtsa_complaints+local_known_issues"
   else:
       retrieval_text, retrieval_meta = await get_vehicle_general_context(make, model, year)
       retrieval_source = "nhtsa_complaints_general"
   ```
   Wrap both in `try/except` with a 6-second total timeout. On failure or timeout: `retrieval_text = ""`, log a warning, continue — retrieval failure degrades the answer, it does not fail the request.

2. **Insert as a delimited block.** The retrieval text enters the prompt inside:
   ```
   <retrieved_context source="{retrieval_source}" retrieved_at="{iso8601}">
   {retrieval_text or "NONE — no vehicle-specific data retrieved for this vehicle."}
   </retrieved_context>
   ```
   It must be structurally distinct from instructions and must never be interleaved with them.

3. **Delete the memory-recall invitations.** Remove these exact lines and any surrounding instruction that asks the model to supply vehicle facts from its own knowledge:
   - `main.py:1435`: `- Are there any TSBs (Technical Service Bulletins) or recalls related to this code on this vehicle?`
   - `main.py:1606–1610`: the `KNOWN ISSUES FOR THIS ENGINE:` block including the example line `Examples: "This engine is known for...", "Owners commonly report...", "TSB issued for..."`
   Then grep for residue: `grep -n "TSB\|recall\|known for\|commonly report\|common problem" main.py` and report every remaining hit with a one-line disposition (kept / removed / rewritten).

4. **Add the sourcing rule** to the prompt, verbatim:
   ```
   SOURCING RULE (absolute):
   Only state a recall, technical service bulletin, or known platform issue if it appears inside <retrieved_context>. If that block is empty, or contains nothing relevant to these codes, you must say: "No vehicle-specific pattern data is available for this vehicle." Then diagnose from the measured evidence alone. Never supply a recall number, bulletin number, or "known issue" from your own knowledge.
   ```

5. **Kill the fabricated defaults.** At `main.py:1237` and `:1239`:
   ```python
   # BEFORE
   "rpm": int(snapshot.rpm) if snapshot.rpm else 750,
   "coolant_temp": int(snapshot.coolant_temp_f) if snapshot.coolant_temp_f else 205,
   # AFTER
   "rpm": int(snapshot.rpm) if snapshot.rpm is not None else None,
   "coolant_temp": int(snapshot.coolant_temp_f) if snapshot.coolant_temp_f is not None else None,
   ```
   Note the `is not None` — the current truthiness test also discards a legitimate reading of `0`.

6. **Render nulls honestly.** Wherever these values enter the prompt, a `None` renders as the literal token `unavailable`, never a number, never an empty string. Add a helper:
   ```python
   def fmt(v, unit=""): return "unavailable" if v is None else f"{v}{unit}"
   ```

7. **Audit for remaining substitutions.** Search the `/interpret` payload assembly for the pattern `X if X else <literal>` applied to measured values. Report each as a table: line, expression, disposition. Apply the same `is not None` + `unavailable` treatment to every measured value.

8. **Mileage, backend.** Add to `InterpretRequest` (`main.py:73`):
   ```python
   mileage: Optional[int] = None
   mileage_source: Optional[str] = None  # "user" | "obd_pid_a6"
   ```
   Thread into the prompt as `Mileage: {fmt(mileage, " mi")} (source: {mileage_source or "unavailable"})`.

9. **Mileage, iOS.** Add a numeric mileage field to the scan flow (`Views/ScanView.swift`), sent on every interpret request. `OBDManager.readOdometer()` already exists — use its value as a **prefill suggestion clearly labeled as read from the vehicle**, editable by the user, and set `mileage_source` accordingly. Never silently substitute the PID value for user input; PID $A6 support is spotty and wrong mileage poisons every prior downstream.

10. **`LICENSE`.** Apache-2.0, full text, repo root. Add the `Copyright [yyyy] [name]` line.

11. **`notes/decisions.md`.** Append (do not delete history):
    ```
    ## [SUPERSEDED] Gemma 4 26B-A4B as target model
    Superseded by the Qwen MoE + SGLang direction. Original rejection rationale for
    Qwen3-30B-A3B (0.13 GB VRAM headroom at 2048 ctx on the A4500) is retained
    below as load-bearing evidence for the SKU decision in Brief 2 — do not delete.

    ## [OPEN] Canonical Qwen SKU
    Blocked on measured worst-case context (Brief 2). Do not pin by estimate.
    ```

### Prohibitions
Do not touch `parse_guidance` (`main.py:100`). Do not change the inference client or model string. Do not restructure the prompt beyond the specified insertions and deletions. Do not modify scraper files.

### Acceptance

```bash
# 1. No fabricated defaults remain
grep -n "else 750\|else 205" main.py          # expect: no output
# 2. Memory-recall invitations removed
grep -n "Are there any TSBs" main.py           # expect: no output
grep -n "TSB issued for" main.py               # expect: no output
# 3. Retrieval is actually called
grep -n "get_vehicle_context\|get_vehicle_general_context" main.py   # expect: >=2 hits in /interpret
# 4. License
test -f LICENSE && head -1 LICENSE
```
Plus, pasted into the PR body:
- Logged prompt from a `/interpret` call on a vehicle **with** NHTSA data: `<retrieved_context>` populated; every known-issue statement in the response traceable to an item inside that block.
- Logged prompt for a vehicle with **no** retrieval hits: block reads `NONE`, response contains the literal abstention sentence, zero named TSBs or recalls.
- Request with `client_rpm=null, client_coolant_temp=null`: prompt contains `unavailable`, contains neither `750` nor `205`.
- The fabricated-default audit table from step 7.

**Rollback:** single revert of the branch merge; no schema or data migration involved.
**Commit:** `fix(interpret): retrieve vehicle context instead of recalling it; drop fabricated telemetry defaults`

---

# BRIEF 2 — Schema freeze + measured context budget

**Objective:** freeze the contracts everything downstream depends on, and pin the Qwen SKU against a measured worst-case prompt. Runs on the A4500 over Tailscale; no 5090 required.

**Model:** Opus 5 · **Branch:** `brief-2-schemas` · **Files:** new `schemas/*.json`, new `scripts/measure_context.py`, `notes/decisions.md`

### Steps

1. Create `schemas/capability_profile.json`:
   ```json
   {
     "$schema":"https://json-schema.org/draft/2020-12/schema",
     "$id":"cleardrive/capability_profile/1.0.0",
     "type":"object",
     "required":["schema_version","protocol","era","adapter"],
     "properties":{
       "schema_version":{"const":"1.0.0"},
       "protocol":{"type":["string","null"],
         "enum":["ISO15765_11_500","ISO15765_29_500","ISO15765_11_250","ISO15765_29_250",
                 "ISO9141_2","KWP2000_5BAUD","KWP2000_FAST","J1850_PWM","J1850_VPW",null]},
       "era":{"type":"string","enum":["pre_can","can","obdonuds","unknown"]},
       "pid_support_bitmaps":{"type":"object",
         "additionalProperties":{"type":["string","null"],"pattern":"^[0-9A-F]{8}$"}},
       "modes_supported":{"type":"object",
         "properties":{"01":{"type":"boolean"},"02":{"type":"boolean"},"03":{"type":"boolean"},
                       "06":{"type":"boolean"},"07":{"type":"boolean"},"09":{"type":"boolean"},
                       "0A":{"type":"boolean"}}},
       "uds_available":{"type":["boolean","null"]},
       "modules_discovered":{"type":"array","items":{"type":"object",
         "required":["module_id","response"],
         "properties":{"module_id":{"type":"string"},
           "response":{"type":"string","enum":["responded","no_response","refused"]}}}},
       "adapter":{"type":"object",
         "required":["id","chipset_class"],
         "properties":{"id":{"type":["string","null"]},"firmware":{"type":["string","null"]},
           "chipset_class":{"type":"string","enum":["elm327_clone","stn_family","unknown"]},
           "networks":{"type":"array","items":{"type":"string",
             "enum":["hs_can","ms_can","sw_can","iso9141","kwp","j1850_pwm","j1850_vpw","can_fd"]}}}},
       "limitations":{"type":"array","items":{"type":"string"}}
     }
   }
   ```

2. Create `schemas/payload_v2.json`. Top-level required: `schema_version`, `session`, `vehicle`, `capability_profile`, `dtcs`. Every measurement field nullable. Blocks:
   - `session`: `{captured_at, adapter_id, adapter_firmware, app_version, capture_script_version}`
   - `vehicle`: `{vin, year, make, model, engine, displacement_l, cylinders, transmission, drive, mileage, mileage_source}`
   - `dtcs[]`: `{code, status: "stored"|"pending"|"permanent", module_id, definition, definition_source: "manufacturer"|"generic_j2012"|"structural", component_id}`
   - `freeze_frames[]`: `{code, frame_no, values: {pid: {value, unit}}}`
   - `live_snapshot`: `{pid: {value, unit, captured_at, rpm_context: "idle"|"2500"|"unknown"}}`
   - `mode06`: nullable array of `{test_id, component_id, value, min, max, unit, passed}`
   - `readiness`: `{monitor: {supported, complete}}`
   - `module_dtcs[]`: `{module_id, module_name, response: "responded"|"no_response"|"refused", dtcs: [{code_3byte, status_byte, definition, definition_source}]}` — **ships empty in Brief 3, populated in Brief 5. Include it now; this is the forward-compat hook that prevents a corpus rebuild.**
   - `retrieval` (backend-added, not client): `{recalls[], complaint_digest[], kb_matches[], mileage_in_window, window_low, window_high}`

3. Create `schemas/component_ids.json` — closed enum, exactly:
   `engine_block, ignition_coils, fuel_injectors, intake_maf, throttle_body, turbo, supercharger, intercooler, radiator, thermostat, water_pump, catalytic_converter, o2_upstream, o2_downstream, exhaust_manifold, exhaust_down, exhaust_mid, muffler, fuel_pump, fuel_tank, fuel_line, evap_canister, evap_purge_valve, transmission, torque_converter, driveshaft, front_diff, rear_diff, transfer_case, abs_module, abs_pump, wss_fl, wss_fr, wss_rl, wss_rr, srs_module, bcm, pcm, alternator, starter, battery_12v, battery_pack, motor_front, motor_rear, inverter, dc_dc, hvac_compressor, unknown`

4. Create `schemas/output_contract.json` — the model's only output:
   ```json
   {
     "type":"object",
     "required":["summary_plain_english","differential","severity","next_test","capability_note"],
     "additionalProperties":false,
     "properties":{
       "summary_plain_english":{"type":"string","minLength":40,"maxLength":900},
       "differential":{"type":"array","minItems":1,"maxItems":5,"items":{
         "type":"object",
         "required":["cause","component_id","likelihood","evidence"],
         "additionalProperties":false,
         "properties":{
           "cause":{"type":"string"},
           "component_id":{"$ref":"component_ids.json#/enum"},
           "likelihood":{"enum":["high","medium","low"]},
           "evidence":{"type":"array","minItems":1,"items":{
             "type":"object",
             "required":["pointer","restatement"],
             "properties":{
               "pointer":{"type":"string","pattern":"^/(dtcs|freeze_frames|live_snapshot|mode06|module_dtcs|retrieval|vehicle)/.*"},
               "restatement":{"type":"string","maxLength":120}}}},
           "vehicle_specific_note":{"type":["string","null"]},
           "prior_source":{"type":["string","null"],
             "enum":["platform_kb","nhtsa_complaints","nhtsa_recall","none",null]}}}},
       "severity":{"type":"object","required":["drive_safe","urgency","rationale"],
         "properties":{"drive_safe":{"type":"boolean"},
           "urgency":{"type":"integer","minimum":1,"maximum":4},
           "rationale":{"type":"string"}}},
       "recall_flag":{"type":["object","null"],
         "properties":{"open_recall_match":{"type":"boolean"},"campaign_id":{"type":["string","null"]}}},
       "next_test":{"type":"object","required":["what","why_discriminating","diy_difficulty"],
         "properties":{"what":{"type":"string"},
           "why_discriminating":{"type":"string","minLength":25},
           "discriminates_between":{"type":"array","minItems":2,"maxItems":2,"items":{"type":"integer"}},
           "diy_difficulty":{"type":"integer","minimum":1,"maximum":5}}},
       "cost_band":{"type":["object","null"],
         "properties":{"low_usd":{"type":"number"},"high_usd":{"type":"number"},"basis":{"type":"string"}}},
       "capability_note":{"type":"string"},
       "confidence_caveats":{"type":["string","null"]}
     }
   }
   ```
   `next_test.discriminates_between` holds two indices into `differential` — this makes "the test must separate the top two causes" a **validated constraint**, not a description.

5. Write `scripts/measure_context.py`. It must:
   - Build a worst-case payload: 6 stored + 3 pending + 2 permanent DTCs, one freeze frame per stored code with 12 PIDs each, 24-PID live snapshot, Mode 06 with 20 test rows, 6 modules × 4 module DTCs, full retrieval block (5 recalls, 8 complaint clusters, 3 KB matches).
   - Assemble the exact production prompt from it.
   - Report per-section token counts (instructions / vehicle / payload / retrieval / few-shot / output-schema) for each candidate SKU's tokenizer.
   - Emit a markdown table to `notes/2026-07-XX-context-budget.md`.
   - Take `--tokenizer` as an argument; **do not hardcode a model**.
6. Run on the A4500 for each candidate Qwen SKU. Record total worst-case prompt tokens, per-section breakdown, and KV headroom at that context within 20 GB with the intended quantization.
7. Write the `[DECIDED]` entry in `decisions.md` pinning SKU + required context length + the measured evidence. **If no candidate fits, record that as the finding and stop.** Do not silently reduce context to make a SKU fit — that is the exact failure mode that produced the earlier silent 4096-token truncation.

### Prohibitions
No capture code, no `/interpret` changes, no rendering. Do not estimate token counts — measure them. Do not compare token counts across model generations without noting tokenizer differences.

### Acceptance
```bash
python -c "import json,glob;[json.load(open(f)) for f in glob.glob('schemas/*.json')];print('schemas parse OK')"
python scripts/validate_example.py schemas/payload_v2.json examples/worst_case_payload.json  # exit 0
python scripts/measure_context.py --tokenizer <sku> --worst-case   # prints per-section table
```
Committed: five schema files, `examples/worst_case_payload.json`, `notes/2026-07-XX-context-budget.md`, a `[DECIDED]` SKU entry citing measured numbers, and intact Gemma/Qwen3-30B history.

**Commit:** `feat(schemas): freeze payload v2, capability profile, and output contract; pin SKU against measured context`

---

# BRIEF 3 — Capability probe + payload v2 capture

**Objective:** the app learns what each vehicle can tell it, then captures everything the generic protocol allows. Server-driven so protocol coverage improves without App Store releases.

**Model:** Opus 5 · **Branch:** `brief-3-capture` · **Files:** `ios/.../Services/OBDManager.swift`, new `capture_scripts/`, `main.py`

### Steps

1. **Script format.** `capture_scripts/` holds versioned JSON:
   ```json
   {"script_id":"can_full","version":"1.0.0","applies_to":{"era":["can"],"chipset_class":["elm327_clone","stn_family"]},
    "commands":[
      {"id":"dtc_stored","send":"03","timeout_ms":2000,"retries":2,"parse_as":"dtc_list","optional":false},
      {"id":"ff_p0301","send":"0202","timeout_ms":2500,"retries":1,"parse_as":"freeze_frame","optional":true}
    ]}
   ```
2. **Endpoint.** `GET /capture-script?protocol=&make=&era=&chipset_class=&codes=` returns the script plus `capture_script_version`. The live-snapshot commands are generated server-side from `capture_scripts/dtc_pid_map.json` keyed on the codes present.
3. **iOS refactor.** `OBDManager` gains `executeScript(_ script: CaptureScript) async -> [String: RawResponse]`, which runs the command list through the existing `sendCommand` and returns raw responses keyed by command `id`. **No per-make logic in Swift.** Keep the existing typed helpers only for connect/init and the capability probe.
4. **Capability probe script** (always runs first): protocol detect; adapter fingerprint via `ATI`, `AT@1`, and `STI` (STN chipsets answer `STI`, clones do not — that is your `chipset_class` discriminator); PID bitmaps `0100`, `0120`, `0140`, `0160`, `0180`; mode probes `0202`, `0600`, `07`, `0900`, `0A`. Populate `capability_profile`.
5. **Payload v2 capture order:** `03` → `07` → `0A` → `02` freeze frame per stored code → keyed `01` live snapshot → `06` if supported → readiness (`0101`) → `0902` VIN + `0904` CALID + `0906` CVN → `0142` module voltage.
6. **`capture_scripts/dtc_pid_map.json`.** Family → PID list, each entry sourced:
   - `P017x/P018x` → `0106,0107,0108,0109,0110,010B,010C,0111,0114,0115` at idle and 2500 rpm
   - `P030x` → `010C,0104,0106,0107,010B,0111` + Mode 06 misfire TIDs if supported
   - `P042x/P043x` → `0114,0115,0124,0125,013C` + `0106,0107`
   - `P012x/P013x` → `0110,0111,010B,0104`
   - `P0-cooling (P0128,P0125)` → `0105,010F,010C` + warmup elapsed
   - default → `010C,010D,0105,0104,0106,0107,010B,0111,010F,0142`
7. **Partial captures are valid.** Per-command timeout/retry from the script. A failed optional command records `null` and appends a human-readable string to `capability_profile.limitations` (e.g. `"Mode 06 not supported on this vehicle"`). Capture continues. A failed **non-optional** command aborts with a user-facing message that names what failed.
8. **Pre-CAN branch.** When protocol is ISO 9141-2 / KWP / J1850: server serves `pre_can_reduced` — timeouts ×3, ≤8 live PIDs, no Mode 06 parsing, no UDS, `era: "pre_can"`, and a limitation string stating that this vehicle's protocol supports fewer diagnostic modes.
9. **Backend acceptance.** `/interpret` accepts `payload_v2` alongside legacy fields. **The legacy path must keep working** — TestFlight users on the old build cannot break.

### Prohibitions
No per-make branching in Swift. No clearing. No writes. No UDS in this brief (that is Brief 5). Do not remove the legacy request path.

### Acceptance
- Real CAN-era vehicle: full payload validates against `payload_v2.json`; `capability_profile.modes_supported` matches manual probing.
- Vehicle/simulator without Mode 06: capture completes, `mode06: null`, limitation string present, no user-facing error.
- Forced timeout on one optional command: capture completes, that field `null`, others intact.
- Old iOS build's legacy request still returns a valid diagnosis (regression test).
- Report: captured payload size in bytes and tokens for two real vehicles, compared against the Brief 2 budget.

**Commit:** `feat(capture): server-driven capability probe and payload v2 capture`

---

# BRIEF 4 — Manufacturer code definitions

**Objective:** decode the manufacturer-specific codes that already arrive over standard Mode 03. Cheap tier of brand-specific coverage.

**Model:** Sonnet 5 · **Branch:** `brief-4-definitions` · **Files:** new `data/dtc_definitions/`, `main.py`

### Steps
1. Migrate the existing 418-entry SAE J2012 table out of code into `data/dtc_definitions/j2012_generic.json`.
2. `data/dtc_definitions/manufacturer/<make>.json`, entries: `{code, definition, systems_affected[], component_id, source, verified_by, verified_at}`. Seed the makes in the TestFlight fleet first — query the vehicles table for actual distribution before choosing.
3. **Resolution order:** manufacturer table (keyed on decoded make) → `j2012_generic` → structural fallback.
4. **Structural fallback** derives system and subsystem from the code's own characters (first letter = P/B/C/U system; second digit = generic vs manufacturer; third = subsystem) and returns:
   ```json
   {"definition":"Manufacturer-defined code. System: powertrain, subsystem: transmission. Precise meaning not in database.",
    "definition_source":"structural","component_id":"unknown"}
   ```
5. Attach `definition_source` to every DTC in payload v2 so both the model and the raw view always know provenance.
6. **Prompt rule:** when any code has `definition_source: "structural"`, the model must state that the code's precise meaning is manufacturer-defined and not in the database, and diagnose from structure plus measured evidence. It must not guess the definition.

### Prohibitions
Do not invent definitions. Do not scrape definition sources. An entry without `source` and `verified_by` may not ship.

### Acceptance
```bash
python scripts/check_definitions.py   # fails if any entry lacks source/verified_by; wire into CI
```
- P1xxx on a seeded make → `definition_source: "manufacturer"`.
- Same code on an unseeded make → structural fallback; response flags the gap and invents no meaning.

**Commit:** `feat(dtc): make-keyed manufacturer definitions with structural fallback`

---

# BRIEF 5 — UDS module sweep (read-only)

**Objective:** read fault codes from ABS, SRS, transmission, and body modules on CAN-era vehicles. This is the real brand-specific unlock and the highest-risk brief in the set.

**Model:** Opus 5 · **Branch:** `brief-5-uds-sweep` · **Files:** new `capture_scripts/uds/`, `ios/.../OBDManager.swift`, `main.py`

### Steps
1. `capture_scripts/uds/module_map.json`, per make and generation:
   ```json
   {"make":"BMW","generation":"F1x","source":"<documentation reference>","verified_by":"","verified_at":"",
    "modules":[{"module_id":"dsc","module_name":"ABS/DSC","request_header":"6F1","target":"29",
                "response_header":"612","session_required":true}]}
   ```
   **Start with one pilot make only — BMW, given the OBDLink CX on hand.** Do not add makes speculatively.
2. **Per-module sequence:** set headers (`AT SH`, `AT CRA`), `AT CAF1` for ISO-TP auto-formatting, open extended session only if `session_required` (`10 03`), send `19 02 FF` (reportDTCByStatusMask, all masks), parse multi-frame response into 3-byte DTCs + status byte, restore headers. `3E 80` only if the sequence exceeds the S3 timeout.
3. Populate `payload_v2.module_dtcs`. **A module that does not answer is `no_response` — never "no faults."** This distinction is the difference between honest and dangerous.
4. **Gating:** only when `capability_profile.era == "can"` and `uds_available`; only while stationary (speed PID reads 0, or explicit user confirmation); only behind a user-initiated "Full system scan" action. Never automatic on every scan.
5. **Abort conditions:** speed > 0 mid-sweep, connection loss, or total sweep exceeding the configured ceiling. On abort, keep partial results and mark the sweep incomplete in `capability_profile.limitations`.
6. Module DTC definitions follow Brief 4's resolution order and provenance rule. **Reporting an undefined ABS fault is valuable and honest; inventing its meaning is not.**
7. **Cross-module correlation** enters the prompt as an explicit instruction: multiple U-codes across modules should rank a single network or power/ground fault above three independent component failures.
8. **Secure gateway:** if modules do not answer on a 2018+ vehicle, record a gateway limitation string. **No bypass attempts of any kind.**

### Prohibitions (restate verbatim to the executor)
Service `0x19` only, plus `10 03` and `3E 80`. Forbidden: `0x14`, `0x2E`, `0x2F`, `0x31`, `0x11`, `0x27`, `0x28`, `0x85`, Mode `04`. No clearing on any non-engine module ever. No security access. No gateway bypass. No sweeps in motion. No speculative module addresses — every address comes from the sourced map file.

### Acceptance
- Pilot vehicle: ≥2 non-powertrain modules enumerated with DTC status read, present in `payload_v2.module_dtcs`.
- Non-responding module recorded `no_response`, distinct from zero DTCs.
- Sweep aborts cleanly and preserves partial data when speed becomes non-zero mid-scan (test by starting a sweep then driving, or by simulating the speed PID).
- **Traffic log committed to `notes/` proving only `19`, `10 03`, `3E 80` were transmitted.** Grep the log for forbidden service bytes as part of acceptance.
- Non-CAN vehicle: sweep not offered in the UI at all.

**Commit:** `feat(uds): read-only module DTC sweep via service 0x19 (BMW pilot)`

---

# BRIEF 6 — Priors layer

**Objective:** "cars like yours, at your mileage" reasoning sourced from data instead of weights.

**Model:** Opus 5 · **Branch:** `brief-6-priors` · **Files:** `knowledge.py`, new `data/platform_kb.json`, `data/component_dtc_map.json`, `main.py`

### Steps
1. Restructure `known_issues.json` → `data/platform_kb.json`, keyed `{make, model_or_platform, engine, year_range}`. **Engine is required** — the current make/model/year keying wrongly matches a V6 Accord against a 2.4L-specific entry.
2. Record fields: `failure_name, mileage_window{low,high}, symptoms[], associated_dtcs[], evidence_signature, severity, typical_fix, cost_band{low,high}, source, verified_by, verified_at`.
3. Seed via Opus-drafted, human-verified records for the TestFlight fleet and eval-set platforms. **Depth over breadth**; unverified records may not ship. Target ~5 records each for ~10 platforms rather than 1 each for 50.
4. NHTSA enrichment stage: recalls, complaints, and manufacturer-communication metadata per `(make, model, year)`; cache with 7-day TTL keyed on that tuple.
5. **Complaints preprocessing:** cluster by NHTSA component category; use the complaints `MILES` field to compute empirical mileage distributions per component. Inject a bounded digest — top components by frequency, count, median reported mileage, one representative summary each. **Never raw narratives.** Enforce the Brief 2 token cap and assert on it.
6. `data/component_dtc_map.json` maps NHTSA component categories ↔ DTC families so retrieval keys on the active code family, not just the vehicle.
7. **Server computes the mileage comparison.** Emit `mileage_in_window: bool`, `window_low`, `window_high` as explicit payload fields. The model narrates the precomputed result — it does not do arithmetic.
8. Open recalls surface as structured `recall_flag`, always ranked first.
9. **Abstention rule**, enforced in the prompt and measured in Brief 9: when the KB returns nothing for a platform, diagnose from measured evidence only and state that no platform pattern data exists.

### Prohibitions
No scraped sources. No unverified KB records. No model-side mileage arithmetic. No raw complaint narratives in the prompt.

### Acceptance
- KB-covered platform: response cites the failure with `prior_source` populated and the mileage window correctly applied.
- KB-absent platform: explicit abstention, zero platform claims.
- **Engine-keying regression test:** V6 and 4-cyl variants of the same model/year return different KB matches. This test is mandatory — it is the specific bug being fixed.
- Cached enrichment returns < 300 ms on second call.
- Complaint digest never exceeds the token cap (assertion, not a comment).

**Commit:** `feat(priors): engine-keyed platform KB, NHTSA enrichment, server-computed mileage windows`

---

# BRIEF 7 — Output contract enforcement + two-layer response

**Objective:** replace fragile section-header parsing with validated JSON; ship interpretation-by-default with raw data one tap away.

**Model:** Sonnet 5 for UI, Opus 5 for the validation layer · **Branch:** `brief-7-contract` · **Files:** `main.py`, `ios/.../Views/ResultsView.swift`

### Steps
1. Model emits JSON conforming to `output_contract.json`. Validate server-side. On failure: one constrained retry with the validation error appended; then a **deterministic degraded response built from raw data alone**. A parse error must never reach the user.
2. **Evidence pointer validation.** Every `differential[].evidence[].pointer` must resolve against the payload actually sent (JSON Pointer resolution). Unresolvable = validation failure. Log resolution rate as a metric — this becomes an eval number in Brief 9.
3. Validate `next_test.discriminates_between` references two distinct existing `differential` indices, and that at least one is index 0.
4. Retire `parse_guidance` string parsing once the JSON path is stable; keep it behind a feature flag for one release for rollback.
5. **iOS default view:** recall banner → drive-safe verdict → plain-English summary → ranked causes with evidence chips → next test → cost band. Plus one quiet status line: `Read 4 modules · 2 codes found`.
6. **Raw view behind a "View scan data" action,** rendered deterministically from payload v2: codes table (code, status, module, definition source), freeze frames, live values with units, readiness grid, module sweep results, and capability profile **including what was unavailable**.
7. Evidence chips are tappable and deep-link into the raw view scrolled to the referenced value.
8. Backend returns raw + interpretation in one envelope. **If inference is unavailable, return raw alone** and have the UI degrade to a competent traditional scan display.
9. "Mechanic Report" export bundling both layers.

### Prohibitions
The model may not restate raw numeric values outside `evidence[].restatement`. No parse-failure text reaches the user. Do not couple the raw path to inference availability.

### Acceptance
- 20-case smoke set: ≥19/20 schema-valid on first attempt; 100% after single retry.
- Evidence pointer resolution rate = 100% on the smoke set; a deliberately corrupted pointer triggers validation failure.
- With the inference server stopped, `/interpret` still returns raw data and the app renders the scan view.
- Tapping an evidence chip opens the raw view at the referenced row.

**Commit:** `feat(response): validated JSON output contract with evidence-pointer resolution`

---

# BRIEF 8 — Corpus specification (the mechanic reasoning pattern)

**Objective:** the reasoning behavior is *learned*, not prompted. This brief defines what the fine-tune is actually taught. No GPU required.

**Model:** Opus 5 · **Branch:** `brief-8-corpus-spec` · **Files:** new `ml/corpus_spec.md`, `ml/scripts/generate_corpus.py`, `ml/scripts/check_format_compat.py`

### Steps
1. **Target reasoning chain**, demonstrated by every example: codes + definition provenance → measured evidence (freeze frame, trims, Mode 06, module faults) → platform prior with mileage conditioning **or explicit abstention** → ranked differential with each cause pinned to evidence → cheapest discriminating next test → severity and cost.
2. **Mandatory example classes**, with target proportions:
   - Rich CAN-era payload + KB hit (~30%)
   - Rich payload + **KB miss → abstention** (~15%) — without these the model confabulates platform priors
   - Thin pre-CAN payload, DTC + freeze frame only (~15%)
   - Codeless / symptom-only (H4) (~10%)
   - Multi-code, contradictory evidence where the correct answer ranks and explains the conflict (~10%)
   - Module-fault correlation, multiple U-codes → single network fault (~8%)
   - Structural-fallback definition, unknown manufacturer code (~7%)
   - Capability-limited, where the correct output names what a better capture would resolve (~5%)
3. **Every target output is valid `output_contract.json`** and passes evidence-pointer resolution against its own input payload. Generation rejects any example that fails validation.
4. Input format is byte-identical to the production prompt assembler. `check_format_compat.py` asserts this by round-tripping a corpus example through the live assembler and diffing — **run it in CI**; format drift between training and inference is a silent killer.
5. Held-out split is **by platform, not by example** — otherwise the model memorizes platforms and H2 measures nothing.
6. Corpus size ~3–5k curated Opus-distilled examples, not the raw 15k.
7. Every example carries metadata: `example_class`, `era`, `kb_present`, `payload_richness`, `platform` — these become the eval strata in Brief 9.

### Acceptance
- `ml/corpus_spec.md` committed with the class table and proportions.
- Generator produces a 100-example pilot; 100% pass output-contract validation and pointer resolution.
- `check_format_compat.py` exits 0 against the live assembler; wired into CI.
- Class distribution report matches spec within ±3%.

**Commit:** `feat(corpus): specification and generator for mechanic-pattern reasoning examples`

---

# BRIEF 9 — Scorers + eval harness

**Objective:** measure whether the model learned the reasoning pattern or just the JSON shape. Defines the numbers H1 and H2 report. No GPU required.

**Model:** Opus 5 · **Branch:** `brief-9-scorers` · **Files:** `scripts/score_*.py`, `notes/eval_protocol.md`

### Steps
1. **Platform-claim precision** — of all "known issue" claims made, the fraction supported by a retrieval item actually present in that example's input. This is the headline H2 metric and the direct measure of the memory→reasoning shift.
2. **Abstention correctness** — on KB-miss examples, did the model abstain rather than confabulate? Report as a rate.
3. **Mileage-conditioning correctness** — when `mileage_in_window` is true/false, did the narration match?
4. **Evidence-linkage validity** — pointer resolution rate; also whether the cited value actually supports the claim (LLM-judge on a sample, Opus 5 as judge per the existing contamination guardrail).
5. **Next-test discrimination** — does the proposed test separate the top two causes? LLM-judge with a rubric.
6. **Schema validity** and **degeneracy** — carry forward the existing scorer, updated to the JSON contract.
7. **Era-stratified reporting** — every metric reported per era (pre_can / can) and per `kb_present`. "Accurate across the majority of vehicles" becomes a measured per-stratum claim rather than an assertion.
8. **Four-arm ablation harness** for H1: base, base+RAG, FT, FT+RAG — identical payloads across arms, only the reasoning/retrieval stack differs. This preempts the judge question "is it the fine-tune or the retrieval?"
9. `notes/eval_protocol.md` documents each metric, its computation, and its hypothesis mapping.

### Acceptance
- All scorers run against the Brief 8 pilot corpus and emit a stratified table.
- Ablation harness runs end-to-end with a stub model in each arm.
- Deliberately planted violations (fabricated TSB, unresolvable pointer, non-discriminating test) are each caught by the corresponding scorer.

**Commit:** `feat(eval): platform-claim precision, abstention, and evidence-linkage scorers with 4-arm ablation`

---

## GATES

1. Briefs 1 and 2 must both pass before corpus generation begins.
2. Corpus generation (Brief 8) depends on Briefs 2, 4, 6, 7 — the input and target formats must be frozen first.
3. QLoRA fine-tune is blocked on the 5090 returning **and** Unsloth sm_120 verification for the pinned SKU. Nothing in Briefs 1–9 requires it.
4. Ablation (Brief 9, step 8) runs after the fine-tune.
5. The 3D X-ray feature is product track, behind a feature flag, and must not enter any H3 study condition — adding a visual aid to one arm would confound the comprehension comparison.

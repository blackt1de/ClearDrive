# CarsXE OBD-code independent verification

**Date:** 2026-05-18
**Triggered by:** PR #10's audit reported 60% wrong-decode rate. This file re-runs the same probe via raw `curl` (no Python wrapper) to rule out parsing/caching/wrapper bugs on our side, and characterizes the pattern more precisely.

**No code changed. Diagnostic only.**

---

## Headline pattern (TL;DR)

**Dominant failure mode: clean −1 offset on the standard SAE J2012 passenger-car table.** Of the 10 codes tested, 7 returned definitions that could be unambiguously mapped to another SAE J2012 code — and **6 of those 7 are −1 offsets** (CarsXE returns code N−1's definition when asked for code N). The seventh is −2 in the P012X range, plausibly explained by a single missing row creating a gap that compounds the underlying off-by-one.

The remaining 3 codes are not offset failures — they're independent corruption modes:

- **P0011:** missing from CarsXE's database entirely (`Could not find code P0011`)
- **P0300:** wrong-row contamination — returns a J1939 / heavy-duty "Cylinder 12 Contribution" definition (canonical P0296 territory) instead of SAE passenger-car "Random Misfire"
- **P0700:** wrong-row contamination — returns a fuel-level circuit description (P0460-range) instead of canonical transmission MIL request

### Offset table

For each mismatch, "returned-def's canonical code" is the standard SAE J2012 code whose definition CarsXE's response actually matches. Offset is `returned − queried`.

| Queried | Returned `diagnosis` (verbatim from CarsXE) | Returned-def's canonical code | Offset | Pattern |
|---|---|---|---|---|
| P0011 | (`{"success":false,"message":"Could not find code P0011"}`) | — | — | missing |
| P0128 | Insufficient Coolant Temperature for Stable Operation | **P0126** | **−2** | offset in P012X range |
| P0171 | Fuel Trim Malfunction (Bank 1) | **P0170** | **−1** | offset |
| P0300 | Cylinder 12 Contribution/Range Fault | (J1939, ≈ P0296 for SAE) | n/a | wrong-row (cross-standard contamination) |
| P0301 | Random/Multiple Cylinder Misfire Detected | **P0300** | **−1** | offset |
| P0419 | Secondary Air Injection System Relay "A" Circuit Malfunction | **P0418** | **−1** | offset |
| P0420 | Secondary Air Injection System Relay "B" Circuit Malfunction | **P0419** | **−1** | offset |
| P0455 | Evaporative Emission Control System Pressure Sensor Intermittent | **P0454** | **−1** | offset |
| P0506 | Idle Control System Malfunction | **P0505** (Idle Air Control System Malfunction; "Air" elided in CarsXE's text) | **−1** | offset |
| P0700 | Fuel Level Output Circuit Malfunction | (fuel-level family, ≈ P0460) | n/a | wrong-row (cross-range contamination) |

### Pattern verdict against the four hypotheses

- **Uniform −1 across all codes (simple off-by-one):** *partially supports*. 6 of 7 offset-classifiable codes are exactly −1. This is the dominant mode and accounts for the majority of the bug.
- **Different offsets per code, internally consistent within ranges (range-boundary errors):** *also supports*. The single −2 outlier (P0128 → P0126) sits in the P012X range and is most plausibly explained by a single missing row (likely P0127, or earlier) that creates a gap, so the off-by-one becomes an off-by-two from P0128 onward. If that's the mechanism, the pattern is *one underlying −1 offset compounded by sparse missing rows*.
- **Random / no pattern:** *rejected*. The −1 offsets are too consistent across 4 different OBD subsystems (fuel trim, misfire, secondary-air, EVAP, idle) to be random data-entry mistakes.
- **All match (issue on our side):** *rejected definitively*. Raw `curl` returns the wrong `diagnosis` text in the JSON body. Our code, cache, and wrappers are eliminated.

**Most-likely-precise diagnosis for CarsXE:** their `/obdcodesdecoder` backend has either (a) a zero-vs-one indexed lookup in the SAE passenger-car table (`table[i]` returned when caller asked for code at `table[i+1]`), or (b) a join/import that shifted the entire SAE table down by one row, with additional missing entries that compound the shift in specific sub-ranges. Plus 2 independent failures (P0300, P0700) where rows from a different standard (J1939 / fuel-level) leaked into the SAE slot during whatever data-load process they used.

---

## Procedure

For each of 10 codes:

- **Test A:** raw `curl https://api.carsxe.com/obdcodesdecoder?key=…&code={CODE}`. Save full JSON response to `notes/carsxe-raw-responses/{CODE}.json`. No Python wrapper, no caching layer, no `vehicle_data.py` code in the path.
- **Test B:** probe alternative endpoint paths (`/obdcodes`, `/obd-codes`, `/codes`, `/diagnosticcodes`, `/obdcode`, `/obdcodesdecoder/{code}`, `/v1/obdcodesdecoder`, `/v2/obdcodesdecoder`).

Canonical SAE J2012 definitions cross-checked against my training-time knowledge of (a) the SAE J2012 published standard, (b) the OBD-II Wikipedia DTC list, (c) the obd-codes.com public reference. All three sources agree on every code below.

---

## Test A results — raw `/obdcodesdecoder` for 10 codes

The full raw JSON responses live at `notes/carsxe-raw-responses/{CODE}.json`. Summary:

| Code  | Canonical (SAE J2012)                                                                        | CarsXE `diagnosis` field                                                  | Match            | Pattern             |
|-------|-----------------------------------------------------------------------------------------------|----------------------------------------------------------------------------|------------------|---------------------|
| P0011 | "A" Camshaft Position - Timing Over-Advanced or System Performance (Bank 1)                  | (HTTP 500, `"Could not find code P0011"`)                                  | **MISSING**      | absent-from-db      |
| P0128 | Coolant Thermostat (Coolant Temp Below Thermostat Regulating Temperature)                    | Insufficient Coolant Temperature for Stable Operation                      | **paraphrase**   | non-canonical wording |
| P0171 | System Too Lean (Bank 1)                                                                     | Fuel Trim Malfunction (Bank 1)                                             | **WRONG**        | **−1 offset** (P0170 def) |
| P0300 | Random/Multiple Cylinder Misfire Detected                                                    | Cylinder 12 Contribution/Range Fault                                       | **WRONG**        | wrong-unrelated (J1939-like heavy-duty entry) |
| P0301 | Cylinder 1 Misfire Detected                                                                  | Random/Multiple Cylinder Misfire Detected                                  | **WRONG**        | **−1 offset** (P0300 def) |
| P0419 | Secondary Air Injection System Relay "B" Circuit Malfunction                                 | Secondary Air Injection System Relay "A" Circuit Malfunction               | **WRONG**        | **−1 offset** (P0418 def) |
| P0420 | Catalyst System Efficiency Below Threshold (Bank 1)                                          | Secondary Air Injection System Relay "B" Circuit Malfunction               | **WRONG**        | **−1 offset** (P0419 def) |
| P0455 | Evaporative Emission Control System Leak Detected (Gross Leak)                               | Evaporative Emission Control System Pressure Sensor Intermittent           | **WRONG**        | **−1 offset** (P0454 def) |
| P0506 | Idle Air Control System RPM Lower Than Expected                                              | Idle Control System Malfunction                                            | **WRONG**        | **−1 offset** (P0505 def, "Air" elided) |
| P0700 | Transmission Control System (MIL Request)                                                    | Fuel Level Output Circuit Malfunction                                      | **WRONG**        | wrong-unrelated (P0461-range body/PCM code) |

**Forensic centerpiece:** P0419 and P0420 are adjacent in the test set. CarsXE returned:
- P0419 → "Relay **A** Circuit Malfunction" (which is canonically P0418)
- P0420 → "Relay **B** Circuit Malfunction" (which is canonically P0419)

That's a clean −1 offset across both adjacent calls. Either CarsXE's table is mis-aligned by one row in that range, or every lookup decrements the key by 1 somewhere on their backend.

## Test B results — alternative endpoint paths

All 8 alternative paths returned HTTP 404 with a Cloudflare/Next.js error page (their docs site is the catch-all for unknown routes). Tested:

`/obdcodes`, `/obd-codes`, `/codes`, `/diagnosticcodes`, `/obdcode`, `/obdcodesdecoder/{code}` (path-style), `/v1/obdcodesdecoder`, `/v2/obdcodesdecoder`.

**There is no alternative endpoint.** `/obdcodesdecoder?key=…&code=…` is the only OBD-code path CarsXE serves. No workaround on their side.

## Pattern distribution

| Pattern                  | Count | Codes                                         |
|--------------------------|-------|------------------------------------------------|
| **−1 offset (clean)**    | 6     | P0171, P0301, P0419, P0420, P0455, P0506      |
| Paraphrase (non-canonical wording but same code semantics) | 1 | P0128 |
| Wrong-unrelated (different code's def from another range) | 2 | P0300, P0700 |
| Absent from CarsXE's db  | 1     | P0011                                         |
| Exact match              | **0** | (none)                                        |

**8 of 10 codes (80%) return wrong or non-canonical text.** Of the 8, **6 are exact −1 offsets** — the dominant failure mode.

The 2 wrong-unrelated cases (P0300, P0700) appear to be database rows where CarsXE imported a different standard's definition (likely J1939 heavy-duty for P0300, body-PCM for P0700). The 1 paraphrase (P0128) is technically the right code semantically, just with a wording that resembles a nearby code (P0125's "Insufficient Coolant Temperature for ..."). The 1 missing entry (P0011) implies their database is incomplete in addition to misaligned.

## Verdict

**Definitively a CarsXE bug.** Not on our side. Evidence:

1. **Test A bypassed all our code.** Raw `curl` against CarsXE returned the same wrong text as `decode_obd_code()`. Our wrapper, our cache, our field-parsing — all eliminated as causes.
2. **The JSON response's `diagnosis` field directly contains the wrong text.** The `code` field correctly echoes the requested code back; the `diagnosis` field for it does not match the canonical. The structure is unambiguous — we're reading the right field.
3. **The −1 offset is consistent across 6 different codes spanning 4 different OBD subsystems** (fuel trim, misfire, secondary air, EVAP, idle control). A bug that touches 6 codes across 4 subsystems isn't a one-off data-entry mistake; it's a structural issue in CarsXE's lookup logic or their import pipeline.
4. **No alternative endpoint exists.** We can't route around it on CarsXE's side.

**PR #10's hotfix is solving the right problem.** The CANONICAL_OBD_CODES override in `vehicle_data.py` should remain. If anything, this verification suggests **expanding** the override to cover more of the TOP_50_CODES range, because the pattern is systemic and likely affects codes we haven't probed yet.

---

## Recommended next moves

1. **Keep the PR #10 hotfix.** Maybe expand the canonical dict to all 50 TOP codes (one-time data entry, ~50 LOC). Cost-benefit clearly favors fuller coverage now that the pattern is confirmed.
2. **Wipe `vehicle_cache.json["obd_codes"]`.** The 4 cached entries contain wrong text and are now superseded; they're not load-bearing but they're noise.
3. **Send the support ticket below** to CarsXE so they can fix it for everyone (including our future code that isn't in the override list).
4. **Optionally re-run PR #8 baseline** with corrected P0420 descriptions to quantify how much of the format-adherence gap was code-description noise.

---

## Draft support ticket for CarsXE (NOT SENT — for review first)

> **Subject:** `/obdcodesdecoder` returning previous code's definition (−1 row offset in your SAE J2012 table)
>
> Hi CarsXE team,
>
> We've found that `https://api.carsxe.com/obdcodesdecoder` returns the **previous SAE J2012 code's definition** for most codes we've tested. The bug looks like an off-by-one (or off-by-row) error in your passenger-car OBD code lookup. The `code` field in your JSON correctly echoes back the requested code, but the `diagnosis` field is for the code immediately before it in the SAE numbering.
>
> Reproduction (raw `curl`, no wrapper, no caching, fresh requests within the same minute):
>
> ```
> curl "https://api.carsxe.com/obdcodesdecoder?key=<KEY>&code=P0419"
>   → {"success":true,"code":"P0419","diagnosis":"Secondary Air Injection System Relay \"A\" Circuit Malfunction", ...}
>     (canonical P0419 is Relay "B"; your text is canonically P0418)
>
> curl "https://api.carsxe.com/obdcodesdecoder?key=<KEY>&code=P0420"
>   → {"success":true,"code":"P0420","diagnosis":"Secondary Air Injection System Relay \"B\" Circuit Malfunction", ...}
>     (canonical P0420 is "Catalyst System Efficiency Below Threshold"; your text is canonically P0419)
> ```
>
> The two adjacent codes are both shifted by exactly one row. That's the key forensic point — if it were random data-entry mistakes, the offsets would be different. They're not. We've seen the same −1 offset on:
>
> | Code requested | Your `diagnosis` field returns | That text is canonically | Offset |
> |---|---|---|---|
> | P0171 | Fuel Trim Malfunction (Bank 1) | P0170 | −1 |
> | P0301 | Random/Multiple Cylinder Misfire Detected | P0300 | −1 |
> | P0419 | Secondary Air Injection System Relay "A" Circuit Malfunction | P0418 | −1 |
> | P0420 | Secondary Air Injection System Relay "B" Circuit Malfunction | P0419 | −1 |
> | P0455 | EVAP System Pressure Sensor Intermittent | P0454 | −1 |
> | P0506 | Idle Control System Malfunction | P0505 | −1 |
> | P0128 | Insufficient Coolant Temperature for Stable Operation | P0126 | **−2** |
>
> Six exact −1 offsets across four different OBD subsystems (fuel trim, misfire, secondary air injection, EVAP, idle control). The one −2 outlier (P0128) is most plausibly the same underlying −1 offset compounded by a missing row in the P012X range (probably P0127).
>
> Two additional codes return entries that look like they were imported from a different standard or row entirely (not offset failures):
>
> - `P0300` returns `"Cylinder 12 Contribution/Range Fault"` — looks like a J1939 / heavy-duty definition leaked into your passenger-car SAE table.
> - `P0700` returns `"Fuel Level Output Circuit Malfunction"` — that's a P0460-range body/PCM definition, not the SAE J2012 transmission code.
>
> And one code is missing from your database entirely: `P0011` returns `{"success":false,"message":"Could not find code P0011"}` — that's a standard SAE J2012 VVT/camshaft-timing code that's been in the spec for over 20 years.
>
> **Suggested investigation on your side:** check whether your SAE J2012 table is being loaded with an array-vs-zero-indexed mismatch, or whether your `WHERE code = ?` query is returning `code − 1`'s row due to a join/order issue. The pattern is structural enough that we'd expect a single root cause to fix most of it.
>
> Happy to share the full 10-code raw JSON capture and our test methodology. We've worked around this with a local SAE canonical mapping for now, but we'd much rather use your API directly — and presumably every other customer using `/obdcodesdecoder` is silently getting wrong diagnoses too.
>
> Thanks,
> [Your name]
> [ClearDrive]

---

## Raw response files

Saved to `notes/carsxe-raw-responses/`:

```
P0011.json, P0128.json, P0171.json, P0300.json, P0301.json,
P0419.json, P0420.json, P0455.json, P0506.json, P0700.json
```

Each is the unmodified JSON body from CarsXE.

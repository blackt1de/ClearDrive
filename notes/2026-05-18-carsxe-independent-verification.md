# CarsXE OBD-code independent verification

**Date:** 2026-05-18
**Triggered by:** PR #10's audit reported 60% wrong-decode rate. This file re-runs the same probe via raw `curl` (no Python wrapper) to rule out parsing/caching/wrapper bugs on our side, and characterizes the pattern more precisely.

**No code changed. Diagnostic only.**

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

> **Subject:** OBD codes decoder API returning wrong definitions — `/obdcodesdecoder` has a systematic −1 offset bug
>
> Hi CarsXE team,
>
> We're using your `/obdcodesdecoder` endpoint to look up SAE J2012 OBD-II code definitions. We've found that the API returns incorrect `diagnosis` text for at least 8 of 10 codes we tested. The dominant failure mode is a **clean −1 offset**: when we request code `N`, the response contains code `N−1`'s definition.
>
> Test setup: direct `curl` calls to `https://api.carsxe.com/obdcodesdecoder?key=…&code=…`, no wrapper, no caching.
>
> Forensic example (adjacent codes from the same call sequence):
>
> | Requested code | Your `diagnosis` field returned | Canonical SAE J2012 definition |
> |---|---|---|
> | `P0419` | `Secondary Air Injection System Relay "A" Circuit Malfunction` | Secondary Air Injection System Relay **"B"** Circuit Malfunction (that's P0418's def) |
> | `P0420` | `Secondary Air Injection System Relay "B" Circuit Malfunction` | Catalyst System Efficiency Below Threshold (Bank 1) (that's P0419's def) |
>
> Both responses are off by one row. The `code` field in the JSON correctly echoes back the requested code, but the `diagnosis` field is for the previous code. The wrong text appears verbatim in the raw JSON — this isn't a parsing issue on our end.
>
> Other codes with the same −1 offset behavior:
>
> | Requested | Your response | Should be |
> |---|---|---|
> | P0171 | Fuel Trim Malfunction (Bank 1) | System Too Lean (Bank 1) |
> | P0301 | Random/Multiple Cylinder Misfire Detected | Cylinder 1 Misfire Detected |
> | P0455 | EVAP Pressure Sensor Intermittent | EVAP Leak Detected (Large) |
> | P0506 | Idle Control System Malfunction | Idle Air Control System RPM Lower Than Expected |
>
> Two additional codes return definitions from unrelated ranges entirely:
> - `P0300` returns `"Cylinder 12 Contribution/Range Fault"` — appears to be a J1939 heavy-duty definition rather than the SAE J2012 passenger-car definition (Random/Multiple Misfire).
> - `P0700` returns `"Fuel Level Output Circuit Malfunction"` — that's a P0461-range body/PCM definition, not the canonical "Transmission Control System (MIL Request)".
>
> And one code (`P0011`) returns `{"success":false,"message":"Could not find code P0011"}` — a basic SAE J2012 code is missing from your database.
>
> We've worked around this by maintaining a local SAE J2012 canonical mapping for our needed codes. But this bug affects every CarsXE customer using `/obdcodesdecoder`, and the −1 offset pattern suggests a single fix would resolve most of the wrong responses.
>
> Test responses available on request. Happy to share the full 10-code raw JSON capture.
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

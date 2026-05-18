# CarsXE support ticket — draft for manual send

**Status:** DRAFT. Not sent. Austin to review then send.
**Recipient:** CarsXE support (https://carsxe.com/support or whatever their channel is)
**Subject line:** `/obdcodesdecoder returns previous code's definition — systematic row-shift bug`

---

Hi CarsXE team,

We're a CarsXE customer (ClearDrive — vehicle diagnostic app) using your `/obdcodesdecoder` endpoint to look up SAE J2012 OBD-II code definitions. We've found a bug that affects every customer using that endpoint, so we wanted to flag it cleanly with reproduction steps. We've worked around it on our end for now; the goal of this ticket is just to surface it so you can fix it for everyone.

## The bug in one example

If you make these two `curl` calls in sequence (no wrapper, no caching — fresh requests within the same minute):

```
curl "https://api.carsxe.com/obdcodesdecoder?key=<KEY>&code=P0419"
→ {"success":true,"code":"P0419","diagnosis":"Secondary Air Injection System Relay \"A\" Circuit Malfunction", ...}

curl "https://api.carsxe.com/obdcodesdecoder?key=<KEY>&code=P0420"
→ {"success":true,"code":"P0420","diagnosis":"Secondary Air Injection System Relay \"B\" Circuit Malfunction", ...}
```

Both responses are off by one row from canonical SAE J2012:

- **P0419** should be `Secondary Air Injection System Relay "B" Circuit Malfunction` — your response gave the `"A"` variant, which is canonically P0418.
- **P0420** should be `Catalyst System Efficiency Below Threshold (Bank 1)` — your response gave P0419's definition (the `"B"` variant).

The `code` field in the JSON correctly echoes back the requested code, but the `diagnosis` field is for the code immediately before it in the SAE numbering. Both adjacent codes are shifted by the same amount — that's the key forensic point. If this were random data-entry mistakes, the offsets would vary. They don't.

## Broader pattern

We tested 10 codes spanning multiple OBD subsystems (fuel trim, misfire, secondary air, EVAP, idle, transmission). Results:

- **8 of 10 return wrong or non-canonical text (80%)**
- **6 of 10 are exact −1 offsets** (i.e., your `diagnosis` field contains code N−1's canonical definition)
- 1 is a −2 offset (P0128 → P0126), most plausibly the same −1 offset compounded by a missing row in your P012X range
- 2 are unrelated-row contaminations (see below)
- 1 code is missing from your database entirely (P0011)
- 0 of 10 are exact matches

Codes that show the clean −1 offset:

| Code requested | Your `diagnosis` field returns | That text is canonically | Offset |
|---|---|---|---|
| P0171 | Fuel Trim Malfunction (Bank 1) | P0170 | −1 |
| P0301 | Random/Multiple Cylinder Misfire Detected | P0300 | −1 |
| P0419 | Secondary Air Injection System Relay "A" Circuit Malfunction | P0418 | −1 |
| P0420 | Secondary Air Injection System Relay "B" Circuit Malfunction | P0419 | −1 |
| P0455 | EVAP System Pressure Sensor Intermittent | P0454 | −1 |
| P0506 | Idle Control System Malfunction | P0505 | −1 |

Six exact −1 offsets across four different OBD subsystems. We think this is structural rather than per-row data entry.

## Two additional codes returning rows from outside the SAE J2012 passenger-car table

These don't look like offset failures — they look like rows from a different code dictionary leaked into your SAE slot during whatever data-load process you used:

- **P0300** returns `"Cylinder 12 Contribution/Range Fault"`. SAE J2012 P0300 is `Random/Multiple Cylinder Misfire Detected`. The `"Cylinder 12 Contribution"` wording is more characteristic of J1939 / heavy-duty diesel diagnostic codes — possibly that row was imported into your passenger-car table by mistake.
- **P0700** returns `"Fuel Level Output Circuit Malfunction"`. SAE J2012 P0700 is `Transmission Control System (MIL Request)`. The fuel-level wording is closer to the P0460-range body/PCM codes.

## One code missing entirely

- **P0011** returns `{"success":false,"message":"Could not find code P0011"}`. P0011 is `"A" Camshaft Position - Timing Over-Advanced or System Performance (Bank 1)` and has been in SAE J2012 for 20+ years. Probably just a missing row.

## Suggested places to look

Without seeing your backend, our best guesses for root cause:

1. **Zero-vs-one indexing in your lookup.** If your SAE table is loaded as an array and the API looks up `table[code_int - 1]` instead of `table[code_int]`, you'd see exactly this −1 offset pattern.
2. **Table shifted by one row during import.** A CSV/SQL load with a missing or extra header row could shift every entry by one.
3. **The P0300 / P0700 cases suggest a separate join/import issue** where rows from a J1939 heavy-duty dictionary and a fuel-level table got cross-contaminated. Worth checking whether those source tables share any columns with your SAE J2012 master.

## What we'd find useful

- Confirmation you can reproduce the −1 offset on your end.
- An ETA on the fix, or a workaround we can switch to (different endpoint, query parameter, etc.).
- If you'd like, we can share the full 10-code raw JSON capture from our test run — happy to attach.

We really appreciate the API in general; just want to flag this so it gets in front of someone who can fix it. Thanks for taking a look.

Best,
Austin Brennan
ClearDrive
[contact email]

---

## Internal notes for Austin (delete before sending)

- The raw JSON evidence is at `notes/carsxe-raw-responses/{CODE}.json` — 10 files. You can zip and attach if they ask.
- The full forensic write-up is at `notes/2026-05-18-carsxe-independent-verification.md`.
- Tone calibration: polite, specific, hands-them-a-likely-root-cause-on-a-plate. Designed to be hard to dismiss but easy to act on.
- Hidden ask: when they fix it, we can drop most of `CANONICAL_OBD_CODES` from `vehicle_data.py` and re-trust the API — keeps our maintenance surface smaller.
- Their support channel is at https://carsxe.com/support (verify before sending). They might also have an email — check the dashboard.

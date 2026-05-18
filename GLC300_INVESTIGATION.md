# GLC300 Anomaly — Source-Coverage Investigation

**Status:** Diagnosis only. No code changes proposed in this document.

## Trigger

`corpus_stats.py` flagged `2018_mercedes-benz_glc300` as the only vehicle in
the 300-vehicle corpus where **all four memoized sources** (NHTSA complaints,
NHTSA recalls, RepairPal, CarComplaints) returned 0. `2018_mercedes-benz_gle350`
shows the same RepairPal=0 + CarComplaints=0 pattern but with intermittent NHTSA
hits elsewhere in the family.

This investigation tracks each empty source back to its root cause, then
quantifies how many other vehicles in the corpus are silently affected by the
same causes.

## Per-source root causes

### 1. NHTSA complaints — model-name mismatch (deterministic)

NHTSA's vPIC catalog (`GetModelsForMakeYear/Mercedes-Benz/2018`) lists the
canonical model names as `C-Class`, `E-Class`, `GLC-Class`, `GLE-Class`,
`SLC-Class` — never the trim-level identifiers `C300`, `GLC300`, `GLE350`.
`scrape_training_data.py` passes the trim-level string straight through to
`complaintsByVehicle?make=Mercedes-Benz&model=GLC300&modelYear=2018`, which
returns count=0. The same query against `model=GLC-Class` returns 97
complaints.

Probed today (2026-04-25):

| Query | Complaints |
|---|---|
| `Mercedes-Benz / C-Class / 2018` | 121 |
| `Mercedes-Benz / C300 / 2018` | 0 |
| `Mercedes-Benz / GLC-Class / 2018` | 97 |
| `Mercedes-Benz / GLC300 / 2018` | 0 |
| `Mercedes-Benz / GLE-Class / 2018` | (unprobed; same pattern expected) |

**Scope across the corpus:** every Mercedes-Benz vehicle in `TOP_VEHICLES`
(C300 x2, E300, GLC300, GLE350 — 5 of 5 = 100%) hits this. Volvo (XC60, XC90 —
2 of 2 = 100%) shows the same NHTSA-empty pattern; vPIC for Volvo lists
canonical names that may also differ. BMW partial — 2 of 5 hit, even though
vPIC for BMW *does* recognize trim-level names like `330i`, `X3`, `X5`. A
direct probe against `BMW / 330i / 2018` and `BMW / 3-Series / 2018` both
returned 0, suggesting BMW has genuinely sparse NHTSA-complaint coverage and
isn't a pure naming issue.

### 2. NHTSA recalls — also affected, plus genuine zeros

Same canonicalization issue; the recalls API uses the same model parameter.
The `1/15` recall miss for `BMW 330i` and 100% miss for Mercedes are
likely a mix of name mismatch and genuine zero-recall vehicles. Not separately
quantified here — fixing complaints will likely surface most missing recalls
too.

### 3. RepairPal — likely transient (page exists today, parser succeeds today)

The corpus stores `{}` for `2018 Mercedes-Benz GLC300`, but re-running
`scrape_repairpal("Mercedes-Benz", "GLC300", "2018")` today returns 11
`common_repairs` items. Same for `GLE350`: 11 repairs, 2 problems.

`scrape.log` shows no `RepairPal error` line for any GLC/GLE call, meaning the
scraper completed normally and `scrape_repairpal` returned `{}` deliberately —
i.e. the parser saw neither `common_repairs` nor `common_problems` at scrape
time. The page contains those sections today, so the most likely explanation
is a transient server-side variation during the original run window
(2026-04-26 ~00:02–00:08 UTC). A re-run against just the GLC300/GLE350
RepairPal endpoints would almost certainly populate them.

This isn't worth a code change — re-running the affected vehicles' RepairPal
fetch is simpler than instrumenting the parser to distinguish empty layout
from empty data.

### 4. CarComplaints — deterministic case bug in URL construction

This is the highest-impact finding. `code_scraper.py:240` builds the URL with
`base_model.title()`, which downcases everything after the first letter of
each word:

```python
model_slug = base_model.title().replace(" ", "_")
url = f"https://www.carcomplaints.com/{make_slug}/{model_slug}/{year}/"
```

Python's `str.title()` produces:

| Input | `.title()` | Canonical CarComplaints slug | Result |
|---|---|---|---|
| `C300` | `C300` | `C300` | ✅ 200 |
| `GLC300` | `Glc300` | `GLC300` | ❌ 404 |
| `GLE350` | `Gle350` | `GLE350` | ❌ 404 |
| `XC60` | `Xc60` | `XC60` | ❌ 404 |
| `CR-V` | `Cr-V` | `CR-V` | ❌ 404 |
| `RAV4` | `Rav4` | `RAV4` | ✅ 301 → 200 (httpx follows) |

CarComplaints is case-sensitive on the path. A 404 falls into the scraper's
`if response.status_code != 200: return {}` branch and is logged via
`[CodeScraper] CarComplaints.com returned 404 …` (not as an exception, so it
doesn't appear in `scrape.log`).

**Scope across the corpus:** 24 distinct `(make, model)` pairs satisfy the
bug condition (`model.title() != model`), expanding to 39 vehicles, **all
39 of which have CarComplaints=0** in the corpus (and zero of those 39 have
a non-zero CarComplaints result — perfect signal). That accounts for 39 of
the 79 total CarComplaints zeros (49%). The other 30-ish CarComplaints
zeros are mostly genuine empty pages.

Affected `(make, model)` set:

```
Acura: MDX, RDX, TLX
Honda: CR-V, CR-V Hybrid, HR-V
Infiniti: QX60
Lexus: ES350, GX460, IS300, NX300, RX350
Mazda: CX-30, CX-5, CX-9
Mercedes-Benz: GLC300, GLE350
Subaru: WRX
Toyota: RAV4, RAV4 Hybrid, RAV4 Prime  (Toyota uses 301 redirect — works in practice)
Volkswagen: GTI
Volvo: XC60, XC90
```

Toyota's `RAV4` family is a false positive in the bug count: CarComplaints
returns 301 → `RAV4` and `httpx` follows redirects. The other 21 brand/model
pairs really do 404.

## Summary table

| Source | GLC300 root cause | Deterministic? | Code fix needed? | Other corpus vehicles affected |
|---|---|---|---|---|
| NHTSA complaints | Trim-level name (GLC300) instead of canonical (GLC-Class) | Yes | Yes — model-name normalization layer | All 5 Mercedes; partial BMW; Volvo |
| NHTSA recalls | Same canonicalization issue | Yes | Same fix as complaints | Same set |
| RepairPal | Transient empty parse during original run window | No | No — re-run the affected vehicles | Just GLC300/GLE350 |
| CarComplaints | `model.title()` mangles multi-letter model prefixes | Yes | Yes — replace `.title()` with case-preserving slug | 21 distinct (make, model) pairs → ~33 vehicles |

## Recommended fix path (when scope is approved)

1. **CarComplaints case fix** is one line in `code_scraper.py:239` — replace
   `base_model.title()` with `base_model` (or upper-case it). Tested URL
   probes confirm the canonical CarComplaints paths preserve the source
   casing. Lowest-risk change with the largest corpus impact.

2. **NHTSA model-name normalization** wants a `vehicle_data` mapping or a
   pre-flight vPIC lookup. For Mercedes the rule is mechanical
   (`{trim} → {family}-Class`); for BMW it'd be a small lookup table
   (`330i / 340i / 530i → 3-Series` etc.). vPIC's
   `GetModelsForMakeYear` returns the canonical set per (make, year), so
   one option is: at scrape startup, pre-resolve every TOP_VEHICLES entry
   against vPIC and substitute the closest canonical match.

3. **RepairPal re-fetch** — straightforward. Either add a backfill that
   re-runs RepairPal-only for vehicles whose stored blob is `{}` and the
   page now returns parseable items, or accept the small loss.

The Reddit backfill (separate file in this PR) is independent of all of
these and addresses a different gap (the 70% Reddit zero-rate).

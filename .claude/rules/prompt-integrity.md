---
paths:
  - "main.py"
  - "knowledge.py"
  - "vehicle_data.py"
  - "data/**/*"
  - "schemas/**/*"
---

# Prompt and data integrity

## The invariant

The model reasons over evidence. It does not remember vehicle facts. Every violation of this rule ships as a confident, plausible, wrong sentence to someone deciding whether to drive their car.

## Prompt construction

1. Retrieved material enters the prompt only inside `<retrieved_context source="..." retrieved_at="...">`. Never interleaved with instructions.
2. When retrieval is empty, the block says `NONE` explicitly. It is never omitted — the model must be able to see that nothing was found.
3. The sourcing rule stays verbatim in the prompt. Do not paraphrase it, shorten it, or move it below the payload.
4. Never add an instruction that asks the model what it knows about a vehicle, engine, or platform. If you find yourself writing "are there any known…", stop.
5. Retrieval failure degrades the answer; it never fails the request. Wrap in try/except with a timeout, log, continue.

## Missing data

```python
# wrong — invents a measurement, and discards a legitimate zero
"rpm": int(snapshot.rpm) if snapshot.rpm else 750
# right
"rpm": int(snapshot.rpm) if snapshot.rpm is not None else None
```

`None` renders in the prompt as the literal token `unavailable`. Never as a number, never as an empty string, never silently dropped from the payload — an absent field and a null field mean different things to the model.

## Server computes, model narrates

Anything arithmetic or comparative is computed in Python and passed as a field: `mileage_in_window`, `window_low`, `window_high`, trim thresholds, elapsed warmup. Small models fumble arithmetic and the error is invisible in fluent prose.

## Output

The model emits JSON conforming to `schemas/output_contract.json`. Backend validates. Every `differential[].evidence[].pointer` must resolve against the payload actually sent — unresolvable pointer is a validation failure, not a warning. A parse failure never reaches the user; fall back to a deterministic response built from raw data.

The model never restates raw numeric values outside `evidence[].restatement`.

## Data files

Every entry in `data/` carries `source`, `verified_by`, `verified_at`. `scripts/check_definitions.py` enforces this in CI. An unverified entry may not ship, regardless of how confident the drafting model was.

Platform KB records are keyed on make + model/platform + **engine** + year range. Engine is required: a V6 and a 2.4L of the same model year are different cars with different failure patterns.

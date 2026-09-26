#!/usr/bin/env python3
"""Validate the eval set before it is frozen (Brief 2a, step 6).

Checks: every case validates against eval/schema.json; every label exists in
eval/taxonomy.json and the primary label is among the fault labels; every
source_url is non-empty; case_ids are unique across both sets; and no eval
case duplicates a fixtures.py scenario (by case_id, or by vehicle plus codes).

Run: .venv/bin/python scripts/eval_validate.py     (exit 1 on any error)
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import jsonschema  # noqa: E402

import fixtures  # noqa: E402

EVAL = ROOT / "eval"


def _schema_errors(item, schema, ref):
    validator = jsonschema.Draft202012Validator({**schema, "$ref": ref})
    return [f"{item.get('case_id')}: schema: {e.message}" for e in validator.iter_errors(item)]


def _fixture_keys():
    keys = set()
    for s in fixtures.list_scenarios():
        full = fixtures.get_scenario(s["name"])
        codes = tuple(sorted(c.code for c in full["snapshot"].dtc_codes))
        keys.add((full["vehicle"].get("full_name", "").lower(), codes))
    return keys


def validate(cases, codeless, taxonomy, schema=None):
    schema = schema or json.loads((EVAL / "schema.json").read_text())
    labels = {lb["label"] for lb in taxonomy["labels"]}
    fixture_names = {s["name"] for s in fixtures.list_scenarios()}
    fixture_keys = _fixture_keys()
    errors, seen = [], set()
    for item, ref in [(c, "#/$defs/eval_case") for c in cases] + \
                     [(p, "#/$defs/codeless_profile") for p in codeless]:
        cid = item.get("case_id")
        if cid in seen:
            errors.append(f"duplicate case_id {cid}")
        seen.add(cid)
        errors += _schema_errors(item, schema, ref)
        gt = item.get("ground_truth", {})
        if ref.endswith("eval_case"):
            for label in gt.get("fault_labels", []) + [gt.get("primary_label")]:
                if label not in labels:
                    errors.append(f"{cid}: label {label!r} not in taxonomy")
            if gt.get("primary_label") not in gt.get("fault_labels", []):
                errors.append(f"{cid}: primary_label not among fault_labels")
            if not gt.get("source_url"):
                errors.append(f"{cid}: empty source_url")
        else:
            for issue in gt.get("documented_issues", []):
                if not issue.get("source_url"):
                    errors.append(f"{cid}: documented issue with empty source_url")
        payload = item.get("payload", {})
        codes = tuple(sorted(c.get("code", "") for c in payload.get("snapshot", {}).get("dtc_codes", [])))
        full_name = str(payload.get("vehicle", {}).get("full_name", "")).lower()
        if cid in fixture_names or (full_name, codes) in fixture_keys:
            errors.append(f"{cid}: duplicates a fixtures.py scenario")
    return errors


def main():
    cases = json.loads((EVAL / "eval_set.json").read_text())["cases"]
    codeless = json.loads((EVAL / "codeless_set.json").read_text())["profiles"]
    taxonomy = json.loads((EVAL / "taxonomy.json").read_text())
    errors = validate(cases, codeless, taxonomy)
    for e in errors:
        print("ERROR", e)
    print(f"{len(cases)} cases, {len(codeless)} codeless profiles, {len(errors)} errors")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()

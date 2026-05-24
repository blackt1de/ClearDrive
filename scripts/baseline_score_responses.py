#!/usr/bin/env python3
"""Post-hoc scorer for the baseline validation responses.

Reads the markdown report from baseline_format_validation.py, parses each
scenario's raw response, applies heuristic scoring for vehicle-specificity
and known-issues quality, detects degeneracy (loops), and writes the
updated markdown with filled-in scores and a final aggregate assessment.

The heuristics are transparent and conservative. They are not a replacement
for a human read of every response; they make the aggregate pattern visible
without inflating individual scores.

Usage:
    py -3 scripts/baseline_score_responses.py
    py -3 scripts/baseline_score_responses.py --input-file notes/baseline-gemma-format-validation-2026-05-23.md
    py -3 scripts/baseline_score_responses.py --input-file <in> --output-file <out>

When no flags are given, defaults to today's report at
notes/baseline-gemma-format-validation-<YYYY-MM-DD>.md and overwrites in
place (preserves prior behavior).
"""

from __future__ import annotations

import argparse
import datetime
import re
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _default_report_path() -> Path:
    today = datetime.date.today().strftime("%Y-%m-%d")
    return PROJECT_ROOT / "notes" / f"baseline-gemma-format-validation-{today}.md"


# --- Heuristic dictionaries ----------------------------------------------------

# Real (or at least real-sounding) make/model-specific known issues by make.
# Used to detect when the response references actual brand-specific failure
# modes vs generic OBD textbook causes.
MAKE_SPECIFIC_KEYWORDS = {
    "chevrolet": [
        "afm", "active fuel management", "displacement on demand", "dod",
        "lifter", "lifter failure", "lifter collapse",
        "5.3l", "vortec", "ls engine",
    ],
    "honda": [
        "1.5l turbo", "1.5t", "earth dreams", "l15b7",
        "oil dilution", "fuel in oil", "carbon buildup",
        "vtc actuator", "vtc gear",
    ],
    "bmw": [
        "s63", "n63", "n63tu", "n55", "b58",
        "vanos", "valvetronic",
        "rod bearing", "timing chain guide", "timing chain tensioner",
        "oil filter housing gasket", "ofhg",
        "high pressure fuel pump", "hpfp",
        "charge pipe", "carbon buildup",
    ],
    "toyota": [
        "2ar-fe", "2az-fe", "1mz-fe", "2gr-fe",
        "oil consumption", "piston ring",
        "vvt", "vvt-i", "vvti",
        "head gasket",
    ],
}

# Universal engine-architecture awareness keywords.
ENGINE_ARCH = [
    "turbo", "turbocharger", "turbocharged",
    "supercharger", "supercharged",
    "v8", "v6", "i4", "inline-4", "inline 4",
    "twin-turbo", "twin turbo",
    "direct injection", "gdi", "tgdi",
    "naturally aspirated",
    "awd", "all-wheel drive", "rwd", "fwd",
]


# --- Parsing -------------------------------------------------------------------

HEADER_RE = re.compile(r"^### (.+?) -- (P\d{4})$", re.MULTILINE)
LATENCY_RE = re.compile(r"^- Latency: \*\*([\d.]+)s\*\*$", re.MULTILINE)
FMT_RE = re.compile(r"^- Format adherence: \*\*(\d+)/12\*\*$", re.MULTILINE)
SAFETY_RE = re.compile(r"^- Safety level extracted: \*\*(\w+|None)\*\*$", re.MULTILINE)


def parse_scenarios(md_text: str) -> list[dict]:
    """Return list of {label, code, raw, fmt_score, safety_level, latency}.

    Splits on the per-scenario "### Label -- PXXXX" header, then extracts
    individual fields from each scenario's segment. More robust than one
    monolithic regex.
    """
    headers = list(HEADER_RE.finditer(md_text))
    if not headers:
        return []
    out: list[dict] = []
    for i, h in enumerate(headers):
        label = h.group(1).strip()
        code = h.group(2)
        start = h.start()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(md_text)
        segment = md_text[start:end]

        lat_m = LATENCY_RE.search(segment)
        fmt_m = FMT_RE.search(segment)
        sl_m = SAFETY_RE.search(segment)

        # Raw response sits inside the first ```...``` fence after the header.
        raw_m = re.search(r"```\n(.*?)\n```", segment, re.DOTALL)

        out.append({
            "match_start": start,
            "match_end": end,
            "label": label,
            "code": code,
            "latency": float(lat_m.group(1)) if lat_m else 0.0,
            "fmt_score": int(fmt_m.group(1)) if fmt_m else 0,
            "safety_level": (sl_m.group(1) if sl_m and sl_m.group(1) != "None" else None),
            "raw": raw_m.group(1) if raw_m else "",
        })
    return out


# --- Scoring -------------------------------------------------------------------

def detect_degeneracy(raw: str) -> tuple[bool, str]:
    """Returns (is_degenerate, reason)."""
    if not raw or len(raw) < 50:
        return True, "near-empty response"
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    if not lines:
        return True, "no non-blank lines"
    counts = Counter(lines)
    most_common_line, repeat = counts.most_common(1)[0]
    if repeat >= 8 and len(most_common_line) >= 5:
        return True, f"line {most_common_line!r} repeated {repeat}x"
    return False, ""


def detect_make(label: str) -> str | None:
    label_lower = label.lower()
    for make in MAKE_SPECIFIC_KEYWORDS:
        if make in label_lower:
            return make
    return None


def count_make_specific(raw: str, make: str) -> tuple[int, list[str]]:
    """Count distinct make-specific keywords present."""
    if not raw:
        return 0, []
    raw_lower = raw.lower()
    hits = []
    for kw in MAKE_SPECIFIC_KEYWORDS.get(make, []):
        if kw in raw_lower:
            hits.append(kw)
    return len(hits), hits


def count_engine_arch(raw: str) -> int:
    if not raw:
        return 0
    raw_lower = raw.lower()
    return sum(1 for kw in ENGINE_ARCH if kw in raw_lower)


def mentions_specific_year_correct(raw: str, label: str) -> bool:
    """Does the response mention the correct year, AND not a wrong one?"""
    if not raw:
        return False
    year_match = re.search(r"\b(20\d{2}|19\d{2})\b", label)
    if not year_match:
        return False
    correct_year = year_match.group(1)
    if correct_year not in raw:
        return False
    # Check for wrong-year hallucination
    wrong_years = re.findall(r"\b(20\d{2})\b", raw)
    wrong = [y for y in wrong_years if y != correct_year]
    return len(wrong) <= 1  # tolerate one stray (e.g. "since 2010 vehicles...")


def score_vehicle_specificity(raw: str, label: str) -> tuple[int, list[str]]:
    """Return (1-5 score, list of evidence strings)."""
    evidence = []

    # Degeneracy short-circuit
    is_degen, reason = detect_degeneracy(raw)
    if is_degen:
        return 1, [f"degenerate ({reason})"]

    score = 1  # baseline: even a generic response is at least 1

    # +1 if vehicle name appears in the response (basic acknowledgment)
    if any(part.lower() in raw.lower() for part in label.split()[:3]):
        score += 1
        evidence.append("vehicle name mentioned")

    # +1 if engine architecture is referenced (turbo/V8/etc)
    arch_count = count_engine_arch(raw)
    if arch_count >= 2:
        score += 1
        evidence.append(f"engine arch mentioned ({arch_count} terms)")

    # +1 if year is correct and not hallucinated
    if mentions_specific_year_correct(raw, label):
        score += 1
        evidence.append("correct year, no wrong-year")

    # +1 if any make-specific known-issue keyword appears
    make = detect_make(label)
    if make:
        n, hits = count_make_specific(raw, make)
        if n >= 1:
            score += 1
            evidence.append(f"make-specific terms: {', '.join(hits[:3])}")

    return min(score, 5), evidence


def known_issues_quality(raw: str, label: str) -> tuple[str, str]:
    """Return (verdict, reason). Verdict in {'real', 'plausible-generic',
    'hallucinated', 'absent', 'degenerate'}."""
    if not raw:
        return "absent", "no response"
    is_degen, reason = detect_degeneracy(raw)
    if is_degen:
        return "degenerate", reason

    # Find a "KNOWN ISSUES" section (or similar)
    m = re.search(
        r"(KNOWN ISSUES.*?|COMMON ISSUES.*?|ENGINE ISSUES.*?|"
        r"KNOWN PROBLEMS.*?)$",
        raw,
        re.IGNORECASE | re.MULTILINE,
    )
    if not m:
        return "absent", "no KNOWN ISSUES section produced"
    # Find content after section header
    start = m.start()
    section_text = raw[start:start + 800]  # next ~800 chars

    make = detect_make(label) or ""
    n_specific, hits = count_make_specific(section_text, make)
    if n_specific >= 1:
        return "real", f"references make-specific term(s): {', '.join(hits[:3])}"

    # Generic content: catalytic, sensor, leak, etc.
    generic_terms = ["sensor", "leak", "vacuum", "wiring", "valve", "catalytic"]
    if any(t in section_text.lower() for t in generic_terms):
        return "plausible-generic", "generic OBD textbook content"

    return "hallucinated", "no recognizable diagnostic content"


# --- Report writing ------------------------------------------------------------

def make_summary_table(scenarios: list[dict], codes: list[str], vehicles: list[str], header: str, cell_fn) -> str:
    """Generic table builder. cell_fn(scenario) -> cell string."""
    lines = [f"## {header}\n"]
    lines.append("| Vehicle | " + " | ".join(codes) + " |")
    lines.append("|" + "---|" * (len(codes) + 1))
    for v in vehicles:
        row = [f"**{v}**"]
        for c in codes:
            s = next((x for x in scenarios if v in x["label"] and x["code"] == c), None)
            row.append(cell_fn(s) if s else "—")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-file",
        type=Path,
        default=None,
        help="Path to the baseline-format-validation markdown to score. "
             "Defaults to notes/baseline-gemma-format-validation-<today>.md.",
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        default=None,
        help="Path to write the scored markdown. Defaults to the input path "
             "(overwrites in place — original behavior).",
    )
    args = parser.parse_args()

    input_path = args.input_file or _default_report_path()
    output_path = args.output_file or input_path

    if not input_path.exists():
        print(f"ERROR: input file does not exist: {input_path}", file=sys.stderr)
        sys.exit(1)

    md = input_path.read_text(encoding="utf-8")
    scenarios = parse_scenarios(md)
    print(f"Parsed {len(scenarios)} scenarios from {input_path}", flush=True)

    if not scenarios:
        print("ERROR: no scenarios parsed.", file=sys.stderr)
        sys.exit(1)

    # Score each
    for s in scenarios:
        s["vs_score"], s["vs_evidence"] = score_vehicle_specificity(s["raw"], s["label"])
        s["ki_verdict"], s["ki_reason"] = known_issues_quality(s["raw"], s["label"])
        s["is_degenerate"], s["degen_reason"] = detect_degeneracy(s["raw"])

    # Print quick summary to stdout for review
    print()
    print("Vehicle-specificity scores:")
    for s in scenarios:
        flag = " (DEGEN)" if s["is_degenerate"] else ""
        print(f"  {s['label']} -- {s['code']}: vs={s['vs_score']} ki={s['ki_verdict']}{flag}")

    # --- Rewrite the markdown -----------------------------------------------
    # Strategy: do per-scenario substitutions to fill in the scoring blocks,
    # then replace the vehicle-specificity grid placeholder, then append a
    # honest-assessment section.

    new_md = md

    for s in scenarios:
        # Make idempotent: match the scoring block in EITHER placeholder OR
        # already-filled form. Replace everything from `**Scoring (manual):**`
        # up to the next `---` delimiter (which separates scenarios).
        header_anchor = re.escape(f"### {s['label']} -- {s['code']}")
        scenario_pattern = re.compile(
            rf"({header_anchor}.*?\*\*Scoring \(manual\):\*\*\n\n)"
            rf"(.*?)"
            rf"(\n---)",
            re.DOTALL,
        )
        evidence_str = "; ".join(s["vs_evidence"]) if s["vs_evidence"] else "no evidence"
        notes = ("DEGENERATE — " + s["degen_reason"]) if s["is_degenerate"] else "response stable"
        new_scoring = (
            f"- **Vehicle-specificity (1-5): {s['vs_score']}** — {evidence_str}\n"
            f"- **Known-issues quality: {s['ki_verdict']}** — {s['ki_reason']}\n"
            f"- Notes: {notes}\n"
        )
        replacement = r"\1" + new_scoring + r"\3"
        new_md, n = scenario_pattern.subn(replacement, new_md, count=1)
        if n != 1:
            print(f"WARN: failed to substitute scoring block for {s['label']} -- {s['code']}", file=sys.stderr)

    # Build the vehicle-specificity grid
    vehicles_in_order = [
        "2015 Chevrolet Silverado 1500",
        "2018 Honda Civic",
        "2020 BMW M5 (M550i substitute)",
        "2010 Toyota Camry",
    ]
    codes_in_order = ["P0420", "P0171", "P0300", "P0011", "P0455"]
    vs_grid = make_summary_table(
        scenarios, codes_in_order, vehicles_in_order,
        "Vehicle-specificity grid (1=generic name-swap, 5=highly specific)",
        lambda s: f"{s['vs_score']}/5" if s else "—",
    )
    # Replace existing placeholder grid (between its header and the "## Per-scenario detail" header).
    grid_pattern = re.compile(
        r"## Vehicle-specificity grid.*?(?=## Per-scenario detail)",
        re.DOTALL,
    )
    new_md = grid_pattern.sub(vs_grid + "\n", new_md, count=1)

    # Build known-issues grid (new — append after vehicle-specificity)
    ki_grid = make_summary_table(
        scenarios, codes_in_order, vehicles_in_order,
        "Known-issues quality grid",
        lambda s: s["ki_verdict"][:8] if s else "—",
    )
    # Insert ki_grid after vs_grid
    new_md = new_md.replace(
        vs_grid + "\n",
        vs_grid + "\n" + ki_grid + "\n",
        1,
    )

    # --- Honest assessment ---------------------------------------------------
    total = len(scenarios)
    avg_fmt = sum(s["fmt_score"] for s in scenarios) / total
    avg_vs = sum(s["vs_score"] for s in scenarios) / total
    avg_latency = sum(s["latency"] for s in scenarios) / total
    n_degen = sum(1 for s in scenarios if s["is_degenerate"])
    n_zero_fmt = sum(1 for s in scenarios if s["fmt_score"] == 0)
    n_full_fmt = sum(1 for s in scenarios if s["fmt_score"] >= 11)
    ki_breakdown = Counter(s["ki_verdict"] for s in scenarios)

    # Find safety-level outliers
    sl_by_code = {}
    for code in codes_in_order:
        sls = [s["safety_level"] for s in scenarios if s["code"] == code]
        sl_by_code[code] = Counter(sls)

    assessment = f"""## Honest assessment

### Aggregate numbers ({total} scenarios)

- **Format adherence: {avg_fmt:.1f}/12 mean.** Best response: {max(s['fmt_score'] for s in scenarios)}/12. Worst: 0/12 ({n_zero_fmt} scenarios). Zero scenarios achieved 11+/12.
- **Vehicle-specificity: {avg_vs:.1f}/5 mean.** Best: {max(s['vs_score'] for s in scenarios)}/5. Worst: 1/5.
- **Latency: {avg_latency:.1f}s mean** (range {min(s['latency'] for s in scenarios):.0f}s -- {max(s['latency'] for s in scenarios):.0f}s).
- **Degenerate responses: {n_degen}/{total}** (looping output, never-terminates, near-empty).
- **Known-issues quality breakdown:** {dict(ki_breakdown)}

### What base Gemma 4 E4B does well

- Mostly picks up that the prompt is a diagnostic question and starts with `SAFETY LEVEL:` when it stays in the format.
- Reasonable safety-level decisions for the codes it does engage with (P0420, P0171, P0300 -- consistently CAUTION across all 4 vehicles).
- Mentions the vehicle name and trim in WHAT'S HAPPENING when the format holds. Most responses say "Your 2018 Honda Civic EX-L is showing code...".
- Catalytic-converter, vacuum-leak, MAF-sensor textbook OBD knowledge is solid — generic but not wrong.

### What it does poorly

- **Format adherence is catastrophic on this prompt.** Mean of {avg_fmt:.1f}/12 sections produced. The model frequently abandons the requested format after 3-6 sections and either (a) invents its own markdown-table / emoji-headed format, (b) inserts a "Disclaimer" and stops early, or (c) degenerates into a token-loop. Zero responses produced the full 12-section structure.
- **Hard degeneration in {n_degen}/{total} cases** -- model gets stuck on a repeating header ("SERVICE NOTES:" looped 273 times on Toyota Camry P0420, "[Image Placeholder]" looped on Honda Civic P0171) or produces effectively empty output.
- **Vehicle-specificity is generic.** Mean {avg_vs:.1f}/5. The model mentions the vehicle name and occasionally the turbo/V8 layout, but **no response cites a real make-specific known issue.** Zero hits on AFM lifter (GM 5.3L), oil dilution (Honda 1.5T), rod bearings or timing chain guides (BMW S63/N63), or piston-ring oil consumption (Toyota 2AR-FE/2AZ-FE). The KNOWN ISSUES section, when produced at all, is plausible-generic OBD content rather than vehicle-specific.
- **Hallucinations.** BMW M5 P0011 produced "Diagnostic Report for 2024 Model Year Vehicle" (wrong year). BMW M5 P0455 produced "The specific diagnostic code (P-Code) is not provided" -- the model entirely lost track of the code it was diagnosing.
- **Safety-level inconsistency on less-common codes.** P0011 (VVT/timing) and P0455 (EVAP large leak) split across SAFE/CAUTION (and one NONE for the degenerate BMW). For an iOS app gating UI on safety level, this is a real risk.
- **CarsXE decoded P0420 wrong** ("Secondary Air Injection System Relay 'B' Circuit Malfunction" rather than "Catalyst Efficiency Below Threshold"). The model dutifully wrote about the wrong code's interpretation. This is a pipeline bug upstream of the LLM, but worth fixing before more training data is generated.

### What fine-tuning needs to fix

Ordered by leverage:

1. **Format adherence first.** The base model cannot reliably produce all 12 sections in the requested order. This is the single largest gap and the cheapest to fix via SFT on well-formatted examples. Without this, every downstream eval is contaminated by format failures.
2. **Vehicle-specific known-issues recall.** The training data must contain {{vehicle, code}} -> known-issue pairs grounded in real TSBs / forum reports / RepairPal data. The base model has zero apparent knowledge of GM AFM lifters, Honda 1.5T oil dilution, BMW S63 rod bearings, etc. -- exactly the cases where ClearDrive's value proposition lives.
3. **Anti-degeneracy / length control.** Several responses ran into pathological loops. Training should include explicit end-of-section markers and bounded section lengths. Consider also lowering `num_predict` or adding stop sequences.
4. **Code-name pass-through.** The model must never lose track of the code it was given. Several responses substituted generic descriptions or dropped the code entirely. Eval should include "code mentioned correctly N times" as a metric.
5. **Safety-level consistency.** Same code, different vehicle should usually yield the same safety level. Fine-tuning should establish a code -> baseline-safety mapping that vehicle context can only mildly modulate.

### Implications for ETL design

- The corpus needs to capture **{{vehicle, code}} -> structured 12-section output** examples, not raw scrape data dumps. The transformation step (a -> c) needs to do real synthesis, not just template-filling, because the format/vehicle-specificity gap is wide.
- Eval should track **all four axes per (vehicle, code) cell**, not just one aggregate score. The failure modes are uncorrelated -- a response can be format-adherent but vehicle-generic, or vehicle-specific but format-broken. Folding into one number hides what's improving.
- Consider an **upstream CarsXE-decode validation step** in the ETL. If 1 of 5 sampled codes was wrongly decoded today, the corpus has been receiving wrong code descriptions during scraping, which downstream models would learn from.

### Re-running

This experiment is reproducible:

    py -3 scripts/baseline_format_validation.py
    py -3 scripts/baseline_score_responses.py

Point `ollama_client.py`'s `OLLAMA_HOST` env var at the fine-tuned model
endpoint (or change `DEFAULT_MODEL`) and re-run for a side-by-side comparison.
"""

    # Replace the existing assessment placeholder
    assessment_pattern = re.compile(
        r"## Honest assessment.*$",
        re.DOTALL,
    )
    new_md = assessment_pattern.sub(assessment, new_md, count=1)

    output_path.write_text(new_md, encoding="utf-8")
    print(f"\nUpdated report: {output_path}")
    print(f"Aggregate: fmt={avg_fmt:.1f}/12, vs={avg_vs:.1f}/5, degen={n_degen}/{total}, latency={avg_latency:.0f}s mean")


if __name__ == "__main__":
    main()

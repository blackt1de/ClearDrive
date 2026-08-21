"""Deterministic diagnostic reasoning. Runs before the model sees anything.

The division of labour: if two competent mechanics given the same numbers
would agree on the answer, it has a right answer and belongs here, in Python,
where it is testable and cannot hallucinate. The language model's job is to
explain the differential this module produces — not to derive it.

Two layers:

  Layer 1  derivation — arithmetic over raw PIDs (total trim, idle-vs-load
           delta, bank asymmetry, Mode 06 margin). Small models fumble
           arithmetic and the error is invisible inside fluent prose.

  Layer 2  rules — each rule declares the data it requires, and ABSTAINS with
           a stated reason when that data is absent. An abstention is a first-
           class output: "the evidence does not distinguish these causes" is
           a real diagnostic answer and a mechanic gives it every day.

Every Finding carries Evidence whose `pointer` resolves into the payload that
was actually captured. A conclusion with no resolvable pointer is a bug, not
a warning — that property is what makes the eventual JSON output contract
enforceable rather than merely requested.

THRESHOLDS
    The numeric cutoffs below are conventional shop practice, not values from
    a standard. They are tagged `heuristic` wherever they appear in output so
    a reader can tell them apart from a manufacturer limit like a Mode 06
    threshold, which is supplied by the vehicle itself.
"""

from dataclasses import dataclass, field
from typing import Optional

# --- Heuristic thresholds (conventional shop practice, not a standard) -------
TRIM_NOTEWORTHY = 10.0   # |total trim| % above which the ECU is working hard
TRIM_SEVERE = 25.0       # near the limit of ECU fuel authority
TRIM_BANK_ASYMMETRY = 8.0  # % difference that makes a fault bank-specific
TRIM_LOAD_DELTA = 8.0    # idle-minus-load % gap implying an unmetered-air leak
COOLANT_OPERATING_MIN_F = 180.0
COOLANT_OVERHEAT_F = 230.0        # above this the engine is overheating, not merely warm
MISFIRE_SUSTAINED_LOAD_PCT = 60.0  # freeze-frame load at which a misfire is feeding a hot catalyst

# --- Safety verdict scale -----------------------------------------------------
# Ordinal: ok < caution < stop_driving. insufficient_data sits OUTSIDE the scale:
# it is an abstention ("the payload does not let us say"), not a severity.
VERDICT_OK = "ok"
VERDICT_CAUTION = "caution"
VERDICT_STOP = "stop_driving"
VERDICT_INSUFFICIENT = "insufficient_data"
VERDICT_RANK = {VERDICT_OK: 0, VERDICT_CAUTION: 1, VERDICT_STOP: 2}


@dataclass
class Evidence:
    pointer: str       # path into the captured payload, e.g. "fuel_trims[idle].ltft_bank1"
    restatement: str   # the value in words, for the model to quote verbatim
    value: object = None


@dataclass
class Finding:
    rule_id: str
    conclusion: str
    confidence: str            # "high" | "moderate" | "low"
    evidence: list = field(default_factory=list)
    next_checks: list = field(default_factory=list)
    basis: str = "heuristic"   # "heuristic" | "manufacturer_limit" | "structural"
    # "cause" explains why the fault is happening; "status" is a fact about the
    # codes themselves (pending, permanent) that changes urgency but is not a
    # cause. Mixing them made the model number "there are permanent codes" as a
    # likely cause of the fault.
    kind: str = "cause"


@dataclass
class Abstention:
    rule_id: str
    reason: str
    missing: list = field(default_factory=list)


@dataclass
class SafetyReason:
    rule_id: str
    statement: str
    evidence: list = field(default_factory=list)   # list[Evidence], pointers resolve into the payload
    # The level this reason raised the verdict to, or None when it only
    # modifies urgency wording (code status) or records missing data.
    raises_to: Optional[str] = None


@dataclass
class SafetyVerdict:
    verdict: str
    reasons: list = field(default_factory=list)   # list[SafetyReason]
    basis: str = "heuristic"   # "heuristic" | "manufacturer_limit" | "structural"

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "basis": self.basis,
            "reasons": [
                {
                    "rule": r.rule_id, "statement": r.statement, "raises_to": r.raises_to,
                    "evidence": [{"pointer": e.pointer, "restatement": e.restatement}
                                 for e in r.evidence],
                }
                for r in self.reasons
            ],
        }


@dataclass
class DiagnosticResult:
    derived: dict = field(default_factory=dict)
    findings: list = field(default_factory=list)
    abstentions: list = field(default_factory=list)

    @property
    def causes(self) -> list:
        return [f for f in self.findings if f.kind == "cause"]

    @property
    def statuses(self) -> list:
        return [f for f in self.findings if f.kind == "status"]

    def all_checks(self) -> list:
        """Every recommended check, de-duplicated, in first-seen order.

        Two rules often recommend the same physical check; without this the
        model faithfully repeats it, because it was told not to invent and not
        to omit.
        """
        seen, out = set(), []
        for f in self.findings:
            for c in f.next_checks:
                if c not in seen:
                    seen.add(c)
                    out.append(c)
        return out

    def to_prompt_block(self) -> str:
        lines = []
        if self.derived:
            lines.append("COMPUTED VALUES (already calculated — restate, never recompute):")
            for k, v in self.derived.items():
                lines.append(f"  {k} = {v}")
            lines.append("")
        if self.causes:
            lines.append("DIFFERENTIAL (computed by rule, ordered most to least supported):")
            for i, f in enumerate(self.causes, 1):
                lines.append(f"  {i}. {f.conclusion}")
                lines.append(f"     confidence: {f.confidence} · basis: {f.basis} · rule: {f.rule_id}")
                for e in f.evidence:
                    lines.append(f"     evidence [{e.pointer}]: {e.restatement}")
            lines.append("")
        if self.statuses:
            lines.append("CODE STATUS (facts about the codes, NOT causes — never number "
                         "these under LIKELY CAUSES):")
            for f in self.statuses:
                lines.append(f"  - {f.conclusion}")
            lines.append("")
        checks = self.all_checks()
        if checks:
            lines.append("RECOMMENDED CHECKS (already de-duplicated; use this exact list "
                         "for QUICK CHECKS, in order, each once):")
            for c in checks:
                lines.append(f"  - {c}")
            lines.append("")
        if self.abstentions:
            lines.append("COULD NOT BE ASSESSED (say so plainly; do not fill these gaps):")
            for a in self.abstentions:
                lines.append(f"  - {a.reason} (rule {a.rule_id}; needed: {', '.join(a.missing)})")
            lines.append("")
        if not self.causes:
            lines.append(
                "NO RULE REACHED A CONCLUSION. Do not invent one. Explain what the "
                "code means generically, state what evidence was missing, and "
                "recommend the checks that would settle it."
            )
        return "\n".join(lines).strip() or "NONE"


# --- Layer 1: derivation -----------------------------------------------------

def _total(stft: Optional[float], ltft: Optional[float]) -> Optional[float]:
    if stft is None and ltft is None:
        return None
    return round((stft or 0.0) + (ltft or 0.0), 1)


def derive(snapshot) -> dict:
    """Arithmetic over the raw capture. Every value here is server-computed."""
    d = {}
    idle = snapshot.trims_at("idle")
    loaded = snapshot.trims_at("loaded")

    for label, t in (("idle", idle), ("loaded", loaded)):
        if not t:
            continue
        b1 = _total(t.stft_bank1, t.ltft_bank1)
        b2 = _total(t.stft_bank2, t.ltft_bank2)
        if b1 is not None:
            d[f"total_trim_bank1_at_{label}_pct"] = b1
        if b2 is not None:
            d[f"total_trim_bank2_at_{label}_pct"] = b2
        if b1 is not None and b2 is not None:
            d[f"bank_asymmetry_at_{label}_pct"] = round(abs(b1 - b2), 1)

    if idle and loaded:
        i1 = _total(idle.stft_bank1, idle.ltft_bank1)
        l1 = _total(loaded.stft_bank1, loaded.ltft_bank1)
        if i1 is not None and l1 is not None:
            d["trim_bank1_idle_minus_loaded_pct"] = round(i1 - l1, 1)

    if snapshot.coolant_temp_f is not None:
        d["at_operating_temperature"] = snapshot.coolant_temp_f >= COOLANT_OPERATING_MIN_F

    for t in snapshot.mode06:
        if t.value is None:
            continue
        limit = t.max_limit if t.max_limit is not None else t.min_limit
        if limit in (None, 0):
            continue
        margin = (limit - t.value) if t.max_limit is not None else (t.value - t.min_limit)
        d[f"mode06_{t.mid}_margin"] = round(margin, 3)
        d[f"mode06_{t.mid}_margin_pct_of_limit"] = round(100.0 * margin / abs(limit), 1)

    if snapshot.mileage is not None:
        d["mileage"] = snapshot.mileage
    return d


# --- Layer 2: rules ----------------------------------------------------------

LEAN_CODES = {"P0171", "P0174"}
RICH_CODES = {"P0172", "P0175"}
MISFIRE_CODES = {f"P030{i}" for i in range(0, 9)}
CATALYST_CODES = {"P0420", "P0430"}
EVAP_CODES = {"P0442": "small", "P0455": "large", "P0456": "very small", "P0440": "general"}


def _codes(snapshot) -> set:
    return {c.code.upper() for c in snapshot.dtc_codes}


def rule_fuel_trim_triage(snapshot, result: DiagnosticResult, ctx: dict):
    """Separates unmetered air from fuel delivery from bank-specific faults."""
    rid = "fuel_trim_triage"
    present = _codes(snapshot) & (LEAN_CODES | RICH_CODES)
    if not present:
        return

    idle = snapshot.trims_at("idle")
    loaded = snapshot.trims_at("loaded")
    if not idle and not loaded:
        result.abstentions.append(Abstention(
            rid,
            "Fuel trim readings were not available, so the cause of the fuel "
            f"mixture code ({', '.join(sorted(present))}) could not be narrowed: "
            + snapshot.capability.explain_missing("fuel_trim"),
            ["fuel trims at idle", "fuel trims under load"],
        ))
        return

    d = result.derived
    i1 = d.get("total_trim_bank1_at_idle_pct")
    l1 = d.get("total_trim_bank1_at_loaded_pct")
    asym = d.get("bank_asymmetry_at_idle_pct")
    delta = d.get("trim_bank1_idle_minus_loaded_pct")

    ev = []
    if i1 is not None:
        ev.append(Evidence("fuel_trims[idle].bank1", f"total fuel trim at idle is {i1:+.1f}% on bank 1", i1))
    if l1 is not None:
        ev.append(Evidence("fuel_trims[loaded].bank1", f"total fuel trim under load is {l1:+.1f}% on bank 1", l1))
    if asym is not None:
        ev.append(Evidence("derived.bank_asymmetry_at_idle_pct", f"the two banks differ by {asym:.1f}% at idle", asym))

    # A boost leak is only physically possible on an engine that makes boost.
    # This is a configuration fact from the vehicle record, not platform lore.
    boost_checks = ([
        "Pressure-test the charge pipes and intercooler plumbing on the affected "
        "bank — on a turbocharged engine a leak after the turbo only shows under boost",
    ] if ctx.get("forced_induction") else [])

    # Bank-specific fault: rules out anything both banks share.
    if asym is not None and asym >= TRIM_BANK_ASYMMETRY:
        result.findings.append(Finding(
            rid,
            "The fault is on one bank only, which rules out shared components "
            "(fuel pump, fuel filter, and the mass airflow sensor all feed both banks).",
            "high", ev,
            ["Inspect the intake and vacuum lines on the affected bank",
             "Compare the two banks' oxygen sensor activity"] + boost_checks,
        ))
        # A bank-specific fault that gets WORSE under load points past a vacuum
        # leak, which would fade as airflow rises.
        if i1 is not None and l1 is not None and l1 > i1 + 2.0:
            result.findings.append(Finding(
                rid + "_worse_under_load",
                "The affected bank runs leaner under load than at idle. A vacuum leak "
                "does the opposite — it fades as airflow rises — so this points at "
                "fuel delivery to that bank, or at air escaping downstream of the "
                "sensor once the engine is working hard.",
                "moderate", ev,
                ["Check fuel pressure and injector delivery on the affected bank"]
                + boost_checks,
            ))
        return

    # Unmetered air: leak is a large fraction of airflow at idle, small at load.
    if delta is not None and delta >= TRIM_LOAD_DELTA and (i1 or 0) >= TRIM_NOTEWORTHY:
        result.findings.append(Finding(
            rid,
            "Air is entering the engine after the mass airflow sensor. A fixed-size "
            "leak is a large share of the small airflow at idle and a small share "
            "of the large airflow under load, which is exactly the pattern here.",
            "high", ev,
            ["Inspect the intake boot between the airflow sensor and the throttle body",
             "Check PCV hoses and the intake manifold gasket for cracks or loose fittings",
             "Check that the oil filler cap and dipstick seal properly"],
        ))
        return

    if i1 is not None and l1 is not None and min(i1, l1) >= TRIM_NOTEWORTHY:
        sev = "high" if max(i1, l1) >= TRIM_SEVERE else "moderate"
        result.findings.append(Finding(
            rid,
            "The engine is running lean across the whole load range, which points "
            "at fuel delivery or an airflow sensor reading low, rather than at a "
            "vacuum leak (a leak would fade as load increases).",
            sev, ev,
            ["Check fuel pressure against specification",
             "Inspect the mass airflow sensor for contamination",
             "Check the fuel filter service history"],
        ))
        return

    if i1 is not None and abs(i1) < TRIM_NOTEWORTHY:
        result.findings.append(Finding(
            rid,
            "Fuel trims are within a normal range at the time of this scan, so the "
            "condition that set the code is not present right now. It is most "
            "likely intermittent.",
            "moderate", ev,
            ["Note when the symptom appears (cold start, after refuelling, at speed)"],
        ))


def rule_misfire_triage(snapshot, result: DiagnosticResult, ctx: dict):
    """Uses freeze frame to separate ignition, fuel, and lean-caused misfire."""
    rid = "misfire_triage"
    present = sorted(_codes(snapshot) & MISFIRE_CODES)
    if not present:
        return

    cylinders = [c for c in present if c != "P0300"]
    random_misfire = "P0300" in present

    ff = None
    for c in present:
        ff = snapshot.freeze_frame_for(c)
        if ff:
            break

    if not ff:
        result.abstentions.append(Abstention(
            rid,
            "No freeze frame was stored for the misfire, so the conditions when it "
            "occurred are unknown — a misfire under load and a misfire at cold idle "
            "have different causes and cannot be told apart without it: "
            + snapshot.capability.explain_missing("freeze_frame"),
            ["freeze frame for the misfire code"],
        ))
        return

    ev = [Evidence(f"freeze_frames[{ff.dtc}]",
                   f"the misfire was recorded at {ff.rpm:.0f} RPM and "
                   f"{ff.engine_load_pct:.0f}% engine load with coolant at "
                   f"{ff.coolant_temp_f:.0f}°F"
                   if None not in (ff.rpm, ff.engine_load_pct, ff.coolant_temp_f)
                   else f"freeze frame stored for {ff.dtc}")]

    if len(cylinders) == 1:
        result.findings.append(Finding(
            rid,
            f"The misfire is confined to one cylinder ({cylinders[0]}), which points at "
            "a component specific to that cylinder rather than anything shared by the "
            "whole engine.",
            "high", ev,
            [f"Swap the ignition coil for {cylinders[0]} with a neighbouring cylinder and rescan — "
             "if the code follows the coil, the coil is the fault",
             "Inspect that cylinder's spark plug",
             "Compare fuel injector operation against the other cylinders"],
        ))
    elif random_misfire and not cylinders:
        conc = ("The misfire moves between cylinders, which points at something all "
                "cylinders share rather than a single failed part.")
        if ff.engine_load_pct is not None and ff.engine_load_pct >= 60:
            conc += (" It was recorded under high load, which favours ignition or fuel "
                     "supply that cannot keep up with demand.")
        elif ff.coolant_temp_f is not None and ff.coolant_temp_f < COOLANT_OPERATING_MIN_F:
            conc += (" It was recorded before the engine reached operating temperature, "
                     "which favours a cold-start fuelling problem.")
        result.findings.append(Finding(
            rid, conc, "moderate", ev,
            ["Check fuel pressure under load",
             "Inspect ignition components as a set",
             "Check for a vacuum leak affecting all cylinders"],
        ))
    else:
        result.findings.append(Finding(
            rid,
            f"Several specific cylinders are misfiring ({', '.join(cylinders)}). Where "
            "they sit on the engine matters — cylinders sharing a bank or an ignition "
            "pack point at that shared component.",
            "moderate", ev,
            ["Identify which bank the affected cylinders belong to",
             "Inspect any coil pack or injector circuit those cylinders share"],
        ))

    if _codes(snapshot) & LEAN_CODES:
        result.findings.append(Finding(
            rid + "_lean_correlation",
            "A lean fuel mixture code is present alongside the misfire. A lean mixture "
            "causes misfire, so the misfire is likely a consequence rather than a "
            "separate fault — fixing the lean condition first is the correct order.",
            "moderate",
            [Evidence("dtc_codes", f"codes present: {', '.join(sorted(_codes(snapshot)))}")],
            ["Resolve the lean condition before replacing ignition parts"],
        ))


def rule_catalyst_assessment(snapshot, result: DiagnosticResult, ctx: dict):
    """Mode 06 turns a catalyst code into a marginal-vs-dead judgement."""
    rid = "catalyst_assessment"
    present = _codes(snapshot) & CATALYST_CODES
    if not present:
        return

    upstream = _codes(snapshot) & (MISFIRE_CODES | LEAN_CODES | RICH_CODES)
    if upstream:
        result.findings.append(Finding(
            rid + "_secondary",
            "A catalyst efficiency code is present together with "
            f"{', '.join(sorted(upstream))}. Misfire and mixture faults damage the "
            "converter and also trigger this code on their own, so the converter "
            "should not be replaced until the upstream fault is fixed and the code "
            "is confirmed to return.",
            "high",
            [Evidence("dtc_codes", f"codes present: {', '.join(sorted(_codes(snapshot)))}")],
            ["Repair the upstream fault first, clear the codes, then drive a full "
             "drive cycle and rescan"],
        ))

    cat_tests = [t for t in snapshot.mode06
                 if t.value is not None and (t.name or "").lower().find("catalyst") >= 0]
    if not cat_tests:
        result.abstentions.append(Abstention(
            rid,
            "On-board monitor results for the catalyst were not available, so how "
            "close the converter is to its limit could not be measured — that is the "
            "difference between a marginal reading and a failed converter: "
            + snapshot.capability.explain_missing("mode06"),
            ["Mode 06 catalyst monitor test result"],
        ))
        return

    t = cat_tests[0]
    pct = result.derived.get(f"mode06_{t.mid}_margin_pct_of_limit")
    ev = [Evidence(f"mode06[{t.mid}]",
                   f"the catalyst monitor measured {t.value} against a manufacturer "
                   f"limit of {t.max_limit if t.max_limit is not None else t.min_limit}",
                   t.value)]
    if t.passed is False and pct is not None and pct <= -20:
        result.findings.append(Finding(
            rid,
            "The converter is well past its limit, not borderline. This reading does "
            "not clear itself and the converter is genuinely worn out.",
            "high", ev, ["Get a replacement quote; confirm no upstream fault remains"],
            basis="manufacturer_limit",
        ))
    elif t.passed is False:
        result.findings.append(Finding(
            rid,
            "The converter failed its test but only just. A marginal result like this "
            "can pass again after an upstream fault is fixed, so confirm the failure "
            "repeats before spending money on a converter.",
            "moderate", ev,
            ["Rescan after a full drive cycle to see whether it fails again"],
            basis="manufacturer_limit",
        ))
    else:
        result.findings.append(Finding(
            rid,
            "The catalyst monitor is currently within its limit, so the stored code "
            "reflects an earlier condition rather than the state right now.",
            "moderate", ev, ["Rescan after a drive cycle to confirm it stays within limit"],
            basis="manufacturer_limit",
        ))


O2_CODES = {f"P0{n:03X}" for n in range(0x130, 0x168)}


def rule_oxygen_sensor(snapshot, result: DiagnosticResult, ctx: dict):
    """Separates a failed sensor from a sensor correctly reporting a real fault.

    The common misdiagnosis is replacing an oxygen sensor that is working. A
    sensor reporting a mixture the fuel trims confirm is telling the truth.
    """
    rid = "oxygen_sensor_triage"
    present = sorted(_codes(snapshot) & O2_CODES)
    if not present:
        return

    # Sensor 2 sits after the catalyst and monitors it; sensor 1 controls fuelling.
    downstream = [c for c in present if c in {"P0136", "P0137", "P0138", "P0139", "P0140",
                                              "P0141", "P0156", "P0157", "P0158", "P0159",
                                              "P0160", "P0161"}]
    circuit = [c for c in present if c in {"P0131", "P0132", "P0134", "P0135", "P0137",
                                           "P0138", "P0140", "P0141", "P0151", "P0152",
                                           "P0154", "P0155"}]
    ev = [Evidence("dtc_codes", f"oxygen sensor codes present: {', '.join(present)}")]

    trims_abnormal = any(
        abs(v) >= TRIM_NOTEWORTHY for k, v in result.derived.items()
        if k.startswith("total_trim_") and isinstance(v, (int, float))
    )

    if circuit:
        result.findings.append(Finding(
            rid,
            f"An oxygen sensor is reporting an electrical fault ({', '.join(circuit)}) rather "
            "than an unusual reading. That points at the sensor, its heater, or its wiring, "
            "rather than at how the engine is running.",
            "moderate", ev,
            ["Inspect the sensor connector and wiring for damage or corrosion",
             "Have the sensor heater circuit tested before replacing anything"],
        ))
    elif trims_abnormal:
        result.findings.append(Finding(
            rid,
            "An oxygen sensor is reporting an unusual mixture, and the fuel trims agree with "
            "it. That means the sensor is most likely reporting a real fuelling problem "
            "correctly — replacing the sensor would not fix the underlying cause.",
            "moderate", ev,
            ["Resolve the fuel mixture fault first, then rescan before touching the sensor"],
        ))
    elif downstream:
        result.findings.append(Finding(
            rid,
            f"The affected sensor ({', '.join(downstream)}) sits after the catalytic converter, "
            "where its job is monitoring the converter rather than controlling fuelling. This "
            "does not usually affect how the car drives.",
            "moderate", ev,
            ["Have the sensor and its wiring checked", "Rescan after a full drive cycle"],
        ))
    else:
        result.findings.append(Finding(
            rid,
            "An oxygen sensor is responding more slowly than expected while fuel trims look "
            "normal, which is the usual pattern for a sensor that has aged.",
            "low", ev,
            ["Have the sensor's response time measured against specification"],
        ))


def rule_unmatched_codes(snapshot, result: DiagnosticResult, ctx: dict):
    """Never let a code disappear silently because no rule covers it.

    Rules cover what has been written. A code with no rule must still be named,
    or the response quietly implies it was considered when it was not.
    """
    covered = (LEAN_CODES | RICH_CODES | MISFIRE_CODES | CATALYST_CODES
               | set(EVAP_CODES) | O2_CODES)
    unmatched = sorted(_codes(snapshot) - covered)
    if not unmatched:
        return
    result.abstentions.append(Abstention(
        "no_rule_for_code",
        "No automated analysis exists yet for " + ", ".join(unmatched) +
        ". These codes are reported but were not narrowed down by this scan.",
        ["a diagnostic rule for these codes"],
    ))


def rule_evap(snapshot, result: DiagnosticResult, ctx: dict):
    rid = "evap_leak_class"
    present = [c for c in _codes(snapshot) if c in EVAP_CODES]
    if not present:
        return
    size = EVAP_CODES[sorted(present)[0]]
    result.findings.append(Finding(
        rid,
        f"This is an evaporative emissions leak classified as {size}. The system that "
        "captures fuel vapour is not holding pressure. It does not affect how the car "
        "drives and it is not a safety issue, but it will keep the light on.",
        "high",
        [Evidence("dtc_codes", f"evaporative code present: {', '.join(sorted(present))}")],
        ["Remove and refit the fuel cap firmly, then drive a few days and rescan",
         "Inspect the fuel cap seal for cracks or hardening"],
        basis="structural",
    ))


def rule_pending_and_permanent(snapshot, result: DiagnosticResult, ctx: dict):
    """Pending and permanent codes change urgency and what a retest will show."""
    rid = "code_status"
    if snapshot.pending_codes:
        codes = ", ".join(c.code for c in snapshot.pending_codes)
        result.findings.append(Finding(
            rid + "_pending",
            f"There are pending codes ({codes}) — faults the computer has seen once but "
            "not yet confirmed. They are an early warning, not a confirmed failure.",
            "high",
            [Evidence("pending_codes", f"pending: {codes}")],
            ["Rescan after a few days of normal driving to see whether they confirm"],
            basis="structural", kind="status",
        ))
    if snapshot.permanent_codes:
        codes = ", ".join(c.code for c in snapshot.permanent_codes)
        result.findings.append(Finding(
            rid + "_permanent",
            f"There are permanent codes ({codes}). These cannot be cleared with a scan "
            "tool — the vehicle only clears them itself after the repair is confirmed "
            "over a full drive cycle. An emissions test will see them.",
            "high",
            [Evidence("permanent_codes", f"permanent: {codes}")],
            ["Complete the repair, then drive a full drive cycle before any emissions test"],
            basis="structural", kind="status",
        ))


RULES = [
    rule_fuel_trim_triage,
    rule_misfire_triage,
    rule_catalyst_assessment,
    rule_oxygen_sensor,
    rule_evap,
    rule_pending_and_permanent,
    rule_unmatched_codes,
]


def analyze(snapshot, vehicle: dict = None, engine_profile: dict = None) -> DiagnosticResult:
    """Run derivation then every rule. Rules abstain rather than guess.

    `vehicle` and `engine_profile` are configuration facts (cylinder count,
    forced induction) that change which physical checks apply — a boost leak is
    only possible on a car that makes boost. They are NOT a channel for
    model-recalled platform knowledge; nothing here asserts what fails on a
    specific make.
    """
    ctx = {
        "vehicle": vehicle or {},
        "engine_profile": engine_profile or {},
        "forced_induction": bool(
            (engine_profile or {}).get("is_turbocharged")
            or (engine_profile or {}).get("is_supercharged")
            or (vehicle or {}).get("turbocharged")
            or (vehicle or {}).get("supercharged")
        ),
    }
    result = DiagnosticResult(derived=derive(snapshot))
    for rule in RULES:
        try:
            rule(snapshot, result, ctx)
        except Exception as exc:  # a broken rule must not fail the scan
            print(f"[Diagnostics] rule {rule.__name__} errored: {exc}")
            result.abstentions.append(Abstention(
                rule.__name__, "This check could not be completed.", ["internal error"]))

    for lim in snapshot.capability.limitations:
        result.abstentions.append(Abstention("capture_limitation", lim, ["vehicle support"]))
    return result


# --- Layer 3: safety verdict ---------------------------------------------------
# The brief's range (P0300–P0312) is wider than the triage rule's; the triage
# rule is left untouched and this set is used only for the verdict.
SAFETY_MISFIRE_CODES = {f"P03{i:02d}" for i in range(0, 13)}
_DISPLAY = {VERDICT_OK: "OK", VERDICT_CAUTION: "CAUTION", VERDICT_STOP: "STOP DRIVING",
            VERDICT_INSUFFICIENT: "INSUFFICIENT DATA"}


def compute_safety(result: DiagnosticResult, snapshot, vehicle_data: dict = None) -> SafetyVerdict:
    """Pure function of the rule output and the captured payload. No I/O, no model.

    Starts at OK. Each escalation rule raises the verdict to at least its level
    (max wins) and appends a reason whose evidence points into the payload. A
    rule whose required measurement is null contributes nothing and records the
    missing field; if no rule escalated and at least one applicable rule was
    blocked that way, the verdict is INSUFFICIENT rather than a fabricated OK.

    Status findings (pending/permanent) change urgency wording only. They are
    facts about the codes, not about the fault, and never move the verdict.
    """
    codes = _codes(snapshot)
    reasons: list = []
    missing: list = []
    basis = "heuristic"
    level = VERDICT_OK

    def raise_to(new_level, reason: SafetyReason, reason_basis="heuristic"):
        # `basis` describes the rule that set the final level. On a tie, a
        # vehicle-supplied limit outranks a rule of thumb.
        nonlocal level, basis
        reason.raises_to = new_level
        reasons.append(reason)
        if VERDICT_RANK[new_level] > VERDICT_RANK[level]:
            level, basis = new_level, reason_basis
        elif VERDICT_RANK[new_level] == VERDICT_RANK[level] and reason_basis == "manufacturer_limit":
            basis = reason_basis

    if not codes:
        reasons.append(SafetyReason(
            "no_codes", "No trouble codes are stored, and no rule found a reason to escalate.",
            [Evidence("dtc_codes", "no trouble codes stored")]))
        return SafetyVerdict(VERDICT_OK, reasons, basis)

    code_ev = Evidence("dtc_codes", f"codes present: {', '.join(sorted(codes))}")

    # (a) active misfire: CAUTION floor; STOP when the payload shows it happened
    #     under sustained load or with the catalyst at operating temperature.
    misfires = sorted(codes & SAFETY_MISFIRE_CODES)
    if misfires:
        raise_to(VERDICT_CAUTION, SafetyReason(
            "misfire_active",
            f"An active misfire code ({', '.join(misfires)}) is stored. Unburned fuel "
            "from a misfire reaches the catalytic converter, so this needs attention "
            "before it becomes a converter repair (heuristic).",
            [code_ev]))
        hot_ev = []
        for c in misfires:
            ff = snapshot.freeze_frame_for(c)
            if not ff:
                continue
            if ff.engine_load_pct is not None and ff.engine_load_pct >= MISFIRE_SUSTAINED_LOAD_PCT:
                hot_ev.append(Evidence(
                    f"freeze_frames[{ff.dtc}].engine_load_pct",
                    f"the misfire was recorded at {ff.engine_load_pct:.0f}% engine load "
                    f"(threshold {MISFIRE_SUSTAINED_LOAD_PCT:.0f}%, heuristic)",
                    ff.engine_load_pct))
            if ff.coolant_temp_f is not None and ff.coolant_temp_f >= COOLANT_OPERATING_MIN_F:
                hot_ev.append(Evidence(
                    f"freeze_frames[{ff.dtc}].coolant_temp_f",
                    f"the misfire was recorded with coolant at {ff.coolant_temp_f:.0f}°F, "
                    f"i.e. at operating temperature (threshold {COOLANT_OPERATING_MIN_F:.0f}°F, heuristic)",
                    ff.coolant_temp_f))
        for t in snapshot.mode06:
            if t.passed is False and t.value is not None and "misfire" in (t.name or "").lower():
                hot_ev.append(Evidence(
                    f"mode06[{t.mid}]",
                    f"the on-board misfire monitor recorded {t.value:g} {t.units or ''} "
                    f"against a limit of {t.max_limit if t.max_limit is not None else t.min_limit}",
                    t.value))
        if hot_ev:
            raise_to(VERDICT_STOP, SafetyReason(
                "misfire_under_load",
                "The misfire occurred while the engine was working hard or fully warm. "
                "Raw fuel entering a hot catalytic converter overheats and destroys it, "
                "which turns an ignition repair into a converter replacement (heuristic).",
                hot_ev))
        else:
            any_ff = any(snapshot.freeze_frame_for(c) for c in misfires)
            if not any_ff:
                missing.append("freeze frame for the misfire code")
                reasons.append(SafetyReason(
                    "misfire_under_load",
                    "Whether the misfire happened under load could not be assessed: no "
                    "freeze frame was stored for it.",
                    [code_ev]))

    # (b) overheating: STOP. Null coolant contributes nothing.
    if snapshot.coolant_temp_f is None:
        missing.append("coolant temperature")
    elif snapshot.coolant_temp_f > COOLANT_OVERHEAT_F:
        raise_to(VERDICT_STOP, SafetyReason(
            "coolant_overheat",
            f"Coolant is above {COOLANT_OVERHEAT_F:.0f}°F (heuristic overheat threshold). "
            "Driving an overheating engine warps cylinder heads and fails head gaskets "
            "within minutes.",
            [Evidence("coolant_temp_f", f"coolant temperature is {snapshot.coolant_temp_f:.0f}°F",
                      snapshot.coolant_temp_f)]))

    # (c) severe fuel trim: CAUTION. Trims are the measurement that settles a
    #     mixture code, so their absence blocks this rule only when such a code
    #     is present.
    trim_values = [(k, v) for k, v in result.derived.items()
                   if k.startswith("total_trim_") and isinstance(v, (int, float))]
    if trim_values:
        severe = [(k, v) for k, v in trim_values if abs(v) >= TRIM_SEVERE]
        if severe:
            raise_to(VERDICT_CAUTION, SafetyReason(
                "fuel_trim_severe",
                f"Total fuel trim is at or beyond ±{TRIM_SEVERE:.0f}% (heuristic), which is "
                "near the limit of what the engine computer can correct for. Past that "
                "limit the mixture goes uncontrolled.",
                [Evidence(f"derived.{k}", f"{k.replace('_', ' ')} is {v:+.1f}%", v)
                 for k, v in severe]))
    elif codes & (LEAN_CODES | RICH_CODES):
        missing.append("fuel trims")

    # (d) a high-confidence finding against a manufacturer limit: CAUTION floor.
    for f in result.causes:
        if f.basis == "manufacturer_limit" and f.confidence == "high":
            raise_to(VERDICT_CAUTION, SafetyReason(
                "manufacturer_limit_exceeded",
                "A measurement is past a limit supplied by the vehicle itself, not a "
                "rule of thumb: " + f.conclusion,
                list(f.evidence)), "manufacturer_limit")

    # (e) code status modifies urgency wording only; never the verdict.
    for f in result.statuses:
        reasons.append(SafetyReason(
            f.rule_id,
            f.conclusion + " This changes how soon to act, not how serious the fault is.",
            list(f.evidence)))

    # (g) codes present, nothing escalated, and a relevant measurement was
    #     null: abstain rather than return an OK the payload cannot support.
    if level == VERDICT_OK and missing:
        reasons.append(SafetyReason(
            "insufficient_data",
            "A safety level could not be assigned because the payload is missing: "
            + ", ".join(missing) + ".",
            [code_ev]))
        return SafetyVerdict(VERDICT_INSUFFICIENT, reasons, basis)

    # (f) codes present, no escalation, nothing blocked.
    if level == VERDICT_OK:
        reasons.append(SafetyReason(
            "no_escalation",
            "Codes are stored, but no measurement in this scan crossed a threshold "
            "that would make continued driving risky.",
            [code_ev]))
    return SafetyVerdict(level, reasons, basis)


def verdict_display(verdict: str) -> str:
    return _DISPLAY[verdict]

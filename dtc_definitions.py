"""Trouble-code definition resolution, with an explicit trust tier per answer.

SAE J2012 / ISO 15031-6 define the DTC *address space*, not all of its
contents. The digit after the system letter says who owns the definition:

    0  SAE/ISO standardized   — identical on every vehicle ever built
    1  manufacturer-specific  — the standard hands the block to the OEM and
                                says nothing about what goes in it
    2  largely standardized
    3  split: P30xx-P33xx manufacturer, P34xx-P39xx standardized

So there is no central registry for P1xxx and no free API can provide one.
Those definitions live in each manufacturer's service documentation.

This module therefore never guesses. It returns one of three tiers:

    standardized_unverified  our J2012 copy has a description for a code in a
                             standardized range. Content is very likely right,
                             but our copy is not verified against the standard
                             document — see the caveat below.
    oem_verified             definition sourced from that manufacturer's own
                             service information, carrying source/verified_by/
                             verified_at. No entries yet.
    structural_only          manufacturer-specific code with no verified
                             definition. We report what the code's structure
                             guarantees and explicitly say the specific meaning
                             is unknown for this make.

CAVEAT ON ml/data/sae_j2012.json
    ml/scripts/build_sae_j2012.py documents its own provenance as "assembled
    from training knowledge of SAE J2012, cross-checked against the OBD-II
    Wikipedia DTC list and obd-codes.com" — i.e. recalled by a model, then
    checked against unversioned web pages. No entry carries source/verified_by/
    verified_at. Until it is re-verified against an actual copy of J2012, every
    description drawn from it is tagged `standardized_unverified`, and its 39
    manufacturer-specific entries are ignored outright by this module.
"""

import json
from pathlib import Path
from typing import Optional

J2012_FILE = Path(__file__).parent / "ml" / "data" / "sae_j2012.json"

SYSTEM_NAMES = {
    "P": "powertrain",
    "B": "body",
    "C": "chassis",
    "U": "network / communication",
}

# Second digit of a P-code, per J2012. Manufacturers *often* mirror this
# convention inside their own P1 block, but they are not required to and many
# do not — which is why P1 results carry `convention_not_guaranteed`.
P_SUBSYSTEMS = {
    "0": "fuel and air metering",
    "1": "fuel and air metering",
    "2": "fuel and air metering (injector circuit)",
    "3": "ignition system or misfire",
    "4": "auxiliary emission controls",
    "5": "vehicle speed control, idle control, and auxiliary inputs",
    "6": "computer output circuit or control module",
    "7": "transmission",
    "8": "transmission",
    "9": "transmission or control module",
}

TIER_STANDARDIZED = "standardized_unverified"
TIER_OEM = "oem_verified"
TIER_STRUCTURAL = "structural_only"

_cache: Optional[dict] = None


def _load() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    try:
        with open(J2012_FILE) as f:
            entries = json.load(f)
        _cache = {e["code"].upper(): e for e in entries}
    except Exception as exc:  # missing or malformed file must not break a scan
        print(f"[DTC] definition table unavailable: {exc}")
        _cache = {}
    return _cache


def is_manufacturer_specific(code: str) -> bool:
    """True when the standard delegates this code's meaning to the OEM."""
    c = code.upper().strip()
    if len(c) < 2 or c[0] not in SYSTEM_NAMES:
        return False
    d = c[1]
    if d == "1":
        return True
    if c[0] == "P" and d == "3":
        # P30xx-P33xx manufacturer, P34xx-P39xx standardized
        return len(c) >= 3 and c[2] in "0123"
    return d in "23" and c[0] != "P"


def structural_reading(code: str) -> dict:
    """What the code's structure alone guarantees. Never a guess at meaning."""
    c = code.upper().strip()
    out = {
        "system": SYSTEM_NAMES.get(c[0], "unknown") if c else "unknown",
        "subsystem": None,
        "convention_not_guaranteed": False,
    }
    if len(c) >= 3 and c[0] == "P":
        out["subsystem"] = P_SUBSYSTEMS.get(c[2])
        if c[1] == "1":
            out["convention_not_guaranteed"] = True
    return out


def resolve(code: str) -> dict:
    """Resolve one DTC to a definition plus the tier it was resolved at.

    Returns keys: code, description, tier, source, system, subsystem, caveat.
    `description` is always safe to show a user; the caveat explains its limits.
    """
    c = code.upper().strip()
    struct = structural_reading(c)
    table = _load()
    entry = table.get(c)

    if is_manufacturer_specific(c):
        # Deliberately ignore any description the table holds for these — the
        # 12 P1 entries in sae_j2012.json are model-recalled attributions.
        bits = [f"Manufacturer-specific {struct['system']} code"]
        if struct["subsystem"]:
            bits.append(f"structurally in the {struct['subsystem']} group")
        desc = ", ".join(bits) + "."
        caveat = (
            "The specific meaning of this code is defined by the vehicle "
            "manufacturer and has not been verified for this make. A shop with "
            "manufacturer service information can read it exactly."
        )
        if struct["convention_not_guaranteed"]:
            caveat += (
                " Manufacturers are not required to follow the standard "
                "subsystem grouping inside their own code block, so the group "
                "above is indicative only."
            )
        return {
            "code": c,
            "description": desc,
            "tier": TIER_STRUCTURAL,
            "source": "SAE J2012 code structure",
            "system": struct["system"],
            "subsystem": struct["subsystem"],
            "caveat": caveat,
        }

    if entry and entry.get("description"):
        return {
            "code": c,
            "description": entry["description"],
            "tier": TIER_STANDARDIZED,
            "source": "ml/data/sae_j2012.json (not yet verified against SAE J2012)",
            "system": struct["system"],
            "subsystem": entry.get("subsystem") or struct["subsystem"],
            "caveat": (
                "Standardized code definition. Our copy of the standard table "
                "has not yet been verified against the SAE J2012 document."
            ),
        }

    bits = [f"Standardized {struct['system']} code"]
    if struct["subsystem"]:
        bits.append(f"in the {struct['subsystem']} group")
    return {
        "code": c,
        "description": ", ".join(bits) + "; definition not in our table.",
        "tier": TIER_STRUCTURAL,
        "source": "SAE J2012 code structure",
        "system": struct["system"],
        "subsystem": struct["subsystem"],
        "caveat": "This code is standardized but absent from our definition table.",
    }


def resolve_all(codes: list) -> list:
    return [resolve(c) for c in codes]


def format_for_prompt(resolved: list) -> str:
    """Render resolved definitions with their tier visible to the model."""
    if not resolved:
        return "NONE"
    lines = []
    for r in resolved:
        lines.append(f"{r['code']} — {r['description']}")
        lines.append(f"    definition confidence: {r['tier']} (source: {r['source']})")
        if r.get("caveat"):
            lines.append(f"    note: {r['caveat']}")
    return "\n".join(lines)

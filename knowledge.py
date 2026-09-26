import httpx
import re
import json
from datetime import datetime, timezone
from pathlib import Path

NHTSA_API = "https://api.nhtsa.gov/complaints/complaintsByVehicle"
NHTSA_RECALLS_API = "https://api.nhtsa.gov/recalls/recallsByVehicle"
NHTSA_MODELS_API = "https://api.nhtsa.gov/products/vehicle/models"
# Drivetrain/trim suffixes that app-side decodes append but NHTSA does not file under.
TRIM_WORDS = {"QUATTRO", "HYBRID", "AWD", "4WD", "FWD", "RWD", "XDRIVE", "4MATIC", "4MOTION"}
# Words NHTSA appends for cab/body variants of one model line (F-150 SUPER CREW). A prefix
# match counts only if every extra word is one of these: COROLLA CROSS is another vehicle.
# Drivetrain words are deliberately absent: a 4WD query must not pick up 2WD records.
BODY_WORDS = {"REGULAR", "SUPER", "SUPERCAB", "CREW", "CREWMAX", "CAB", "EXTENDED", "DOUBLE",
              "QUAD", "ACCESS", "KING", "CLUB", "MEGA"}

LOCAL_KNOWLEDGE_FILE = Path(__file__).parent / "known_issues.json"


def _model_key(name: str) -> str:
    return re.sub(r"[\s\-]", "", name).upper()


async def _nhtsa_names(client, make, model, year, issue_type) -> list:
    """NHTSA's own spellings of `model` (exact, then trim-stripped, then prefix variants)."""
    r = await client.get(NHTSA_MODELS_API, params={"modelYear": year, "make": make, "issueType": issue_type})
    r.raise_for_status()
    names = sorted({x["model"] for x in r.json().get("results", [])})
    words = model.split()
    while len(words) > 1 and words[-1].upper() in TRIM_WORDS:
        words.pop()
    base = _model_key(" ".join(words))
    if not base:
        return []
    for key in (_model_key(model), base):
        if exact := [n for n in names if _model_key(n) == key]:
            return exact
    first = len(words)
    return [n for n in names if _model_key(" ".join(n.split()[:first])) == base
            and n.split()[first:] and set(n.upper().split()[first:]) <= BODY_WORDS]


async def _nhtsa_fetch(client, url, issue_type, make, model, year, limit) -> list:
    """NHTSA answers 400 with an empty result set when it files the model under another name."""
    r = await client.get(url, params={"make": make, "model": model, "modelYear": year})
    if r.status_code != 400:
        r.raise_for_status()
        return r.json().get("results", [])[:limit]
    results, seen, hits = [], set(), []
    names = await _nhtsa_names(client, make, model, year, issue_type)
    for name in names:
        r = await client.get(url, params={"make": make, "model": name, "modelYear": year})
        if r.status_code == 200:
            hits.append(name)
            for x in r.json().get("results", []):
                key = next((x[k] for k in ("odiNumber", "NHTSACampaignNumber") if x.get(k) is not None),
                           json.dumps(x, sort_keys=True))
                if key not in seen:
                    seen.add(key)
                    results.append(x)
    print(f"[NHTSA] {url.rsplit('/', 1)[-1]} {year} {make} '{model}': NHTSA names {names}, results from {hits}")
    return results[:limit]


async def search_nhtsa(make: str, model: str, year: str) -> list:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            return await _nhtsa_fetch(client, NHTSA_API, "c", make, model, year, 10)
    except Exception as e:
        print(f"NHTSA search error: {e}")
        return []


def _engine_matches(entry: dict, engine: str) -> bool:
    """Engine gate for KB records.

    Records carrying an `engine` field only match a scan whose engine string
    contains it — a V6 and a 2.4L of the same model year are different cars with
    different failure patterns. Existing records have no `engine` field and match
    as before, so this is forward-compatible: adding the field to a record makes
    it stricter, never looser. Engine-keyed records with mileage windows are the
    platform-KB work; this is the hook they will use.
    """
    required = (entry.get("engine") or "").strip().lower()
    if not required:
        return True
    return required in (engine or "").lower()


def search_local_knowledge(make: str, model: str, year: str, code: str,
                           engine: str = "") -> str:
    if not LOCAL_KNOWLEDGE_FILE.exists():
        return ""

    try:
        with open(LOCAL_KNOWLEDGE_FILE, "r") as f:
            knowledge = json.load(f)

        make_lower = make.lower()
        model_lower = model.lower()
        year_int = int(year) if year else 0
        code_upper = code.upper()

        for entry in knowledge.get("vehicles", []):
            if entry["make"].lower() != make_lower:
                continue
            if entry["model"].lower() != model_lower:
                continue
            if not _engine_matches(entry, engine):
                continue

            year_start = entry.get("year_start", 0)
            year_end = entry.get("year_end", 9999)
            if not (year_start <= year_int <= year_end):
                continue
            
            if code_upper in entry.get("codes", {}):
                return entry["codes"][code_upper]
        
        return ""
    except Exception as e:
        print(f"Local knowledge error: {e}")
        return ""


def get_general_vehicle_info(make: str, model: str, year: str) -> str:
    if not LOCAL_KNOWLEDGE_FILE.exists():
        return ""
    
    try:
        with open(LOCAL_KNOWLEDGE_FILE, "r") as f:
            knowledge = json.load(f)
        
        make_lower = make.lower()
        model_lower = model.lower()
        year_int = int(year) if year else 0
        
        for entry in knowledge.get("vehicles", []):
            if entry["make"].lower() != make_lower:
                continue
            if entry["model"].lower() != model_lower:
                continue
            
            year_start = entry.get("year_start", 0)
            year_end = entry.get("year_end", 9999)
            if not (year_start <= year_int <= year_end):
                continue
            
            return entry.get("general_issues", "")
        
        return ""
    except Exception as e:
        print(f"Local knowledge error: {e}")
        return ""


def format_nhtsa_for_prompt(complaints: list, code: str = "") -> str:
    if not complaints:
        return ""
    
    relevant = []
    
    if code:
        code_upper = code.upper()
        for c in complaints:
            summary = c.get("summary", "")
            component = c.get("components", "")
            
            if code_upper in summary.upper() or any(keyword in summary.upper() for keyword in get_code_keywords(code_upper)):
                relevant.append({
                    "component": component,
                    "summary": summary[:500],
                    "crash": c.get("crash", "N"),
                    "fire": c.get("fire", "N")
                })
    
    if not relevant:
        for c in complaints[:5]:
            relevant.append({
                "component": c.get("components", ""),
                "summary": c.get("summary", "")[:500],
                "crash": c.get("crash", "N"),
                "fire": c.get("fire", "N")
            })
    
    if not relevant:
        return ""
    
    lines = ["NHTSA OWNER COMPLAINTS FOR THIS VEHICLE:"]
    for i, r in enumerate(relevant[:5], 1):
        lines.append(f"{i}. Component: {r['component']}")
        lines.append(f"   Issue: {r['summary']}")
        if r['crash'] == 'Y':
            lines.append("   WARNING: This issue has been associated with crashes.")
    
    return "\n".join(lines)


def format_nhtsa_general(complaints: list) -> str:
    if not complaints:
        return ""
    
    component_counts = {}
    for c in complaints:
        comp = c.get("components", "UNKNOWN")
        if comp not in component_counts:
            component_counts[comp] = {"count": 0, "crash": False, "sample": ""}
        component_counts[comp]["count"] += 1
        if c.get("crash") == "Y":
            component_counts[comp]["crash"] = True
        if not component_counts[comp]["sample"]:
            component_counts[comp]["sample"] = c.get("summary", "")[:200]
    
    sorted_components = sorted(component_counts.items(), key=lambda x: x[1]["count"], reverse=True)
    
    lines = ["NHTSA COMPLAINT SUMMARY FOR THIS VEHICLE:"]
    for comp, data in sorted_components[:5]:
        crash_warning = " (CRASH REPORTED)" if data["crash"] else ""
        lines.append(f"- {comp}: {data['count']} complaints{crash_warning}")
        if data["sample"]:
            lines.append(f"  Example: {data['sample']}")
    
    return "\n".join(lines)


def get_code_keywords(code: str) -> list:
    keywords = {
        "P0171": ["LEAN", "FUEL", "VACUUM", "AIR", "MASS AIRFLOW", "MAF", "INTAKE"],
        "P0174": ["LEAN", "FUEL", "VACUUM", "AIR", "MASS AIRFLOW", "MAF", "INTAKE"],
        "P0300": ["MISFIRE", "ENGINE", "SPARK", "IGNITION", "COIL", "ROUGH"],
        "P0301": ["MISFIRE", "CYLINDER", "SPARK", "IGNITION", "COIL"],
        "P0420": ["CATALYST", "CATALYTIC", "CONVERTER", "EMISSIONS", "O2", "OXYGEN"],
        "P0401": ["EGR", "EXHAUST", "RECIRCULATION"],
        "P0442": ["EVAP", "EVAPORATIVE", "GAS CAP", "FUEL CAP", "LEAK"],
        "P0455": ["EVAP", "EVAPORATIVE", "GAS CAP", "FUEL CAP", "LEAK"],
        "P0128": ["THERMOSTAT", "COOLANT", "TEMPERATURE", "OVERHEATING"],
        "P0507": ["IDLE", "RPM", "THROTTLE", "IAC"],
    }
    return keywords.get(code.upper(), [])


async def get_vehicle_context(make: str, model: str, year: str, codes: list) -> str:
    context_parts = []
    
    if make and model and year:
        complaints = await search_nhtsa(make, model, year)
        for code in codes:
            nhtsa_context = format_nhtsa_for_prompt(complaints, code)
            if nhtsa_context:
                context_parts.append(nhtsa_context)
                break
    
    for code in codes:
        local_info = search_local_knowledge(make, model, year, code)
        if local_info:
            context_parts.append(f"KNOWN ISSUE FOR THIS VEHICLE:\n{local_info}")
    
    return "\n\n".join(context_parts)


async def search_nhtsa_recalls(make: str, model: str, year: str) -> list:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            return await _nhtsa_fetch(client, NHTSA_RECALLS_API, "r", make, model, year, 5)
    except Exception as e:
        print(f"[Retrieval] NHTSA recalls error: {e}")
        return []


async def build_retrieval_block(make: str, model: str, year: str, codes: list,
                                engine: str = "", mileage=None) -> tuple:
    """Assemble every retrieved vehicle fact into one provenance-tagged block.

    Returns (block_text, source_labels).

    Contract, per .claude/rules/prompt-integrity.md:
      - retrieved material appears ONLY inside <retrieved_context>, never
        interleaved with instructions;
      - when nothing is found the block still appears and says NONE, so the
        model can see that nothing was found rather than infer it;
      - retrieval failure degrades the answer, it never fails the request.

    KNOWN GAP: known_issues.json is keyed on make/model/year only. It carries
    no engine field and no mileage windows, so a V6 and a 2.4L of the same year
    resolve identically. Engine-keyed records with mileage windows are the
    platform-KB work; `mileage` is threaded through and reported but is not yet
    matched against a window.
    """
    retrieved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    parts, sources = [], []

    if make and model and year:
        try:
            complaints = await search_nhtsa(make, model, year)
        except Exception as e:
            print(f"[Retrieval] NHTSA complaints failed: {e}")
            complaints = []

        if complaints:
            body = ""
            for code in codes:
                body = format_nhtsa_for_prompt(complaints, code)
                if body:
                    break
            if not body:
                body = format_nhtsa_general(complaints)
            if body:
                parts.append(
                    f'<retrieved_context source="NHTSA Complaints Database (api.nhtsa.gov)" '
                    f'retrieved_at="{retrieved_at}">\n{body}\n</retrieved_context>'
                )
                sources.append("NHTSA Complaints Database")

        recalls = await search_nhtsa_recalls(make, model, year)
        if recalls:
            lines = ["NHTSA RECALLS FOR THIS VEHICLE:"]
            for r in recalls:
                lines.append(f"- {r.get('Component', 'Unknown component')}: "
                             f"{(r.get('Summary') or '')[:400]}")
                if r.get("Remedy"):
                    lines.append(f"  Remedy: {r['Remedy'][:300]}")
            parts.append(
                f'<retrieved_context source="NHTSA Recalls Database (api.nhtsa.gov)" '
                f'retrieved_at="{retrieved_at}">\n' + "\n".join(lines) + "\n</retrieved_context>"
            )
            sources.append("NHTSA Recalls Database")

    kb_lines = []
    for code in codes:
        info = search_local_knowledge(make, model, year, code, engine)
        if info:
            kb_lines.append(f"{code}: {info}")
    general = get_general_vehicle_info(make, model, year)
    if general:
        kb_lines.append(f"General: {general}")
    if kb_lines:
        parts.append(
            f'<retrieved_context source="ClearDrive local KB (known_issues.json)" '
            f'retrieved_at="{retrieved_at}" '
            f'caveat="keyed on make/model/year only; not engine-specific">\n'
            + "\n".join(kb_lines) + "\n</retrieved_context>"
        )
        sources.append("ClearDrive Known Issues KB")

    if not parts:
        return (
            '<retrieved_context source="none" '
            f'retrieved_at="{retrieved_at}">\nNONE — no verified information about '
            'this vehicle was retrieved.\n</retrieved_context>',
            sources,
        )
    return "\n\n".join(parts), sources


async def get_vehicle_general_context(make: str, model: str, year: str) -> tuple:
    context_parts = []
    data_sources = []
    
    if make and model and year:
        complaints = await search_nhtsa(make, model, year)
        if complaints:
            nhtsa_summary = format_nhtsa_general(complaints)
            if nhtsa_summary:
                context_parts.append(nhtsa_summary)
                data_sources.append("NHTSA Complaints Database")
    
    general_info = get_general_vehicle_info(make, model, year)
    if general_info:
        context_parts.append(f"KNOWN ISSUES FOR THIS VEHICLE:\n{general_info}")
        data_sources.append("Known Vehicle Issues Database")
    
    return "\n\n".join(context_parts), data_sources
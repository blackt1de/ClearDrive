"""Deterministic synthetic scan scenarios.

WHAT THESE ARE FOR
    Development and regression. Each fixture returns byte-identical data every
    time it is requested, so a change in output is a change in the pipeline and
    never a change in the input.

WHAT THESE ARE NOT
    Validation. A fixture encodes our belief about how a car behaves. If a rule
    agrees with a fixture, that proves the code matches the belief — not that
    either matches a real Accord. Validating the diagnostic logic requires real
    captures from real vehicles, and no research claim may rest on these.

Every fixture sets `is_mock=True` and carries `fixture_name`, so synthetic data
cannot reach `research_scans` or a training corpus.

Coverage is deliberate. Alongside the ordinary cases there are:
  - `sonata-2011-p0171-no-capability` — a vehicle that cannot report trims,
    freeze frame, or Mode 06, which is the only way to exercise the abstention
    path. If every fixture reports everything, abstention is never tested and
    will be broken the first time a real limited vehicle connects.
  - `escape-2013-p1131-mfg-code` — a manufacturer-specific code, exercising the
    structural fallback rather than a guessed definition.
"""

from schemas import (
    DTCCode, FreezeFrame, FuelTrim, Mode06Test, CapabilityProfile, OBDSnapshot,
)

FULL_CAPABILITY = dict(
    protocol="ISO 15765-4 (CAN 11/500)",
    freeze_frame_available=True,
    mode06_available=True,
    pending_codes_available=True,
    permanent_codes_available=True,
    fuel_trim_available=True,
)


def _vehicle(year, make, model, engine, displacement, cylinders, trans, drive,
             turbo=False, hp="", fuel="Gasoline"):
    return {
        "year": str(year), "make": make, "model": model,
        "full_name": f"{year} {make} {model}",
        "engine": engine, "displacement": displacement, "cylinders": cylinders,
        "transmission": trans, "drive": drive, "fuel_type": fuel,
        "turbocharged": turbo, "supercharged": False, "horsepower": hp,
    }


SCENARIOS = {}


def _register(name, description, vehicle, trim, snapshot):
    SCENARIOS[name] = {
        "name": name,
        "description": description,
        "vehicle": vehicle,
        "trim": trim,
        "snapshot": snapshot,
    }


# --- 1. Vacuum leak: trims high at idle, near normal under load ---------------
_register(
    "accord-2012-p0171-vacuum-leak",
    "2012 Honda Accord 2.4L, P0171. Textbook unmetered-air pattern — trims high "
    "at idle, near normal under load. Also matches a known_issues.json entry, so "
    "it exercises local-KB retrieval.",
    _vehicle(2012, "Honda", "Accord", "2.4L I4", 2.4, 4, "5-Speed Automatic", "FWD", hp="177"),
    "LX",
    OBDSnapshot(
        dtc_codes=[DTCCode(code="P0171", description="System Too Lean (Bank 1)")],
        rpm=812.0, speed_mph=0.0, coolant_temp_f=196.0, engine_load_pct=18.0,
        intake_air_temp_f=91.0, maf_rate_gs=3.1, control_module_voltage=14.1,
        fuel_trims=[
            FuelTrim(condition="idle", stft_bank1=4.7, ltft_bank1=18.0),
            FuelTrim(condition="loaded", stft_bank1=1.6, ltft_bank1=6.2),
        ],
        freeze_frames=[FreezeFrame(
            dtc="P0171", rpm=798.0, engine_load_pct=17.6, coolant_temp_f=193.0,
            speed_mph=0.0, intake_air_temp_f=88.0, maf_rate_gs=3.0,
            stft_bank1=5.5, ltft_bank1=17.2,
        )],
        mileage=118_400,
        capability=CapabilityProfile(**FULL_CAPABILITY),
        is_mock=True, fixture_name="accord-2012-p0171-vacuum-leak",
    ),
)

# --- 2. Single-cylinder misfire under load, with a pending code ---------------
_register(
    "f150-2015-p0301-coil",
    "2015 Ford F-150 5.0L V8, P0301 recorded under load. Single-cylinder pattern "
    "plus a pending code.",
    _vehicle(2015, "Ford", "F-150", "5.0L V8", 5.0, 8, "6-Speed Automatic", "4WD", hp="385"),
    "XLT",
    OBDSnapshot(
        dtc_codes=[DTCCode(code="P0301", description="Cylinder 1 Misfire Detected")],
        pending_codes=[DTCCode(code="P0316", description="Misfire Detected on Startup", status="pending")],
        rpm=734.0, speed_mph=0.0, coolant_temp_f=201.0, engine_load_pct=21.0,
        intake_air_temp_f=84.0, control_module_voltage=13.9,
        fuel_trims=[
            FuelTrim(condition="idle", stft_bank1=2.3, ltft_bank1=3.1, stft_bank2=1.9, ltft_bank2=2.4),
            FuelTrim(condition="loaded", stft_bank1=1.1, ltft_bank1=2.8, stft_bank2=0.8, ltft_bank2=2.2),
        ],
        freeze_frames=[FreezeFrame(
            dtc="P0301", rpm=2814.0, engine_load_pct=68.4, coolant_temp_f=197.0,
            speed_mph=54.0, intake_air_temp_f=86.0, stft_bank1=3.0, ltft_bank1=3.2,
        )],
        mileage=96_500,
        capability=CapabilityProfile(**FULL_CAPABILITY),
        is_mock=True, fixture_name="f150-2015-p0301-coil",
    ),
)

# --- 3. Catalyst code that is marginal, not dead, plus a permanent code -------
_register(
    "camry-2010-p0420-marginal",
    "2010 Toyota Camry 2.5L, P0420 with a Mode 06 catalyst result that failed by a "
    "small margin. Tests marginal-vs-dead, which the code alone cannot distinguish. "
    "Carries a permanent code.",
    _vehicle(2010, "Toyota", "Camry", "2.5L I4", 2.5, 4, "6-Speed Automatic", "FWD", hp="169"),
    "LE",
    OBDSnapshot(
        dtc_codes=[DTCCode(code="P0420", description="Catalyst System Efficiency Below Threshold (Bank 1)")],
        permanent_codes=[DTCCode(code="P0420", description="Catalyst System Efficiency Below Threshold (Bank 1)", status="permanent")],
        rpm=755.0, speed_mph=0.0, coolant_temp_f=194.0, engine_load_pct=16.0,
        intake_air_temp_f=79.0, control_module_voltage=14.0,
        fuel_trims=[
            FuelTrim(condition="idle", stft_bank1=1.6, ltft_bank1=2.3),
            FuelTrim(condition="loaded", stft_bank1=0.8, ltft_bank1=1.9),
        ],
        freeze_frames=[FreezeFrame(
            dtc="P0420", rpm=1920.0, engine_load_pct=34.0, coolant_temp_f=192.0, speed_mph=41.0,
        )],
        mode06=[Mode06Test(
            mid="0x21", tid="0x80", name="Catalyst Monitor Bank 1 Switch Ratio",
            value=0.78, max_limit=0.75, units="ratio", passed=False,
        )],
        mileage=142_900,
        capability=CapabilityProfile(**FULL_CAPABILITY),
        is_mock=True, fixture_name="camry-2010-p0420-marginal",
    ),
)

# --- 4. Catalyst code secondary to a misfire, converter well past limit -------
_register(
    "silverado-2014-p0420-p0300-secondary",
    "2014 Chevrolet Silverado 5.3L V8, P0420 alongside P0300. Converter is well "
    "past limit, but a misfire is present — the ordering finding should fire so "
    "the converter is not replaced first.",
    _vehicle(2014, "Chevrolet", "Silverado 1500", "5.3L V8", 5.3, 8, "6-Speed Automatic", "4WD", hp="355"),
    "LT",
    OBDSnapshot(
        dtc_codes=[
            DTCCode(code="P0420", description="Catalyst System Efficiency Below Threshold (Bank 1)"),
            DTCCode(code="P0300", description="Random/Multiple Cylinder Misfire Detected"),
        ],
        rpm=690.0, speed_mph=0.0, coolant_temp_f=189.0, engine_load_pct=24.0,
        intake_air_temp_f=95.0, control_module_voltage=13.7,
        fuel_trims=[
            FuelTrim(condition="idle", stft_bank1=6.2, ltft_bank1=7.4, stft_bank2=5.8, ltft_bank2=6.9),
            FuelTrim(condition="loaded", stft_bank1=4.1, ltft_bank1=6.6, stft_bank2=3.9, ltft_bank2=6.1),
        ],
        freeze_frames=[FreezeFrame(
            dtc="P0300", rpm=1640.0, engine_load_pct=72.1, coolant_temp_f=188.0,
            speed_mph=38.0, stft_bank1=7.0, ltft_bank1=7.4,
        )],
        mode06=[Mode06Test(
            mid="0x21", tid="0x80", name="Catalyst Monitor Bank 1 Switch Ratio",
            value=1.34, max_limit=0.75, units="ratio", passed=False,
        )],
        mileage=171_200,
        capability=CapabilityProfile(**FULL_CAPABILITY),
        is_mock=True, fixture_name="silverado-2014-p0420-p0300-secondary",
    ),
)

# --- 5. Bank-specific lean fault on a V8 -------------------------------------
_register(
    "bmw-550i-2013-p0171-bank-specific",
    "2013 BMW 550i 4.4L twin-turbo V8, P0171 with one bank lean and the other "
    "normal. Tests the bank-asymmetry rule, which rules out shared components.",
    _vehicle(2013, "BMW", "550i", "4.4L V8 Twin-Turbo", 4.4, 8, "8-Speed Automatic", "RWD",
             turbo=True, hp="445"),
    "Base",
    OBDSnapshot(
        dtc_codes=[DTCCode(code="P0171", description="System Too Lean (Bank 1)")],
        rpm=684.0, speed_mph=0.0, coolant_temp_f=203.0, engine_load_pct=19.0,
        intake_air_temp_f=102.0, control_module_voltage=14.3,
        fuel_trims=[
            FuelTrim(condition="idle", stft_bank1=6.1, ltft_bank1=13.3, stft_bank2=1.2, ltft_bank2=2.1),
            FuelTrim(condition="loaded", stft_bank1=4.8, ltft_bank1=11.9, stft_bank2=0.9, ltft_bank2=1.8),
        ],
        freeze_frames=[FreezeFrame(
            dtc="P0171", rpm=702.0, engine_load_pct=18.4, coolant_temp_f=201.0,
            speed_mph=0.0, stft_bank1=6.6, ltft_bank1=13.1, stft_bank2=1.1, ltft_bank2=2.0,
        )],
        mileage=88_100,
        capability=CapabilityProfile(**FULL_CAPABILITY),
        is_mock=True, fixture_name="bmw-550i-2013-p0171-bank-specific",
    ),
)

# --- 6. Manufacturer-specific code, structural fallback only -----------------
_register(
    "escape-2013-p1131-mfg-code",
    "2013 Ford Escape 1.6L EcoBoost with a manufacturer-specific P1131. We hold no "
    "verified Ford definition, so this must resolve to the structural fallback and "
    "say so — never to a guessed meaning.",
    _vehicle(2013, "Ford", "Escape", "1.6L I4 EcoBoost", 1.6, 4, "6-Speed Automatic", "FWD",
             turbo=True, hp="178"),
    "SE",
    OBDSnapshot(
        dtc_codes=[
            DTCCode(code="P1131", description=""),
            DTCCode(code="P0133", description="O2 Sensor Circuit Slow Response (Bank 1 Sensor 1)"),
        ],
        rpm=771.0, speed_mph=0.0, coolant_temp_f=198.0, engine_load_pct=20.0,
        intake_air_temp_f=88.0, control_module_voltage=14.0,
        fuel_trims=[
            FuelTrim(condition="idle", stft_bank1=3.4, ltft_bank1=5.1),
            FuelTrim(condition="loaded", stft_bank1=2.2, ltft_bank1=4.8),
        ],
        freeze_frames=[FreezeFrame(
            dtc="P0133", rpm=1810.0, engine_load_pct=41.0, coolant_temp_f=197.0, speed_mph=36.0,
        )],
        mileage=104_600,
        capability=CapabilityProfile(**FULL_CAPABILITY),
        is_mock=True, fixture_name="escape-2013-p1131-mfg-code",
    ),
)

# --- 7. THE ABSTENTION CASE: vehicle reports almost nothing -------------------
_register(
    "sonata-2011-p0171-no-capability",
    "2011 Hyundai Sonata, P0171 on a vehicle that cannot report fuel trims, freeze "
    "frame, or Mode 06. The rules must ABSTAIN and the response must say what could "
    "not be seen. This is the fixture that proves missing data is never filled in.",
    _vehicle(2011, "Hyundai", "Sonata", "2.4L I4", 2.4, 4, "6-Speed Automatic", "FWD", hp="198"),
    "GLS",
    OBDSnapshot(
        dtc_codes=[DTCCode(code="P0171", description="System Too Lean (Bank 1)")],
        rpm=688.0, speed_mph=0.0, coolant_temp_f=187.0,
        engine_load_pct=None, intake_air_temp_f=None, maf_rate_gs=None,
        fuel_trims=[], freeze_frames=[], mode06=[],
        mileage=156_000,
        capability=CapabilityProfile(
            protocol="ISO 15765-4 (CAN 11/500)",
            freeze_frame_available=False,
            mode06_available=False,
            pending_codes_available=False,
            permanent_codes_available=False,
            fuel_trim_available=False,
            unsupported_pids=["06", "07", "08", "09", "0A"],
            limitations=[
                "This vehicle did not return fuel trim data, so the fuel mixture "
                "could not be assessed.",
                "No freeze frame was stored, so the conditions when the fault "
                "occurred are unknown.",
            ],
        ),
        is_mock=True, fixture_name="sonata-2011-p0171-no-capability",
    ),
)

# --- 8. EVAP small leak ------------------------------------------------------
_register(
    "civic-2008-p0442-evap",
    "2008 Honda Civic 1.8L, P0442 small evaporative leak. Low-severity case — the "
    "response should not overstate urgency.",
    _vehicle(2008, "Honda", "Civic", "1.8L I4", 1.8, 4, "5-Speed Automatic", "FWD", hp="140"),
    "LX",
    OBDSnapshot(
        dtc_codes=[DTCCode(code="P0442", description="EVAP System Leak Detected (Small Leak)")],
        rpm=742.0, speed_mph=0.0, coolant_temp_f=191.0, engine_load_pct=17.0,
        intake_air_temp_f=77.0, control_module_voltage=14.2,
        fuel_trims=[
            FuelTrim(condition="idle", stft_bank1=1.1, ltft_bank1=2.0),
            FuelTrim(condition="loaded", stft_bank1=0.6, ltft_bank1=1.7),
        ],
        freeze_frames=[FreezeFrame(
            dtc="P0442", rpm=1450.0, engine_load_pct=28.0, coolant_temp_f=190.0, speed_mph=32.0,
        )],
        mileage=133_700,
        capability=CapabilityProfile(**FULL_CAPABILITY),
        is_mock=True, fixture_name="civic-2008-p0442-evap",
    ),
)

# --- 9. Clean scan -----------------------------------------------------------
_register(
    "rav4-2018-clean",
    "2018 Toyota RAV4, no codes. Confirms the no-codes path does not invent issues.",
    _vehicle(2018, "Toyota", "RAV4", "2.5L I4", 2.5, 4, "6-Speed Automatic", "AWD", hp="176"),
    "XLE",
    OBDSnapshot(
        dtc_codes=[],
        rpm=698.0, speed_mph=0.0, coolant_temp_f=192.0, engine_load_pct=15.0,
        intake_air_temp_f=81.0, control_module_voltage=14.1,
        fuel_trims=[FuelTrim(condition="idle", stft_bank1=0.8, ltft_bank1=1.6)],
        mileage=47_300,
        capability=CapabilityProfile(**FULL_CAPABILITY),
        is_mock=True, fixture_name="rav4-2018-clean",
    ),
)


# --- 10. Hard case: multi-system fault on a twin-turbo V8 --------------------
# Deliberately difficult. Six codes across four systems, where the naive reading
# of each code in isolation leads somewhere different from the reading of all of
# them together:
#   - bank 1 lean, bank 2 clean            -> not a shared component
#   - bank 1 leaner under LOAD than idle   -> not a vacuum leak (those fade)
#   - misfires only on bank 1 cylinders    -> consistent with the lean bank
#   - an O2 code the trims corroborate     -> the sensor is telling the truth
#   - P052E and a P1xxx with no definition -> must be named, never guessed
# The trap is replacing the oxygen sensor, or chasing a vacuum leak that the
# load behaviour rules out.
_register(
    "m6-2014-bank1-lean-misfire-hard",
    "2014 BMW M6 4.4L twin-turbo V8. Six codes across four systems: bank 1 lean and "
    "getting worse under boost, misfires confined to bank 1 cylinders, an oxygen "
    "sensor code the fuel trims corroborate, plus a crankcase-ventilation code and a "
    "manufacturer-specific code with no verified definition.",
    _vehicle(2014, "BMW", "M6", "4.4L V8 Twin-Turbo", 4.4, 8, "7-Speed M-DCT", "RWD",
             turbo=True, hp="560"),
    "Base",
    OBDSnapshot(
        dtc_codes=[
            DTCCode(code="P0171", description="System Too Lean (Bank 1)"),
            DTCCode(code="P0300", description="Random/Multiple Cylinder Misfire Detected"),
            DTCCode(code="P0302", description="Cylinder 2 Misfire Detected"),
            DTCCode(code="P0304", description="Cylinder 4 Misfire Detected"),
            DTCCode(code="P0133", description="O2 Sensor Circuit Slow Response (Bank 1 Sensor 1)"),
            DTCCode(code="P052E", description=""),
            DTCCode(code="P1497", description=""),
        ],
        pending_codes=[DTCCode(code="P0301", description="", status="pending")],
        permanent_codes=[DTCCode(code="P0300", description="", status="permanent")],
        rpm=742.0, speed_mph=0.0, coolant_temp_f=208.0, engine_load_pct=22.0,
        intake_air_temp_f=104.0, maf_rate_gs=6.8, control_module_voltage=14.2,
        fuel_trims=[
            # Bank 1 is lean and gets WORSE under load — the opposite of a vacuum
            # leak, which is diluted as airflow rises. Bank 2 is clean throughout.
            FuelTrim(condition="idle", stft_bank1=6.4, ltft_bank1=12.1,
                     stft_bank2=1.1, ltft_bank2=1.9),
            FuelTrim(condition="loaded", stft_bank1=8.2, ltft_bank1=14.6,
                     stft_bank2=0.8, ltft_bank2=2.2),
        ],
        freeze_frames=[
            FreezeFrame(
                dtc="P0300", rpm=3448.0, engine_load_pct=84.2, coolant_temp_f=207.0,
                speed_mph=62.0, intake_air_temp_f=118.0, maf_rate_gs=71.4,
                stft_bank1=8.5, ltft_bank1=14.2, stft_bank2=0.9, ltft_bank2=2.1,
            ),
            FreezeFrame(
                dtc="P0171", rpm=3390.0, engine_load_pct=81.0, coolant_temp_f=206.0,
                speed_mph=59.0, intake_air_temp_f=116.0,
                stft_bank1=8.1, ltft_bank1=14.4, stft_bank2=1.0, ltft_bank2=2.0,
            ),
        ],
        mode06=[
            Mode06Test(mid="0x21", tid="0x80", name="Catalyst Monitor Bank 1 Switch Ratio",
                       value=0.44, max_limit=0.75, units="ratio", passed=True),
            Mode06Test(mid="0x22", tid="0x80", name="Catalyst Monitor Bank 2 Switch Ratio",
                       value=0.41, max_limit=0.75, units="ratio", passed=True),
            Mode06Test(mid="0xA2", tid="0x0B", name="Misfire Cylinder 2 Data",
                       value=187.0, max_limit=100.0, units="counts", passed=False),
            Mode06Test(mid="0xA4", tid="0x0B", name="Misfire Cylinder 4 Data",
                       value=142.0, max_limit=100.0, units="counts", passed=False),
        ],
        mileage=78_400,
        capability=CapabilityProfile(**FULL_CAPABILITY),
        is_mock=True, fixture_name="m6-2014-bank1-lean-misfire-hard",
    ),
)


# --- 11. CAUTION case: severe lean trim, no misfire (synthetic) --------------
# Added for the safety verdict. The only fixture whose verdict is CAUTION: total
# trim past the severe threshold with no misfire, no overheat, nothing at a
# manufacturer limit. Like every fixture it is is_mock=True and cannot reach
# research_scans.
_register(
    "tacoma-2009-p0171-severe-trim-synthetic",
    "2009 Toyota Tacoma 2.7L, P0171 with total fuel trim past the severe threshold "
    "at idle and under load. Synthetic CAUTION case for the safety verdict: the "
    "engine computer is near the end of its fuel authority, but nothing here "
    "warrants a stop-driving verdict.",
    _vehicle(2009, "Toyota", "Tacoma", "2.7L I4", 2.7, 4, "5-Speed Manual", "RWD", hp="159"),
    "Base",
    OBDSnapshot(
        dtc_codes=[DTCCode(code="P0171", description="System Too Lean (Bank 1)")],
        rpm=748.0, speed_mph=0.0, coolant_temp_f=193.0, engine_load_pct=19.0,
        intake_air_temp_f=83.0, maf_rate_gs=3.4, control_module_voltage=14.0,
        fuel_trims=[
            FuelTrim(condition="idle", stft_bank1=7.8, ltft_bank1=19.5),
            FuelTrim(condition="loaded", stft_bank1=6.1, ltft_bank1=18.9),
        ],
        freeze_frames=[FreezeFrame(
            dtc="P0171", rpm=2210.0, engine_load_pct=44.0, coolant_temp_f=191.0,
            speed_mph=43.0, intake_air_temp_f=85.0, stft_bank1=6.4, ltft_bank1=19.1,
        )],
        mileage=164_300,
        capability=CapabilityProfile(**FULL_CAPABILITY),
        is_mock=True, fixture_name="tacoma-2009-p0171-severe-trim-synthetic",
    ),
)


# --- Replay-validity pilot: three real cars, synthetic clean payloads --------
# 2026-08-22. These replicate the researcher's physically accessible cars for
# the synthetic arm of the replay-validity pilot (synthetic payload now, real
# capture later the same day, compare). Engine, trim, transmission, and mileage
# were NOT known at authoring time and are deliberately unknown/null — never
# guessed. PID values are invented idle readings, as in every fixture. The
# V70 capability profile encodes a PREDICTION about what a pre-CAN 2004 vehicle
# reports; prediction error against the real capture is a measured outcome of
# the pilot, not a bug.
def _register_replay_clean(name, year, make, model, drive, capability=None, limitations=(),
                           fuel_trims=None, coolant=191.0, rpm=735.0,
                           engine="", displacement=None, cylinders=None, turbo=False):
    _register(
        name,
        f"{year} {make} {model}, no codes. Synthetic arm of the 2026-08-22 "
        "replay-validity pilot. Unknown vehicle facts are blank, not guessed.",
        {
            "year": str(year), "make": make, "model": model,
            "full_name": f"{year} {make} {model}",
            "engine": engine, "displacement": displacement, "cylinders": cylinders,
            "transmission": "", "drive": drive, "fuel_type": "Gasoline",
            "turbocharged": turbo, "supercharged": False, "horsepower": "",
        },
        "",
        OBDSnapshot(
            dtc_codes=[],
            rpm=rpm, speed_mph=0.0, coolant_temp_f=coolant, engine_load_pct=18.0,
            intake_air_temp_f=86.0, control_module_voltage=14.0,
            fuel_trims=fuel_trims if fuel_trims is not None else
                [FuelTrim(condition="idle", stft_bank1=1.2, ltft_bank1=2.1)],
            mileage=None,
            capability=capability,
            is_mock=True, fixture_name=name,
        ),
    )


_register_replay_clean(
    "landcruiser-2014-clean-replay", 2014, "Toyota", "Land Cruiser", "",
    capability=CapabilityProfile(**FULL_CAPABILITY),
)
_register_replay_clean(
    "audi-a4-2015-clean-replay", 2015, "Audi", "A4 quattro", "AWD",
    capability=CapabilityProfile(**FULL_CAPABILITY),
)
# V70 facts supplied by the owner 2026-08-22: 2.5T (2.5L I5 turbo), FWD.
_register_replay_clean(
    "volvo-v70-2004-clean-replay", 2004, "Volvo", "V70", "FWD",
    engine="2.5L I5 Turbo (2.5T)", displacement=2.5, cylinders=5, turbo=True,
    capability=CapabilityProfile(
        protocol="ISO 9141-2 / KWP2000 (predicted, pre-CAN era)",
        freeze_frame_available=True,
        mode06_available=False,
        pending_codes_available=True,
        permanent_codes_available=False,
        fuel_trim_available=True,
        limitations=[
            "Predicted pre-CAN capability: Mode 06 monitor results and permanent "
            "codes (Mode 0A) are not expected on this 2004 vehicle.",
        ],
    ),
)


def list_scenarios() -> list:
    return [
        {"name": s["name"], "description": s["description"],
         "vehicle": s["vehicle"]["full_name"], "trim": s["trim"],
         "codes": [c.code for c in s["snapshot"].dtc_codes]}
        for s in SCENARIOS.values()
    ]


def get_scenario(name: str) -> dict:
    """Return a deep copy so a caller can never mutate the fixture in place."""
    s = SCENARIOS.get(name)
    if not s:
        return None
    return {
        "name": s["name"],
        "description": s["description"],
        "vehicle": dict(s["vehicle"]),
        "trim": s["trim"],
        "snapshot": s["snapshot"].model_copy(deep=True),
    }

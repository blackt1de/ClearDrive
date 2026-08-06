"""Wire formats for OBD capture.

Payload v2 adds the evidence a mechanic actually uses — freeze frame, fuel
trims, on-board monitor results, pending/permanent codes, mileage — plus a
capability profile recording what the vehicle could NOT report.

Every new field is optional with a null default, so `OBDSnapshot(...)` calls
that predate v2 (obd_reader.py) keep working unchanged.

The capability profile is not a nicety. Without it, "fuel trims are normal"
and "this vehicle cannot report fuel trims" are the same empty field, and a
rule that abstains on missing data cannot tell the difference between a
vehicle that is healthy and one that is silent.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class DTCCode(BaseModel):
    code: str
    description: str
    # "confirmed" (mode 03) | "pending" (mode 07) | "permanent" (mode 0A)
    status: str = "confirmed"


class FuelTrim(BaseModel):
    """Short- and long-term fuel trim, percent. Positive = ECU adding fuel.

    Captured at a stated engine condition, because the same trim numbers mean
    different things at idle and under load. `condition` is one of
    "idle" | "loaded" | "unknown".
    """
    condition: str = "unknown"
    stft_bank1: Optional[float] = None
    ltft_bank1: Optional[float] = None
    stft_bank2: Optional[float] = None
    ltft_bank2: Optional[float] = None


class FreezeFrame(BaseModel):
    """Conditions recorded by the ECU at the instant a DTC set.

    This is the single most diagnostic piece of generic OBD-II data: a misfire
    that set at 2,800 RPM under load is a different fault from one that set at
    700 RPM cold, and the code alone cannot tell them apart.
    """
    dtc: str
    rpm: Optional[float] = None
    engine_load_pct: Optional[float] = None
    coolant_temp_f: Optional[float] = None
    speed_mph: Optional[float] = None
    intake_air_temp_f: Optional[float] = None
    maf_rate_gs: Optional[float] = None
    fuel_pressure_psi: Optional[float] = None
    stft_bank1: Optional[float] = None
    ltft_bank1: Optional[float] = None
    stft_bank2: Optional[float] = None
    ltft_bank2: Optional[float] = None


class Mode06Test(BaseModel):
    """One on-board monitor test result with the limits it was judged against.

    Mode 06 is what separates "your catalyst code is marginal and may clear"
    from "your converter is dead." Standard MIDs come from SAE J1979; many
    MIDs are manufacturer-defined, so `name` may be unavailable even when the
    numbers are valid.
    """
    mid: str
    tid: Optional[str] = None
    name: Optional[str] = None
    value: Optional[float] = None
    min_limit: Optional[float] = None
    max_limit: Optional[float] = None
    units: Optional[str] = None
    passed: Optional[bool] = None


class CapabilityProfile(BaseModel):
    """What this vehicle could and could not report during capture.

    `unsupported_pids` means probed and refused — different from a PID we never
    asked for, which appears in neither list. `limitations` carries
    human-readable strings for anything that is not a simple PID, such as a
    module that did not answer or a gateway that refused the request.
    """
    protocol: Optional[str] = None
    supported_pids: list[str] = Field(default_factory=list)
    unsupported_pids: list[str] = Field(default_factory=list)
    freeze_frame_available: Optional[bool] = None
    mode06_available: Optional[bool] = None
    pending_codes_available: Optional[bool] = None
    permanent_codes_available: Optional[bool] = None
    fuel_trim_available: Optional[bool] = None
    limitations: list[str] = Field(default_factory=list)

    def can(self, feature: str) -> bool:
        """True only when the capability is affirmatively known to be present."""
        return getattr(self, f"{feature}_available", None) is True

    def explain_missing(self, feature: str) -> str:
        state = getattr(self, f"{feature}_available", None)
        label = feature.replace("_", " ")
        if state is False:
            return f"vehicle does not support {label}"
        return f"{label} was not captured"


class OBDSnapshot(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.now)
    dtc_codes: list[DTCCode] = Field(default_factory=list)

    # Live values. None means not reported — never substitute a plausible number.
    rpm: Optional[float] = None
    speed_mph: Optional[float] = None
    coolant_temp_f: Optional[float] = None
    engine_load_pct: Optional[float] = None
    intake_air_temp_f: Optional[float] = None
    maf_rate_gs: Optional[float] = None
    fuel_pressure_psi: Optional[float] = None
    control_module_voltage: Optional[float] = None

    # v2 additions
    pending_codes: list[DTCCode] = Field(default_factory=list)
    permanent_codes: list[DTCCode] = Field(default_factory=list)
    fuel_trims: list[FuelTrim] = Field(default_factory=list)
    freeze_frames: list[FreezeFrame] = Field(default_factory=list)
    mode06: list[Mode06Test] = Field(default_factory=list)
    # Odometer is not available over generic OBD-II on most vehicles; this is
    # user-entered. Distance-since-codes-cleared is a different PID and is not
    # mileage — do not conflate them.
    mileage: Optional[int] = None
    capability: CapabilityProfile = Field(default_factory=CapabilityProfile)

    is_mock: bool = True
    # Set for synthetic fixtures so a scenario can never be mistaken for a
    # capture in logs, in the research table, or in a training corpus.
    fixture_name: Optional[str] = None

    def trims_at(self, condition: str) -> Optional[FuelTrim]:
        for t in self.fuel_trims:
            if t.condition == condition:
                return t
        return None

    def freeze_frame_for(self, code: str) -> Optional[FreezeFrame]:
        for f in self.freeze_frames:
            if f.dtc.upper() == code.upper():
                return f
        return None

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class DTCCode(BaseModel):
    code: str
    description: str


class OBDSnapshot(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.now)
    dtc_codes: list[DTCCode] = Field(default_factory=list)
    rpm: Optional[float] = None
    speed_mph: Optional[float] = None
    coolant_temp_f: Optional[float] = None
    is_mock: bool = True
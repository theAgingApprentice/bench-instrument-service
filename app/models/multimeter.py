from typing import Literal, Optional

from pydantic import BaseModel, Field

MeasurementMode = Literal[
    "VOLT:DC", "VOLT:AC", "CURR:DC", "CURR:AC",
    "RES", "FRES", "FREQ", "CONT", "DIOD", "CAP",
]


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class LogReading(BaseModel):
    timestamp: str
    value: float


class LogStatistics(BaseModel):
    min: float
    max: float
    mean: float
    std_dev: float


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class MultimeterMeasureRequest(BaseModel):
    mode: MeasurementMode
    range: str = "AUTO"


class MultimeterLogRequest(BaseModel):
    mode: MeasurementMode
    duration_seconds: float = Field(..., gt=0, le=3600)
    interval_seconds: float = Field(default=1.0, gt=0)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class MultimeterStatusResponse(BaseModel):
    mode: str
    range: str
    resolution: str


class MeasurementResult(BaseModel):
    timestamp: str
    mode: str
    value: float
    unit: str


class MultimeterLogResponse(BaseModel):
    log_id: Optional[str] = None  # populated by the router; used for CSV download
    mode: str
    unit: str
    count: int
    readings: list[LogReading]
    statistics: LogStatistics

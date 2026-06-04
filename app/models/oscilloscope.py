from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class OscilloscopeChannelStatus(BaseModel):
    enabled: bool
    coupling: str
    scale: float
    offset: float
    probe: int


class OscilloscopeTimebaseStatus(BaseModel):
    scale: float
    offset: float


class WaveformData(BaseModel):
    enabled: bool
    sample_rate: float
    timebase: float
    volts_per_div: float
    offset: float
    probe_ratio: int
    num_points: int
    time_array: list[float]
    voltage_array: list[float]


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class OscilloscopeConfigureRequest(BaseModel):
    channel: int = Field(..., ge=1, le=2)
    coupling: Optional[str] = None       # "DC" | "AC" | "GND"
    scale: Optional[float] = None        # V/div
    offset: Optional[float] = None       # V
    probe: Optional[int] = None          # attenuation ratio e.g. 10
    timebase_scale: Optional[float] = None  # s/div


class OscilloscopeCaptureRequest(BaseModel):
    channels: list[int] = Field(default=[1], min_length=1)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class OscilloscopeStatusResponse(BaseModel):
    channel_1: OscilloscopeChannelStatus
    channel_2: OscilloscopeChannelStatus
    timebase: OscilloscopeTimebaseStatus


class OscilloscopeCaptureResponse(BaseModel):
    timestamp: str
    channel_1: Optional[WaveformData] = None
    channel_2: Optional[WaveformData] = None

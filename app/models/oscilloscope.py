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


class TriggerStatus(BaseModel):
    source: int
    mode: str
    level: float
    slope: str


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

class TriggerConfigRequest(BaseModel):
    source: Optional[int] = None         # channel 1 or 2
    level: Optional[float] = None         # V
    slope: Optional[str] = None           # "POS" | "NEG" | "WINDOW"
    mode: Optional[str] = None            # "AUTO" | "NORM" | "SINGLE" | "STOP"


class ChannelConfigRequest(BaseModel):
    coupling: Optional[str] = None       # "DC" | "AC" | "GND"
    scale: Optional[float] = None        # V/div
    offset: Optional[float] = None       # V
    probe: Optional[int] = None          # attenuation ratio e.g. 10


class TimebaseConfigRequest(BaseModel):
    scale: Optional[float] = None        # s/div
    offset: Optional[float] = None       # s (trigger delay)


class OscilloscopeConfigureRequest(BaseModel):
    channel: int = Field(..., ge=1, le=2)
    channel_config: Optional[ChannelConfigRequest] = None
    timebase: Optional[TimebaseConfigRequest] = None
    trigger: Optional[TriggerConfigRequest] = None


class OscilloscopeCaptureRequest(BaseModel):
    channels: list[int] = Field(default=[1], min_length=1)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class OscilloscopeStatusResponse(BaseModel):
    channel_1: OscilloscopeChannelStatus
    channel_2: OscilloscopeChannelStatus
    timebase: OscilloscopeTimebaseStatus
    trigger: TriggerStatus


class OscilloscopeCaptureResponse(BaseModel):
    timestamp: str
    channel_1: Optional[WaveformData] = None
    channel_2: Optional[WaveformData] = None

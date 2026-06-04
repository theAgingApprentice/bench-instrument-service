from typing import Literal, Optional

from pydantic import BaseModel, Field

WaveformType = Literal["SINE", "SQUARE", "RAMP", "PULSE", "NOISE", "ARB", "DC"]


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class SignalGeneratorChannelStatus(BaseModel):
    output_enabled: bool
    waveform: str
    frequency: float
    amplitude: float
    offset: float
    duty_cycle: float
    phase: float


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class SignalGeneratorConfigureRequest(BaseModel):
    channel: int = Field(..., ge=1, le=2)
    waveform: Optional[WaveformType] = None
    frequency: Optional[float] = Field(default=None, gt=0)
    amplitude: Optional[float] = Field(default=None, gt=0)
    offset: Optional[float] = None
    duty_cycle: Optional[float] = Field(default=None, ge=0, le=100)
    phase: Optional[float] = Field(default=None, ge=0, lt=360)
    output: Optional[bool] = None


class SignalGeneratorOutputRequest(BaseModel):
    channel: int = Field(..., ge=1, le=2)
    enabled: bool


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class SignalGeneratorStatusResponse(BaseModel):
    channel_1: SignalGeneratorChannelStatus
    channel_2: SignalGeneratorChannelStatus

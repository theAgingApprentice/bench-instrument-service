from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class PowerSupplyChannelStatus(BaseModel):
    output_enabled: bool
    voltage_set: float
    current_limit: float
    voltage_actual: float
    current_actual: float
    power_actual: float


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class PowerSupplyConfigureRequest(BaseModel):
    channel: int = Field(..., ge=1, le=3)
    voltage: float = Field(..., ge=0)
    current_limit: float = Field(..., gt=0)


class PowerSupplyOutputRequest(BaseModel):
    channel: int = Field(..., ge=1, le=3)
    enabled: bool


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class PowerSupplyStatusResponse(BaseModel):
    channel_1: PowerSupplyChannelStatus
    channel_2: PowerSupplyChannelStatus
    channel_3: PowerSupplyChannelStatus

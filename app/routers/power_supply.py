from fastapi import APIRouter, Depends

from app.dependencies import get_instrument_registry, instrument_session
from app.models.power_supply import (
    PowerSupplyChannelStatus,
    PowerSupplyConfigureRequest,
    PowerSupplyOutputRequest,
    PowerSupplyStatusResponse,
)
from app.services.instrument_registry import InstrumentRegistry

router = APIRouter(prefix="/v1/power-supply", tags=["Power Supply"])


@router.get("/status", response_model=PowerSupplyStatusResponse)
def get_status(registry: InstrumentRegistry = Depends(get_instrument_registry)):
    """Return actual measured values and set points for all three channels."""
    with instrument_session(registry, "power_supply") as driver:
        raw = driver.get_status()
    return PowerSupplyStatusResponse(
        channel_1=PowerSupplyChannelStatus(**raw["channel_1"]),
        channel_2=PowerSupplyChannelStatus(**raw["channel_2"]),
        channel_3=PowerSupplyChannelStatus(**raw["channel_3"]),
    )


@router.post("/configure")
def configure(
    req: PowerSupplyConfigureRequest,
    registry: InstrumentRegistry = Depends(get_instrument_registry),
):
    """Set voltage and current limit for one channel."""
    with instrument_session(registry, "power_supply") as driver:
        driver.configure_channel(req.channel, req.voltage, req.current_limit)
    return {"ok": True}


@router.post("/output")
def set_output(
    req: PowerSupplyOutputRequest,
    registry: InstrumentRegistry = Depends(get_instrument_registry),
):
    """Enable or disable one channel's output."""
    with instrument_session(registry, "power_supply") as driver:
        driver.set_output(req.channel, req.enabled)
    return {"ok": True}


@router.post("/all-off")
def all_off(registry: InstrumentRegistry = Depends(get_instrument_registry)):
    """Disable all three channel outputs immediately."""
    with instrument_session(registry, "power_supply") as driver:
        driver.all_off()
    return {"ok": True}

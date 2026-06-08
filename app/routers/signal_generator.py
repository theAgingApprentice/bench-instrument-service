from fastapi import APIRouter, Depends

from app.dependencies import check_session, get_instrument_registry, instrument_session
from app.models.signal_generator import (
    SignalGeneratorChannelStatus,
    SignalGeneratorConfigureRequest,
    SignalGeneratorOutputRequest,
    SignalGeneratorStatusResponse,
)
from app.services.instrument_registry import InstrumentRegistry

router = APIRouter(
    prefix="/v1/signal-generator",
    tags=["Signal Generator"],
    dependencies=[Depends(check_session)],
)


@router.get("/status", response_model=SignalGeneratorStatusResponse)
def get_status(registry: InstrumentRegistry = Depends(get_instrument_registry)):
    """Return current output configuration for both channels."""
    with instrument_session(registry, "signal_generator") as driver:
        raw = driver.get_status()
    return SignalGeneratorStatusResponse(
        channel_1=SignalGeneratorChannelStatus(**raw["channel_1"]),
        channel_2=SignalGeneratorChannelStatus(**raw["channel_2"]),
    )


@router.post("/configure")
def configure(
    req: SignalGeneratorConfigureRequest,
    registry: InstrumentRegistry = Depends(get_instrument_registry),
):
    """Configure one channel. Only supplied fields are applied."""
    with instrument_session(registry, "signal_generator") as driver:
        driver.configure_channel(
            channel=req.channel,
            waveform=req.waveform,
            frequency=req.frequency,
            amplitude=req.amplitude,
            offset=req.offset,
            duty_cycle=req.duty_cycle,
            phase=req.phase,
            output=req.output,
        )
    return {"ok": True}


@router.post("/output")
def set_output(
    req: SignalGeneratorOutputRequest,
    registry: InstrumentRegistry = Depends(get_instrument_registry),
):
    """Enable or disable channel output without changing other settings."""
    with instrument_session(registry, "signal_generator") as driver:
        driver.set_output(req.channel, req.enabled)
    return {"ok": True}

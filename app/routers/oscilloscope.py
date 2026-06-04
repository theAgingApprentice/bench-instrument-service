from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.dependencies import get_instrument_registry, instrument_session
from app.models.oscilloscope import (
    OscilloscopeCaptureRequest,
    OscilloscopeCaptureResponse,
    OscilloscopeChannelStatus,
    OscilloscopeConfigureRequest,
    OscilloscopeStatusResponse,
    OscilloscopeTimebaseStatus,
    WaveformData,
)
from app.services.instrument_registry import InstrumentRegistry

router = APIRouter(prefix="/v1/oscilloscope", tags=["Oscilloscope"])


@router.get("/status", response_model=OscilloscopeStatusResponse)
def get_status(registry: InstrumentRegistry = Depends(get_instrument_registry)):
    """Return channel settings for both channels plus timebase."""
    with instrument_session(registry, "oscilloscope") as driver:
        raw = driver.get_status()
    return OscilloscopeStatusResponse(
        channel_1=OscilloscopeChannelStatus(**raw["channel_1"]),
        channel_2=OscilloscopeChannelStatus(**raw["channel_2"]),
        timebase=OscilloscopeTimebaseStatus(**raw["timebase"]),
    )


@router.post("/configure")
def configure(
    req: OscilloscopeConfigureRequest,
    registry: InstrumentRegistry = Depends(get_instrument_registry),
):
    """Set channel and/or timebase parameters. Only supplied fields are applied."""
    with instrument_session(registry, "oscilloscope") as driver:
        driver.configure_channel(
            channel=req.channel,
            coupling=req.coupling,
            scale=req.scale,
            offset=req.offset,
            probe=req.probe,
        )
        if req.timebase_scale is not None:
            driver.configure_timebase(scale=req.timebase_scale)
    return {"ok": True}


@router.post("/capture", response_model=OscilloscopeCaptureResponse)
def capture(
    req: OscilloscopeCaptureRequest,
    registry: InstrumentRegistry = Depends(get_instrument_registry),
):
    """Capture waveform data from one or both channels."""
    with instrument_session(registry, "oscilloscope") as driver:
        ch1_data = driver.capture_waveform(1) if 1 in req.channels else None
        ch2_data = driver.capture_waveform(2) if 2 in req.channels else None

    return OscilloscopeCaptureResponse(
        timestamp=datetime.now(timezone.utc).isoformat(),
        channel_1=WaveformData(**ch1_data) if ch1_data else None,
        channel_2=WaveformData(**ch2_data) if ch2_data else None,
    )


@router.post("/screenshot")
def screenshot(registry: InstrumentRegistry = Depends(get_instrument_registry)):
    """Capture a screenshot from the oscilloscope display. Returns BMP image bytes."""
    with instrument_session(registry, "oscilloscope") as driver:
        raw = driver.screenshot()
    return Response(content=raw, media_type="image/bmp")

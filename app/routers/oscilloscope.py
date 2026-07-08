import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.dependencies import check_session, get_instrument_registry, instrument_session
from app.models.oscilloscope import (
    OscilloscopeCaptureRequest,
    OscilloscopeCaptureResponse,
    OscilloscopeChannelStatus,
    OscilloscopeConfigureRequest,
    OscilloscopeStatusResponse,
    OscilloscopeTimebaseStatus,
    TriggerStatus,
    WaveformData,
)
from app.services.instrument_registry import InstrumentRegistry

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v1/oscilloscope",
    tags=["Oscilloscope"],
    dependencies=[Depends(check_session)],
)


@router.get("/status", response_model=OscilloscopeStatusResponse)
def get_status(registry: InstrumentRegistry = Depends(get_instrument_registry)):
    """Return channel settings for both channels plus timebase."""
    with instrument_session(registry, "oscilloscope") as driver:
        raw = driver.get_status()
    return OscilloscopeStatusResponse(
        channel_1=OscilloscopeChannelStatus(**raw["channel_1"]),
        channel_2=OscilloscopeChannelStatus(**raw["channel_2"]),
        timebase=OscilloscopeTimebaseStatus(**raw["timebase"]),
        trigger=TriggerStatus(**raw["trigger"]),
    )


@router.post("/configure")
def configure(
    req: OscilloscopeConfigureRequest,
    registry: InstrumentRegistry = Depends(get_instrument_registry),
):
    """Set channel, timebase, and/or trigger parameters. Only supplied fields are applied."""
    with instrument_session(registry, "oscilloscope") as driver:
        if req.channel_config is not None:
            driver.configure_channel(
                channel=req.channel,
                coupling=req.channel_config.coupling,
                scale=req.channel_config.scale,
                offset=req.channel_config.offset,
                probe=req.channel_config.probe,
            )
        if req.timebase is not None:
            driver.configure_timebase(
                scale=req.timebase.scale,
                offset=req.timebase.offset,
            )
        if req.trigger is not None:
            driver.configure_trigger(
                source=req.trigger.source,
                level=req.trigger.level,
                slope=req.trigger.slope,
                mode=req.trigger.mode,
            )
        if req.timebase is not None:
            # A timebase change invalidates whatever the scope was previously
            # acquiring. /configure and /capture are separate HTTP requests, each
            # with its own connect/disconnect cycle, so a /capture issued right
            # after this /configure can call TRMD STOP before the first sweep
            # under the new settings completes, freezing an empty acquisition
            # buffer. Sleep for one full sweep (14 horizontal divisions on the
            # SDS1202X-E) plus margin before releasing the connection.
            settle_seconds = req.timebase.scale * 14 + 0.5
            logger.info(
                "timebase changed, waiting %.3fs for acquisition to settle",
                settle_seconds,
            )
            time.sleep(settle_seconds)
    return {"ok": True}


@router.post("/capture", response_model=OscilloscopeCaptureResponse)
def capture(
    req: OscilloscopeCaptureRequest,
    registry: InstrumentRegistry = Depends(get_instrument_registry),
):
    """Capture waveform data from one or both channels."""
    with instrument_session(registry, "oscilloscope") as driver:
        data = driver.capture_waveforms(req.channels)

    return OscilloscopeCaptureResponse(
        timestamp=datetime.now(timezone.utc).isoformat(),
        channel_1=WaveformData(**data[1]) if 1 in data else None,
        channel_2=WaveformData(**data[2]) if 2 in data else None,
    )


@router.post("/screenshot")
def screenshot(registry: InstrumentRegistry = Depends(get_instrument_registry)):
    """Capture a screenshot from the oscilloscope display. Returns BMP image bytes."""
    with instrument_session(registry, "oscilloscope") as driver:
        raw = driver.screenshot()
    return Response(content=raw, media_type="image/bmp")

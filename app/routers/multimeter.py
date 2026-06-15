import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app.dependencies import check_session, get_instrument_registry, instrument_session
from app.models.multimeter import (
    LogReading,
    LogStatistics,
    MeasurementResult,
    MultimeterLogRequest,
    MultimeterLogResponse,
    MultimeterMeasureRequest,
    MultimeterStatusResponse,
)
from app.services.instrument_registry import InstrumentRegistry

router = APIRouter(
    prefix="/v1/multimeter",
    tags=["Multimeter"],
    dependencies=[Depends(check_session)],
)

# In-memory log store — keyed by UUID, populated by POST /log.
# Survives for the lifetime of the process; not persisted across restarts.
_log_store: dict[str, MultimeterLogResponse] = {}


@router.get("/status", response_model=MultimeterStatusResponse)
def get_status(registry: InstrumentRegistry = Depends(get_instrument_registry)):
    """Return current measurement mode, range, and resolution."""
    with instrument_session(registry, "multimeter") as driver:
        raw = driver.get_status()
    return MultimeterStatusResponse(**raw)


@router.post("/measure", response_model=MeasurementResult)
def measure(
    req: MultimeterMeasureRequest,
    registry: InstrumentRegistry = Depends(get_instrument_registry),
):
    """Configure and take a single measurement."""
    with instrument_session(registry, "multimeter") as driver:
        raw = driver.measure(req.mode, req.range)
    return MeasurementResult(**raw)


@router.post("/log", response_model=MultimeterLogResponse)
def log_measurements(
    req: MultimeterLogRequest,
    registry: InstrumentRegistry = Depends(get_instrument_registry),
):
    """Take repeated measurements over a duration and return results with statistics.

    The response includes a log_id that can be used with GET /log/{log_id}/csv.
    Fires a measurement.log_complete webhook event on completion.
    """
    with instrument_session(registry, "multimeter") as driver:
        raw = driver.log_measurements(req.mode, req.duration_seconds, req.interval_seconds)
    log_id = str(uuid.uuid4())
    response = MultimeterLogResponse(
        log_id=log_id,
        mode=raw["mode"],
        unit=raw["unit"],
        count=raw["count"],
        readings=[LogReading(**r) for r in raw["readings"]],
        statistics=LogStatistics(**raw["statistics"]),
    )
    _log_store[log_id] = response
    from app.services.webhook_manager import webhook_manager
    webhook_manager.fire("measurement.log_complete", {
        "log_id": log_id,
        "mode": response.mode,
        "unit": response.unit,
        "count": response.count,
        "statistics": response.statistics.model_dump(),
    })
    return response


@router.get("/log/{log_id}/csv")
def get_log_csv(log_id: str):
    """Download a previous measurement log as CSV."""
    log = _log_store.get(log_id)
    if log is None:
        raise HTTPException(status_code=404, detail=f"Log '{log_id}' not found")

    lines = [f"timestamp,value ({log.unit})"]
    for reading in log.readings:
        lines.append(f"{reading.timestamp},{reading.value}")
    csv_content = "\n".join(lines) + "\n"

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="multimeter_log_{log_id}.csv"'},
    )

from fastapi import APIRouter, Depends

from app.dependencies import get_instrument_registry
from app.models.common import HealthResponse, InstrumentInfo
from app.services.instrument_registry import InstrumentRegistry

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse)
def get_health(registry: InstrumentRegistry = Depends(get_instrument_registry)):
    """Return service status, uptime, and reachability of all four instruments."""
    instruments = {
        name: InstrumentInfo(reachable=e.reachable, ip=e.ip, identity=e.identity)
        for name, e in registry.all_entries().items()
    }
    return HealthResponse(
        status=registry.health_status,
        uptime_seconds=registry.uptime_seconds,
        instruments=instruments,
    )

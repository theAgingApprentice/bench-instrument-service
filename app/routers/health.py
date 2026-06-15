from fastapi import APIRouter, Depends
from app.dependencies import get_instrument_registry
from app.models.common import HealthFullResponse, HealthResponse, InstrumentInfo, SessionInfo
from app.services.instrument_registry import InstrumentRegistry
from app.services.session_manager import session_manager

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


@router.get("/health/full", response_model=HealthFullResponse)
def get_health_full(registry: InstrumentRegistry = Depends(get_instrument_registry)):
    """Return service status, instrument reachability, and active session state.

    No authentication required — intended for the status dashboard polling loop.
    """
    instruments = {
        name: InstrumentInfo(reachable=e.reachable, ip=e.ip, identity=e.identity)
        for name, e in registry.all_entries().items()
    }
    current = session_manager.current
    session = None
    if current:
        session = SessionInfo(
            session_id=current.session_id,
            client_id=current.client_ip,
            expires_at=current.expires_at.isoformat(),
        )
    return HealthFullResponse(
        status=registry.health_status,
        uptime_seconds=registry.uptime_seconds,
        instruments=instruments,
        session=session,
    )

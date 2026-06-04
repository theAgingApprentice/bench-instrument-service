from fastapi import APIRouter, Depends

from app.dependencies import get_instrument_registry
from app.models.common import InstrumentInfo, InstrumentsResponse
from app.services.instrument_registry import InstrumentRegistry

router = APIRouter(prefix="/v1/instruments", tags=["Instruments"])


@router.get("", response_model=InstrumentsResponse)
def list_instruments(registry: InstrumentRegistry = Depends(get_instrument_registry)):
    """Return current instrument registry — IPs, identity strings, and availability."""
    return InstrumentsResponse(
        instruments={
            name: InstrumentInfo(reachable=e.reachable, ip=e.ip, identity=e.identity)
            for name, e in registry.all_entries().items()
        }
    )


@router.post("/discover", response_model=InstrumentsResponse)
def discover_instruments(registry: InstrumentRegistry = Depends(get_instrument_registry)):
    """Trigger an immediate probe of all instruments and return the refreshed registry."""
    registry.discover()
    return InstrumentsResponse(
        instruments={
            name: InstrumentInfo(reachable=e.reachable, ip=e.ip, identity=e.identity)
            for name, e in registry.all_entries().items()
        }
    )

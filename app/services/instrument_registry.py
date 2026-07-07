import logging
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class InstrumentEntry:
    """Live state for one instrument in the registry."""
    ip: str
    reachable: bool = False
    identity: Optional[str] = None


class InstrumentRegistry:
    """Tracks the four bench instruments — their IPs, reachability, and identity strings.

    Lifecycle:
        registry = InstrumentRegistry(settings)
        registry.discover()          # called on startup and by POST /v1/instruments/discover
        driver = registry.get_driver("oscilloscope")
    """

    def __init__(self, settings):
        self._start_time = time.monotonic()
        self._entries: dict[str, InstrumentEntry] = {
            "oscilloscope":     InstrumentEntry(ip=settings.oscilloscope_ip),
            "signal_generator": InstrumentEntry(ip=settings.signal_generator_ip),
            "multimeter":       InstrumentEntry(ip=settings.multimeter_ip),
            "power_supply":     InstrumentEntry(ip=settings.power_supply_ip),
        }
        self._drivers = _build_drivers(settings)

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover(self) -> None:
        """Probe every instrument and refresh reachability + identity."""
        for name, driver in self._drivers.items():
            entry = self._entries[name]
            reachable, identity = _probe(driver)
            entry.reachable = reachable
            entry.identity = identity
            logger.info(
                "instrument=%s ip=%s reachable=%s identity=%r",
                name, entry.ip, reachable, identity,
            )

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def get_driver(self, name: str):
        """Return the driver instance for the named instrument."""
        return self._drivers.get(name)

    def get_entry(self, name: str) -> Optional[InstrumentEntry]:
        return self._entries.get(name)

    def all_entries(self) -> dict[str, InstrumentEntry]:
        return dict(self._entries)

    @property
    def health_status(self) -> str:
        """'ok' if all instruments are reachable, 'degraded' otherwise."""
        return "ok" if all(e.reachable for e in self._entries.values()) else "degraded"

    @property
    def uptime_seconds(self) -> float:
        return time.monotonic() - self._start_time


# ---------------------------------------------------------------------------
# Module-level singleton — set by initialise() during FastAPI startup
# ---------------------------------------------------------------------------

_registry: Optional[InstrumentRegistry] = None


def initialise(settings) -> InstrumentRegistry:
    """Create and store the module-level registry singleton. Called once in main.py."""
    global _registry
    _registry = InstrumentRegistry(settings)
    return _registry


def get_registry() -> InstrumentRegistry:
    """Return the singleton. Raises if initialise() was never called."""
    if _registry is None:
        raise RuntimeError("InstrumentRegistry has not been initialised")
    return _registry


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_drivers(settings) -> dict:
    # Deferred imports keep startup fast and make mocking straightforward in tests.
    from app.drivers.oscilloscope_siglent_sds1202xe import OscilloscopeSiglentSDS1202XE
    from app.drivers.signal_generator_siglent_sdg2042x import SignalGeneratorSiglentSDG2042X
    from app.drivers.multimeter_siglent_sdm3055 import MultimeterSiglentSDM3055
    from app.drivers.power_supply_rigol_dp832 import PowerSupplyRigolDP832

    return {
        "oscilloscope":     OscilloscopeSiglentSDS1202XE(
                                settings.oscilloscope_ip, settings.scpi_timeout_ms),
        "signal_generator": SignalGeneratorSiglentSDG2042X(
                                settings.signal_generator_ip, settings.scpi_timeout_ms),
        "multimeter":       MultimeterSiglentSDM3055(
                                settings.multimeter_ip, settings.scpi_timeout_ms),
        "power_supply":     PowerSupplyRigolDP832(
                                settings.power_supply_ip, settings.scpi_timeout_ms),
    }


def _probe(driver) -> tuple[bool, Optional[str]]:
    """Open a connection, query *IDN?, close. Returns (reachable, identity)."""
    # Hold driver._lock for the whole connect/identify/disconnect span so this
    # background health-check poll (runs on the asyncio event loop thread via
    # main.py's 30s discover() task) can't disconnect/reconnect an instrument
    # while a request handler (FastAPI sync-route thread pool) is mid-operation
    # on it. Discovered via live diagnostic logging 7 July 2026 — see roadmap §4.7.
    with driver._lock:
        try:
            if driver.connect():
                identity = driver.identify().strip()
                return True, identity
        except Exception as exc:
            logger.debug("Probe failed for %s: %s", type(driver).__name__, exc)
        finally:
            try:
                driver.disconnect()
            except Exception:
                pass
    return False, None

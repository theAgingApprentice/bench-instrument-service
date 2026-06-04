"""Pytest configuration and shared fixtures.

env vars are set via os.environ.setdefault BEFORE any app module is imported so
that pydantic-settings can parse them at Settings() instantiation time.

The `client` fixture overrides the get_instrument_registry FastAPI dependency
with a mock registry whose drivers are configured per-test via `mock_drivers`.
No real instruments or VISA connections are required in CI.
"""

import os

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Environment — must be set before any app.* import
# ---------------------------------------------------------------------------

os.environ.setdefault("BIS_OSCILLOSCOPE_IP", "192.168.2.45")
os.environ.setdefault("BIS_SIGNAL_GENERATOR_IP", "192.168.2.46")
os.environ.setdefault("BIS_MULTIMETER_IP", "192.168.2.20")
os.environ.setdefault("BIS_POWER_SUPPLY_IP", "192.168.2.27")
os.environ.setdefault("BIS_DISCOVER_ON_STARTUP", "false")  # don't probe real instruments

# ---------------------------------------------------------------------------
# App imports (after env vars are set)
# ---------------------------------------------------------------------------

from app.main import app  # noqa: E402
from app.dependencies import get_instrument_registry  # noqa: E402
from app.services.instrument_registry import InstrumentEntry  # noqa: E402

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

_INSTRUMENT_NAMES = ("oscilloscope", "signal_generator", "multimeter", "power_supply")

FAKE_ENTRIES: dict[str, InstrumentEntry] = {
    "oscilloscope": InstrumentEntry(
        ip="192.168.2.45", reachable=True,
        identity="Siglent Technologies,SDS1202X-E,SDS1EDED5R3218,1.3.27",
    ),
    "signal_generator": InstrumentEntry(
        ip="192.168.2.46", reachable=True,
        identity="Siglent Technologies,SDG2042X,SDG2XFBQ902599,2.01.01.38R4",
    ),
    "multimeter": InstrumentEntry(
        ip="192.168.2.20", reachable=True,
        identity="Siglent Technologies,SDM3055,SDM35HBC900580,1.02.01.28",
    ),
    "power_supply": InstrumentEntry(
        ip="192.168.2.27", reachable=True,
        identity="RIGOL TECHNOLOGIES,DP832,DP8C277M00511,00.01.19",
    ),
}


def _make_driver() -> MagicMock:
    driver = MagicMock()
    driver.connect.return_value = True
    return driver


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_visa_resource() -> MagicMock:
    """Mock PyVISA resource — inject into driver unit tests via monkeypatch."""
    resource = MagicMock()
    resource.query.return_value = "Siglent Technologies,SDM3055,SDM35HBC900580,1.02.01.28"
    return resource


@pytest.fixture
def mock_drivers() -> dict[str, MagicMock]:
    """Fresh mock driver per instrument, per test. Configure return values in tests."""
    return {name: _make_driver() for name in _INSTRUMENT_NAMES}


@pytest.fixture
def client(mock_drivers: dict[str, MagicMock]):
    """FastAPI TestClient with the registry dependency replaced by a mock.

    `mock_drivers` is shared between this fixture and the test function so tests
    can configure driver return values before making requests:

        def test_foo(client, mock_drivers):
            mock_drivers["oscilloscope"].get_status.return_value = {...}
            resp = client.get("/v1/oscilloscope/status")
    """
    registry = MagicMock()
    registry.health_status = "ok"
    registry.uptime_seconds = 42.0
    registry.all_entries.return_value = FAKE_ENTRIES
    registry.get_entry.side_effect = FAKE_ENTRIES.get
    registry.get_driver.side_effect = mock_drivers.get

    app.dependency_overrides[get_instrument_registry] = lambda: registry
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()

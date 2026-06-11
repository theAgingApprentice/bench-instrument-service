"""Tests for X-API-Key authentication on instrument endpoints."""

import os
import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from app.main import app
from app.dependencies import get_instrument_registry
from app.services.instrument_registry import InstrumentEntry

_INSTRUMENT_NAMES = ("oscilloscope", "signal_generator", "multimeter", "power_supply")

_FAKE_ENTRIES: dict[str, InstrumentEntry] = {
    "oscilloscope":     InstrumentEntry(ip="192.168.2.45", reachable=True, identity="Test"),
    "signal_generator": InstrumentEntry(ip="192.168.2.46", reachable=True, identity="Test"),
    "multimeter":       InstrumentEntry(ip="192.168.2.20", reachable=True, identity="Test"),
    "power_supply":     InstrumentEntry(ip="192.168.2.27", reachable=True, identity="Test"),
}


def _make_registry() -> MagicMock:
    registry = MagicMock()
    registry.health_status = "ok"
    registry.uptime_seconds = 0.0
    registry.all_entries.return_value = _FAKE_ENTRIES
    registry.get_entry.side_effect = _FAKE_ENTRIES.get
    registry.get_driver.side_effect = {
        name: MagicMock(connect=MagicMock(return_value=True))
        for name in _INSTRUMENT_NAMES
    }.get
    return registry


@pytest.fixture
def auth_client():
    """TestClient with mocked registry and API_KEY set to 'test-key'."""
    os.environ["API_KEY"] = "test-key"
    app.dependency_overrides[get_instrument_registry] = lambda: _make_registry()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_health_no_auth_returns_200(auth_client):
    """Health endpoint is unprotected — no X-API-Key header required."""
    resp = auth_client.get("/health")
    assert resp.status_code == 200


def test_instruments_no_auth_returns_401(auth_client):
    """Instrument list endpoint rejects requests with no auth header."""
    resp = auth_client.get("/v1/instruments")
    assert resp.status_code == 401


def test_instruments_wrong_key_returns_401(auth_client):
    """Instrument list endpoint rejects a wrong API key."""
    resp = auth_client.get("/v1/instruments", headers={"X-API-Key": "wrong-key"})
    assert resp.status_code == 401


def test_instruments_correct_key_passes_auth(auth_client):
    """Correct X-API-Key header passes authentication."""
    resp = auth_client.get("/v1/instruments", headers={"X-API-Key": "test-key"})
    assert resp.status_code != 401

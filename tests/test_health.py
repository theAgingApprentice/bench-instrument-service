from fastapi.testclient import TestClient

from tests.conftest import FAKE_ENTRIES


def test_health_returns_200(client: TestClient):
    resp = client.get("/health")
    assert resp.status_code == 200


def test_health_response_shape(client: TestClient):
    data = client.get("/health").json()
    assert "status" in data
    assert "uptime_seconds" in data
    assert "instruments" in data


def test_health_status_ok_when_all_reachable(client: TestClient):
    assert client.get("/health").json()["status"] == "ok"


def test_health_lists_all_four_instruments(client: TestClient):
    instruments = client.get("/health").json()["instruments"]
    assert set(instruments.keys()) == {"oscilloscope", "signal_generator", "multimeter", "power_supply"}


def test_health_instrument_fields(client: TestClient):
    instruments = client.get("/health").json()["instruments"]
    scope = instruments["oscilloscope"]
    assert scope["reachable"] is True
    assert scope["ip"] == FAKE_ENTRIES["oscilloscope"].ip
    assert "identity" in scope


def test_health_degraded_when_instrument_unreachable(client: TestClient, mock_drivers):
    from unittest.mock import MagicMock
    from app.main import app
    from app.dependencies import get_instrument_registry
    from app.services.instrument_registry import InstrumentEntry
    from tests.conftest import FAKE_ENTRIES

    degraded_entries = dict(FAKE_ENTRIES)
    degraded_entries["oscilloscope"] = InstrumentEntry(
        ip="192.168.2.45", reachable=False, identity=None
    )

    degraded_registry = MagicMock()
    degraded_registry.health_status = "degraded"
    degraded_registry.uptime_seconds = 42.0
    degraded_registry.all_entries.return_value = degraded_entries
    degraded_registry.get_entry.side_effect = degraded_entries.get
    degraded_registry.get_driver.side_effect = mock_drivers.get

    app.dependency_overrides[get_instrument_registry] = lambda: degraded_registry
    try:
        from fastapi.testclient import TestClient as TC
        with TC(app) as c:
            data = c.get("/health").json()
        assert data["status"] == "degraded"
        assert data["instruments"]["oscilloscope"]["reachable"] is False
    finally:
        app.dependency_overrides.clear()

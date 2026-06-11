"""Tests for session management (Phase 2).

Session state is held in a module-level singleton. The autouse `reset_session`
fixture wipes it before and after every test so tests don't bleed into each other.

`session_client`     — no dependency overrides; used for pure session-endpoint tests.
`instrument_client`  — registry mocked, check_session left real; used for access-control tests.
`stacked_dep_client` — generator-based registry override that exercises the real
                       set_client_ip / reset_client_ip teardown path, reproducing the
                       stacked-dependency 500 regression (see test_stacked_deps_*).
"""

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from app.main import app
from app.dependencies import get_instrument_registry, verify_api_key
from app.services.command_logger import command_logger
from app.services.session_manager import session_manager
from tests.conftest import FAKE_ENTRIES, _INSTRUMENT_NAMES

_STATUS_PAYLOAD = {
    "channel_1": {"enabled": True, "coupling": "DC", "scale": 1.0, "offset": 0.0, "probe": 10},
    "channel_2": {"enabled": False, "coupling": "DC", "scale": 1.0, "offset": 0.0, "probe": 1},
    "timebase": {"scale": 0.001, "offset": 0.0},
}


def _make_driver() -> MagicMock:
    driver = MagicMock()
    driver.connect.return_value = True
    return driver


@pytest.fixture(autouse=True)
def reset_session():
    session_manager._session = None
    yield
    session_manager._session = None


@pytest.fixture
def session_client():
    app.dependency_overrides[verify_api_key] = lambda: None
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def mock_drivers():
    return {name: _make_driver() for name in _INSTRUMENT_NAMES}


@pytest.fixture
def instrument_client(mock_drivers):
    """Registry mocked, check_session left real so access-control tests work."""
    registry = MagicMock()
    registry.health_status = "ok"
    registry.uptime_seconds = 42.0
    registry.all_entries.return_value = FAKE_ENTRIES
    registry.get_entry.side_effect = FAKE_ENTRIES.get
    registry.get_driver.side_effect = mock_drivers.get

    app.dependency_overrides[get_instrument_registry] = lambda: registry
    app.dependency_overrides[verify_api_key] = lambda: None
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------

def test_acquire_returns_token(session_client: TestClient):
    resp = session_client.post("/v1/sessions/acquire")
    assert resp.status_code == 201
    data = resp.json()
    assert "session_id" in data
    assert "client_ip" in data
    assert "acquired_at" in data
    assert "expires_at" in data


def test_duplicate_acquire_returns_409(session_client: TestClient):
    session_client.post("/v1/sessions/acquire")
    resp = session_client.post("/v1/sessions/acquire")
    assert resp.status_code == 409


def test_release_clears_session(session_client: TestClient):
    token = session_client.post("/v1/sessions/acquire").json()["session_id"]
    assert session_client.delete(f"/v1/sessions/{token}").status_code == 204
    # After release a second acquire must succeed
    assert session_client.post("/v1/sessions/acquire").status_code == 201


def test_release_unknown_token_returns_404(session_client: TestClient):
    resp = session_client.delete("/v1/sessions/no-such-id")
    assert resp.status_code == 404


def test_keepalive_extends_expiry(session_client: TestClient):
    data = session_client.post("/v1/sessions/acquire").json()
    token = data["session_id"]
    original_expires = data["expires_at"]

    resp = session_client.put(f"/v1/sessions/{token}/keepalive")
    assert resp.status_code == 200
    new_expires = resp.json()["expires_at"]
    assert new_expires >= original_expires


def test_keepalive_unknown_token_returns_404(session_client: TestClient):
    resp = session_client.put("/v1/sessions/no-such-id/keepalive")
    assert resp.status_code == 404


def test_status_no_session(session_client: TestClient):
    resp = session_client.get("/v1/sessions/status")
    assert resp.status_code == 200
    assert resp.json() == {"active": False}


def test_status_with_active_session(session_client: TestClient):
    token = session_client.post("/v1/sessions/acquire").json()["session_id"]
    resp = session_client.get("/v1/sessions/status")
    assert resp.status_code == 200
    assert resp.json()["session_id"] == token


# ---------------------------------------------------------------------------
# Instrument access control
# ---------------------------------------------------------------------------

def test_instrument_endpoint_open_when_no_session(
    instrument_client: TestClient, mock_drivers
):
    mock_drivers["oscilloscope"].get_status.return_value = _STATUS_PAYLOAD
    resp = instrument_client.get("/v1/oscilloscope/status")
    assert resp.status_code == 200


def test_instrument_endpoint_rejected_with_423(
    instrument_client: TestClient, mock_drivers
):
    mock_drivers["oscilloscope"].get_status.return_value = _STATUS_PAYLOAD
    instrument_client.post("/v1/sessions/acquire")

    resp = instrument_client.get(
        "/v1/oscilloscope/status",
        headers={"X-Session-ID": "wrong-token"},
    )
    assert resp.status_code == 423
    assert "expires_at" in resp.json()["detail"]


def test_instrument_endpoint_rejected_with_no_token_when_session_held(
    instrument_client: TestClient, mock_drivers
):
    mock_drivers["oscilloscope"].get_status.return_value = _STATUS_PAYLOAD
    instrument_client.post("/v1/sessions/acquire")

    resp = instrument_client.get("/v1/oscilloscope/status")
    assert resp.status_code == 423


def test_instrument_endpoint_passes_with_correct_token(
    instrument_client: TestClient, mock_drivers
):
    mock_drivers["oscilloscope"].get_status.return_value = _STATUS_PAYLOAD
    token = instrument_client.post("/v1/sessions/acquire").json()["session_id"]

    resp = instrument_client.get(
        "/v1/oscilloscope/status",
        headers={"X-Session-ID": token},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Stacked-dependency teardown regression
#
# The instrument_client fixture above overrides get_instrument_registry with a
# plain lambda, which bypasses set_client_ip / reset_client_ip entirely.  The
# stacked_dep_client fixture below uses a *generator* override that mirrors the
# real function, so reset_client_ip runs on every request.  Without the
# ValueError guard in reset_client_ip, these tests would return 500.
# ---------------------------------------------------------------------------

@pytest.fixture
def stacked_dep_client(mock_drivers):
    """Generator-based registry override — exercises the real set/reset_client_ip path."""
    registry = MagicMock()
    registry.health_status = "ok"
    registry.uptime_seconds = 42.0
    registry.all_entries.return_value = FAKE_ENTRIES
    registry.get_entry.side_effect = FAKE_ENTRIES.get
    registry.get_driver.side_effect = mock_drivers.get

    def gen_override(request: Request):
        token = command_logger.set_client_ip(
            request.client.host if request.client else "unknown"
        )
        try:
            yield registry
        finally:
            command_logger.reset_client_ip(token)

    app.dependency_overrides[get_instrument_registry] = gen_override
    app.dependency_overrides[verify_api_key] = lambda: None
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_stacked_deps_open_access_returns_200(
    stacked_dep_client: TestClient, mock_drivers
):
    """Regression: check_session + generator get_instrument_registry must not 500."""
    mock_drivers["oscilloscope"].get_status.return_value = _STATUS_PAYLOAD
    resp = stacked_dep_client.get("/v1/oscilloscope/status")
    assert resp.status_code == 200


def test_stacked_deps_correct_token_returns_200(
    stacked_dep_client: TestClient, mock_drivers
):
    """Regression: session holder + real teardown path must not 500."""
    mock_drivers["oscilloscope"].get_status.return_value = _STATUS_PAYLOAD
    token = stacked_dep_client.post("/v1/sessions/acquire").json()["session_id"]
    resp = stacked_dep_client.get(
        "/v1/oscilloscope/status",
        headers={"X-Session-ID": token},
    )
    assert resp.status_code == 200

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

_STATUS_PAYLOAD = {
    "channel_1": {"enabled": True,  "coupling": "DC", "scale": 1.0, "offset": 0.0, "probe": 10},
    "channel_2": {"enabled": False, "coupling": "DC", "scale": 1.0, "offset": 0.0, "probe": 1},
    "timebase":  {"scale": 0.001, "offset": 0.0},
    "trigger": {"source": 1, "mode": "AUTO", "level": 0.5, "slope": "POS"},
}

_WAVEFORM = {
    "enabled": True,
    "sample_rate": 1_000_000.0,
    "timebase": 0.001,
    "volts_per_div": 0.5,
    "offset": 0.0,
    "probe_ratio": 10,
    "num_points": 4,
    "time_array": [0.0, 1e-6, 2e-6, 3e-6],
    "voltage_array": [0.1, 0.2, 0.15, 0.12],
}


def test_oscilloscope_status_200(client: TestClient, mock_drivers):
    mock_drivers["oscilloscope"].get_status.return_value = _STATUS_PAYLOAD
    resp = client.get("/v1/oscilloscope/status")
    assert resp.status_code == 200


def test_oscilloscope_status_shape(client: TestClient, mock_drivers):
    mock_drivers["oscilloscope"].get_status.return_value = _STATUS_PAYLOAD
    data = client.get("/v1/oscilloscope/status").json()
    assert "channel_1" in data
    assert "channel_2" in data
    assert "timebase" in data
    assert data["channel_1"]["coupling"] == "DC"
    assert data["timebase"]["scale"] == pytest.approx(0.001)


def test_oscilloscope_configure_calls_driver(client: TestClient, mock_drivers):
    resp = client.post(
        "/v1/oscilloscope/configure",
        json={"channel": 1, "channel_config": {"coupling": "DC", "scale": 0.5}},
    )
    assert resp.status_code == 200
    mock_drivers["oscilloscope"].configure_channel.assert_called_once_with(
        channel=1, coupling="DC", scale=0.5, offset=None, probe=None,
    )


def test_oscilloscope_configure_timebase_calls_driver(client: TestClient, mock_drivers):
    resp = client.post(
        "/v1/oscilloscope/configure",
        json={"channel": 1, "timebase": {"scale": 0.001, "offset": 0.0}},
    )
    assert resp.status_code == 200
    mock_drivers["oscilloscope"].configure_timebase.assert_called_once_with(
        scale=0.001, offset=0.0,
    )


def test_oscilloscope_configure_trigger_calls_driver(client: TestClient, mock_drivers):
    resp = client.post(
        "/v1/oscilloscope/configure",
        json={"channel": 1, "trigger": {"source": 1, "level": 0.5, "slope": "POS", "mode": "AUTO"}},
    )
    assert resp.status_code == 200
    mock_drivers["oscilloscope"].configure_trigger.assert_called_once_with(
        source=1, level=0.5, slope="POS", mode="AUTO",
    )


def test_oscilloscope_configure_timebase_settles(client: TestClient, mock_drivers):
    with patch("app.routers.oscilloscope.time.sleep") as mock_sleep:
        resp = client.post(
            "/v1/oscilloscope/configure",
            json={"channel": 1, "timebase": {"scale": 0.001, "offset": 0.0}},
        )
    assert resp.status_code == 200
    mock_sleep.assert_called_once_with(pytest.approx(0.001 * 14 + 0.5))


def test_oscilloscope_configure_without_timebase_does_not_settle(client: TestClient, mock_drivers):
    with patch("app.routers.oscilloscope.time.sleep") as mock_sleep:
        resp = client.post(
            "/v1/oscilloscope/configure",
            json={"channel": 1, "channel_config": {"coupling": "DC", "scale": 0.5}},
        )
    assert resp.status_code == 200
    mock_sleep.assert_not_called()

    with patch("app.routers.oscilloscope.time.sleep") as mock_sleep:
        resp = client.post(
            "/v1/oscilloscope/configure",
            json={"channel": 1, "trigger": {"source": 1, "level": 0.5, "slope": "POS", "mode": "AUTO"}},
        )
    assert resp.status_code == 200
    mock_sleep.assert_not_called()


def test_oscilloscope_capture_returns_waveform(client: TestClient, mock_drivers):
    mock_drivers["oscilloscope"].capture_waveforms.return_value = {1: _WAVEFORM}
    resp = client.post("/v1/oscilloscope/capture", json={"channels": [1]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["channel_1"]["num_points"] == 4
    assert data["channel_2"] is None
    mock_drivers["oscilloscope"].capture_waveforms.assert_called_once_with([1])


def test_oscilloscope_capture_both_channels(client: TestClient, mock_drivers):
    """A dual-channel request must be a single capture_waveforms() call with
    both channels, not one capture_waveform() call per channel -- calling
    per-channel let acquisition resume between channels and produce an empty
    second capture on real hardware (confirmed 7 July 2026).
    """
    mock_drivers["oscilloscope"].capture_waveforms.return_value = {1: _WAVEFORM, 2: _WAVEFORM}
    resp = client.post("/v1/oscilloscope/capture", json={"channels": [1, 2]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["channel_1"] is not None
    assert data["channel_2"] is not None
    mock_drivers["oscilloscope"].capture_waveforms.assert_called_once_with([1, 2])


def test_oscilloscope_status_503_when_unreachable(client: TestClient, mock_drivers):
    mock_drivers["oscilloscope"].connect.return_value = False
    resp = client.get("/v1/oscilloscope/status")
    assert resp.status_code == 503

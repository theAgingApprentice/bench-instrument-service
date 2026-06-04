import pytest
from fastapi.testclient import TestClient

_CHANNEL_STATUS = {
    "output_enabled": True,
    "waveform": "SINE",
    "frequency": 1000.0,
    "amplitude": 2.0,
    "offset": 0.0,
    "duty_cycle": 50.0,
    "phase": 0.0,
}

_STATUS_PAYLOAD = {"channel_1": _CHANNEL_STATUS, "channel_2": {**_CHANNEL_STATUS, "output_enabled": False}}


def test_signal_generator_status_200(client: TestClient, mock_drivers):
    mock_drivers["signal_generator"].get_status.return_value = _STATUS_PAYLOAD
    resp = client.get("/v1/signal-generator/status")
    assert resp.status_code == 200


def test_signal_generator_status_shape(client: TestClient, mock_drivers):
    mock_drivers["signal_generator"].get_status.return_value = _STATUS_PAYLOAD
    data = client.get("/v1/signal-generator/status").json()
    assert data["channel_1"]["waveform"] == "SINE"
    assert data["channel_1"]["frequency"] == pytest.approx(1000.0)
    assert data["channel_2"]["output_enabled"] is False


def test_signal_generator_configure_calls_driver(client: TestClient, mock_drivers):
    resp = client.post(
        "/v1/signal-generator/configure",
        json={"channel": 1, "waveform": "SQUARE", "frequency": 1000.0, "amplitude": 3.3},
    )
    assert resp.status_code == 200
    mock_drivers["signal_generator"].configure_channel.assert_called_once()
    _, kwargs = mock_drivers["signal_generator"].configure_channel.call_args
    assert kwargs["waveform"] == "SQUARE"
    assert kwargs["frequency"] == pytest.approx(1000.0)


def test_signal_generator_output_enable(client: TestClient, mock_drivers):
    resp = client.post("/v1/signal-generator/output", json={"channel": 1, "enabled": True})
    assert resp.status_code == 200
    mock_drivers["signal_generator"].set_output.assert_called_once_with(1, True)


def test_signal_generator_output_disable(client: TestClient, mock_drivers):
    resp = client.post("/v1/signal-generator/output", json={"channel": 2, "enabled": False})
    assert resp.status_code == 200
    mock_drivers["signal_generator"].set_output.assert_called_once_with(2, False)


def test_signal_generator_invalid_waveform_422(client: TestClient):
    resp = client.post(
        "/v1/signal-generator/configure",
        json={"channel": 1, "waveform": "INVALID_WAVE"},
    )
    assert resp.status_code == 422


def test_signal_generator_invalid_channel_422(client: TestClient):
    resp = client.post("/v1/signal-generator/output", json={"channel": 5, "enabled": True})
    assert resp.status_code == 422


def test_signal_generator_status_503_when_unreachable(client: TestClient, mock_drivers):
    mock_drivers["signal_generator"].connect.return_value = False
    resp = client.get("/v1/signal-generator/status")
    assert resp.status_code == 503

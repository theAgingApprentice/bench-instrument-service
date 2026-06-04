import pytest
from fastapi.testclient import TestClient

_STATUS_PAYLOAD = {
    "channel_1": {"enabled": True,  "coupling": "DC", "scale": 1.0, "offset": 0.0, "probe": 10},
    "channel_2": {"enabled": False, "coupling": "DC", "scale": 1.0, "offset": 0.0, "probe": 1},
    "timebase":  {"scale": 0.001, "offset": 0.0},
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
    resp = client.post("/v1/oscilloscope/configure", json={"channel": 1, "coupling": "DC", "scale": 0.5})
    assert resp.status_code == 200
    mock_drivers["oscilloscope"].configure_channel.assert_called_once_with(
        channel=1, coupling="DC", scale=0.5, offset=None, probe=None,
    )


def test_oscilloscope_capture_returns_waveform(client: TestClient, mock_drivers):
    mock_drivers["oscilloscope"].capture_waveform.return_value = _WAVEFORM
    resp = client.post("/v1/oscilloscope/capture", json={"channels": [1]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["channel_1"]["num_points"] == 4
    assert data["channel_2"] is None


def test_oscilloscope_capture_both_channels(client: TestClient, mock_drivers):
    mock_drivers["oscilloscope"].capture_waveform.return_value = _WAVEFORM
    resp = client.post("/v1/oscilloscope/capture", json={"channels": [1, 2]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["channel_1"] is not None
    assert data["channel_2"] is not None
    assert mock_drivers["oscilloscope"].capture_waveform.call_count == 2


def test_oscilloscope_status_503_when_unreachable(client: TestClient, mock_drivers):
    mock_drivers["oscilloscope"].connect.return_value = False
    resp = client.get("/v1/oscilloscope/status")
    assert resp.status_code == 503

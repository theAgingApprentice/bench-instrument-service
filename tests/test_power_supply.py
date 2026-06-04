import pytest
from fastapi.testclient import TestClient

_CHANNEL = {
    "output_enabled": True,
    "voltage_set": 5.0,
    "current_limit": 1.0,
    "voltage_actual": 4.998,
    "current_actual": 0.234,
    "power_actual": 1.169,
}

_OFF_CHANNEL = {
    "output_enabled": False,
    "voltage_set": 3.3,
    "current_limit": 0.5,
    "voltage_actual": 0.0,
    "current_actual": 0.0,
    "power_actual": 0.0,
}

_STATUS_PAYLOAD = {
    "channel_1": _CHANNEL,
    "channel_2": _OFF_CHANNEL,
    "channel_3": {**_OFF_CHANNEL, "voltage_set": 12.0, "current_limit": 2.0},
}


def test_power_supply_status_200(client: TestClient, mock_drivers):
    mock_drivers["power_supply"].get_status.return_value = _STATUS_PAYLOAD
    resp = client.get("/v1/power-supply/status")
    assert resp.status_code == 200


def test_power_supply_status_shape(client: TestClient, mock_drivers):
    mock_drivers["power_supply"].get_status.return_value = _STATUS_PAYLOAD
    data = client.get("/v1/power-supply/status").json()
    assert data["channel_1"]["voltage_set"] == pytest.approx(5.0)
    assert data["channel_1"]["output_enabled"] is True
    assert data["channel_2"]["output_enabled"] is False
    assert "channel_3" in data


def test_power_supply_configure_calls_driver(client: TestClient, mock_drivers):
    resp = client.post(
        "/v1/power-supply/configure",
        json={"channel": 1, "voltage": 5.0, "current_limit": 1.0},
    )
    assert resp.status_code == 200
    mock_drivers["power_supply"].configure_channel.assert_called_once_with(1, 5.0, 1.0)


def test_power_supply_output_on(client: TestClient, mock_drivers):
    resp = client.post("/v1/power-supply/output", json={"channel": 1, "enabled": True})
    assert resp.status_code == 200
    mock_drivers["power_supply"].set_output.assert_called_once_with(1, True)


def test_power_supply_output_off(client: TestClient, mock_drivers):
    resp = client.post("/v1/power-supply/output", json={"channel": 2, "enabled": False})
    assert resp.status_code == 200
    mock_drivers["power_supply"].set_output.assert_called_once_with(2, False)


def test_power_supply_all_off(client: TestClient, mock_drivers):
    resp = client.post("/v1/power-supply/all-off")
    assert resp.status_code == 200
    mock_drivers["power_supply"].all_off.assert_called_once()


def test_power_supply_invalid_channel_422(client: TestClient):
    resp = client.post(
        "/v1/power-supply/configure",
        json={"channel": 4, "voltage": 5.0, "current_limit": 1.0},
    )
    assert resp.status_code == 422


def test_power_supply_status_503_when_unreachable(client: TestClient, mock_drivers):
    mock_drivers["power_supply"].connect.return_value = False
    resp = client.get("/v1/power-supply/status")
    assert resp.status_code == 503

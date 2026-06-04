import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log_result(count: int = 3) -> dict:
    now = _now()
    values = [3.296, 3.294, 3.298][:count]
    return {
        "mode": "VOLT:DC",
        "unit": "V",
        "count": count,
        "readings": [{"timestamp": now, "value": v} for v in values],
        "statistics": {"min": min(values), "max": max(values), "mean": 3.296, "std_dev": 0.002},
    }


def test_multimeter_status_200(client: TestClient, mock_drivers):
    mock_drivers["multimeter"].get_status.return_value = {
        "mode": "VOLT:DC", "range": "AUTO", "resolution": "HIGH"
    }
    resp = client.get("/v1/multimeter/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "VOLT:DC"
    assert data["range"] == "AUTO"


def test_multimeter_measure_returns_value(client: TestClient, mock_drivers):
    mock_drivers["multimeter"].measure.return_value = {
        "timestamp": _now(), "mode": "VOLT:DC", "value": 3.296, "unit": "V"
    }
    resp = client.post("/v1/multimeter/measure", json={"mode": "VOLT:DC"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["value"] == pytest.approx(3.296)
    assert data["unit"] == "V"


def test_multimeter_measure_invalid_mode_422(client: TestClient):
    resp = client.post("/v1/multimeter/measure", json={"mode": "RESISTANCE"})
    assert resp.status_code == 422


def test_multimeter_log_returns_stats_and_log_id(client: TestClient, mock_drivers):
    mock_drivers["multimeter"].log_measurements.return_value = _log_result(3)
    resp = client.post(
        "/v1/multimeter/log",
        json={"mode": "VOLT:DC", "duration_seconds": 3, "interval_seconds": 1.0},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 3
    assert data["unit"] == "V"
    assert "log_id" in data and data["log_id"] is not None
    assert data["statistics"]["mean"] == pytest.approx(3.296)
    mock_drivers["multimeter"].log_measurements.assert_called_once_with("VOLT:DC", 3, 1.0)


def test_multimeter_log_csv_download(client: TestClient, mock_drivers):
    mock_drivers["multimeter"].log_measurements.return_value = _log_result(1)
    post_resp = client.post(
        "/v1/multimeter/log",
        json={"mode": "VOLT:DC", "duration_seconds": 1, "interval_seconds": 1.0},
    )
    log_id = post_resp.json()["log_id"]

    csv_resp = client.get(f"/v1/multimeter/log/{log_id}/csv")
    assert csv_resp.status_code == 200
    assert "text/csv" in csv_resp.headers["content-type"]
    assert "3.296" in csv_resp.text
    assert "timestamp" in csv_resp.text


def test_multimeter_log_csv_404_unknown_id(client: TestClient):
    resp = client.get("/v1/multimeter/log/no-such-id/csv")
    assert resp.status_code == 404


def test_multimeter_status_503_when_unreachable(client: TestClient, mock_drivers):
    mock_drivers["multimeter"].connect.return_value = False
    resp = client.get("/v1/multimeter/status")
    assert resp.status_code == 503

"""Tests for bench_client.py.

Uses unittest.mock to patch urllib.request.urlopen — no real network
or BIS instance required.  The mock returns a fake HTTP response object
whose .read() returns JSON-encoded bytes and whose .status is 200.
"""

from __future__ import annotations

import io
import json
import sys
import os
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from bench_client import BenchClient, BISError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_response(payload: dict, status: int = 200) -> MagicMock:
    """Return a mock that behaves like urllib's http.client.HTTPResponse."""
    mock = MagicMock()
    mock.read.return_value = json.dumps(payload).encode()
    mock.status = status
    mock.__enter__ = lambda s: s
    mock.__exit__ = MagicMock(return_value=False)
    return mock


@contextmanager
def _mock_urlopen(payload: dict, status: int = 200):
    """Context manager: patches urlopen to return a fake response."""
    with patch("urllib.request.urlopen", return_value=_fake_response(payload, status)) as m:
        yield m


@contextmanager
def _mock_urlopen_error(status: int, detail: str):
    """Context manager: patches urlopen to raise HTTPError."""
    import urllib.error
    err = urllib.error.HTTPError(
        url="https://mitchellnet.local/api/bench/test",
        code=status,
        msg="error",
        hdrs=None,  # type: ignore[arg-type]
        fp=io.BytesIO(json.dumps({"detail": detail}).encode()),
    )
    with patch("urllib.request.urlopen", side_effect=err):
        yield


CLIENT = BenchClient(base_url="http://bis.test", api_key="test-key", verify_ssl=True)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_ok(self):
        payload = {"status": "ok", "instruments": {}}
        with _mock_urlopen(payload):
            result = CLIENT.health()
        assert result["status"] == "ok"

    def test_health_full_ok(self):
        payload = {"status": "ok", "instruments": {}, "session": None}
        with _mock_urlopen(payload):
            result = CLIENT.health_full()
        assert "session" in result


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

class TestSessionManagement:
    def test_acquire_session_returns_token(self):
        payload = {"session_id": "abc-123", "client_id": "test", "expires_at": "2099-01-01T00:00:00"}
        with _mock_urlopen(payload):
            token = CLIENT.acquire_session("test-client")
        assert token == "abc-123"

    def test_acquire_session_stores_token_on_client(self):
        payload = {"session_id": "abc-123", "client_id": "test", "expires_at": "2099-01-01T00:00:00"}
        with _mock_urlopen(payload):
            CLIENT.acquire_session("test-client")
        assert CLIENT._session_token == "abc-123"

    def test_release_session_clears_stored_token(self):
        CLIENT._session_token = "abc-123"
        with _mock_urlopen({}):
            CLIENT.release_session("abc-123")
        assert CLIENT._session_token is None

    def test_keepalive_sends_put(self):
        payload = {"session_id": "abc-123", "expires_at": "2099-01-01T00:00:00"}
        with _mock_urlopen(payload) as mock_open:
            CLIENT.keepalive("abc-123")
        req = mock_open.call_args[0][0]
        assert req.get_method() == "PUT"

    def test_context_manager_releases_on_exit(self):
        acquire_payload = {"session_id": "tok-1", "client_id": "c", "expires_at": "2099-01-01T00:00:00"}
        release_payload = {}
        responses = [_fake_response(acquire_payload), _fake_response(release_payload)]
        with patch("urllib.request.urlopen", side_effect=responses):
            with BenchClient(base_url="http://bis.test", api_key="k", verify_ssl=True) as bench:
                token = bench.acquire_session("ctx-test")
            assert bench._session_token is None

    def test_context_manager_releases_on_exception(self):
        acquire_payload = {"session_id": "tok-2", "client_id": "c", "expires_at": "2099-01-01T00:00:00"}
        release_payload = {}
        responses = [_fake_response(acquire_payload), _fake_response(release_payload)]
        with patch("urllib.request.urlopen", side_effect=responses):
            with pytest.raises(ValueError):
                with BenchClient(base_url="http://bis.test", api_key="k", verify_ssl=True) as bench:
                    bench.acquire_session("ctx-test")
                    raise ValueError("simulated error")
        assert bench._session_token is None


# ---------------------------------------------------------------------------
# Oscilloscope
# ---------------------------------------------------------------------------

class TestOscilloscope:
    def test_capture_waveform_posts_correct_body(self):
        payload = {"channel": 1, "time_s": [0.0], "voltage_v": [1.0]}
        with _mock_urlopen(payload) as mock_open:
            CLIENT.capture_waveform("tok", channel=1)
        req = mock_open.call_args[0][0]
        body = json.loads(req.data)
        assert body["channels"] == [1]

    def test_capture_waveform_returns_dict(self):
        payload = {"channel": 1, "time_s": [], "voltage_v": []}
        with _mock_urlopen(payload):
            result = CLIENT.capture_waveform("tok")
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Signal generator
# ---------------------------------------------------------------------------

class TestSignalGenerator:
    def test_configure_signal_posts_correct_body(self):
        payload = {"channel": 1, "waveform": "SINE", "frequency": 1000.0}
        with _mock_urlopen(payload) as mock_open:
            CLIENT.configure_signal("tok", channel=1, waveform="SINE", freq_hz=1000.0, amplitude_v=2.0)
        req = mock_open.call_args[0][0]
        body = json.loads(req.data)
        assert body["waveform"] == "SINE"
        assert body["frequency"] == 1000.0
        assert body["amplitude"] == 2.0

    def test_enable_output_posts_enabled_flag(self):
        with _mock_urlopen({"channel": 1, "enabled": True}) as mock_open:
            CLIENT.enable_output("tok", channel=1, enabled=True)
        req = mock_open.call_args[0][0]
        body = json.loads(req.data)
        assert body["enabled"] is True


# ---------------------------------------------------------------------------
# Power supply
# ---------------------------------------------------------------------------

class TestPowerSupply:
    def test_set_psu_channel_posts_correct_body(self):
        payload = {"channel": 2, "voltage": 5.0, "current_limit": 1.0}
        with _mock_urlopen(payload) as mock_open:
            CLIENT.set_psu_channel("tok", channel=2, voltage_v=5.0, current_limit_a=1.0)
        req = mock_open.call_args[0][0]
        body = json.loads(req.data)
        assert body["channel"] == 2
        assert body["voltage"] == 5.0

    def test_enable_psu_channel_sends_correct_body(self):
        with _mock_urlopen({"channel": 1, "enabled": False}) as mock_open:
            CLIENT.enable_psu_channel("tok", channel=1, enabled=False)
        req = mock_open.call_args[0][0]
        body = json.loads(req.data)
        assert body["enabled"] is False


# ---------------------------------------------------------------------------
# Multimeter
# ---------------------------------------------------------------------------

class TestMultimeter:
    def test_measure_posts_mode_and_range(self):
        payload = {"mode": "DCV", "value": 3.3, "unit": "V", "timestamp": "2025-01-01T00:00:00"}
        with _mock_urlopen(payload) as mock_open:
            CLIENT.measure("tok", mode="DCV", range_="AUTO")
        req = mock_open.call_args[0][0]
        body = json.loads(req.data)
        assert body["mode"] == "DCV"
        assert body["range"] == "AUTO"

    def test_log_measurements_posts_correct_body(self):
        payload = {"log_id": "x", "mode": "DCV", "unit": "V", "count": 5, "readings": [], "statistics": {}}
        with _mock_urlopen(payload) as mock_open:
            CLIENT.log_measurements("tok", mode="DCV", duration_s=5, interval_s=1.0)
        req = mock_open.call_args[0][0]
        body = json.loads(req.data)
        assert body["duration_seconds"] == 5
        assert body["interval_seconds"] == 1.0

    def test_get_log_csv_url_returns_correct_url(self):
        url = CLIENT.get_log_csv_url("my-log-id")
        assert url == "http://bis.test/v1/multimeter/log/my-log-id/csv"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_raises_biserror_on_404(self):
        with _mock_urlopen_error(404, "Instrument not found"):
            with pytest.raises(BISError) as exc_info:
                CLIENT.health()
        assert exc_info.value.status == 404
        assert "Instrument not found" in exc_info.value.detail

    def test_raises_biserror_on_423(self):
        with _mock_urlopen_error(423, "Session locked"):
            with pytest.raises(BISError) as exc_info:
                CLIENT.capture_waveform("bad-token")
        assert exc_info.value.status == 423

    def test_biserror_str_contains_status(self):
        err = BISError(500, "internal error")
        assert "500" in str(err)

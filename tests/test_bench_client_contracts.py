"""Contract tests: verify bench_client.py request bodies match the real
Pydantic models used by the FastAPI routers.

These tests exist because ordinary unit tests that mock the HTTP transport
(see test_bench_client.py) cannot catch field-name mismatches between the
client and server: Pydantic BaseModel silently ignores unknown keys by
default, so a wrong key name never raises an error server-side -- it just
silently fails to configure the instrument. Four such bugs shipped
undetected until discovered live at the bench (5 July 2026).

Each test captures the JSON body a bench_client.py method would send (by
patching urllib.request.urlopen, same technique as test_bench_client.py)
and asserts every key in that body is a real field on the corresponding
Pydantic request model -- not just that the model happens to validate it.
"""

import json
from unittest.mock import MagicMock, patch

from bench_client import BenchClient
from app.models.oscilloscope import (
    ChannelConfigRequest,
    OscilloscopeCaptureRequest,
    OscilloscopeConfigureRequest,
    TimebaseConfigRequest,
    TriggerConfigRequest,
)
from app.models.signal_generator import SignalGeneratorConfigureRequest
from app.models.power_supply import PowerSupplyConfigureRequest
from app.models.multimeter import MultimeterMeasureRequest, MultimeterLogRequest

CLIENT = BenchClient(base_url="https://fake", api_key="test")


def _capture_body(call) -> dict:
    """Invoke a bench_client.py method and return the JSON body it sends."""
    fake_resp = MagicMock()
    fake_resp.read.return_value = b"{}"
    fake_resp.__enter__.return_value = fake_resp
    with patch("urllib.request.urlopen", return_value=fake_resp) as mock_open:
        call()
    req = mock_open.call_args[0][0]
    return json.loads(req.data) if req.data else {}


def _assert_body_matches_model(body: dict, model_cls) -> None:
    """Assert every key in body is a real field on model_cls, and that the
    model accepts the body without a validation error."""
    valid_fields = set(model_cls.model_fields.keys())
    unknown = set(body.keys()) - valid_fields
    assert not unknown, (
        f"body contains keys not recognized by {model_cls.__name__}: {unknown}. "
        f"These would be silently dropped by the server, not rejected."
    )
    model_cls.model_validate(body)


class TestOscilloscopeContract:
    def test_capture_waveform_matches_model(self):
        body = _capture_body(lambda: CLIENT.capture_waveform("tok", channel=2))
        _assert_body_matches_model(body, OscilloscopeCaptureRequest)

    def test_configure_oscilloscope_matches_model(self):
        body = _capture_body(lambda: CLIENT.configure_oscilloscope(
            "tok",
            channel=1,
            coupling="DC",
            scale=1.0,
            offset=0.0,
            probe=10,
            timebase_scale=0.001,
            trigger_source=1,
            trigger_level=0.5,
            trigger_slope="POS",
            trigger_mode="AUTO",
        ))
        _assert_body_matches_model(body, OscilloscopeConfigureRequest)
        _assert_body_matches_model(body["trigger"], TriggerConfigRequest)
        _assert_body_matches_model(body["channel_config"], ChannelConfigRequest)

    def test_configure_oscilloscope_timebase_matches_model(self):
        body = _capture_body(lambda: CLIENT.configure_oscilloscope(
            "tok", channel=1, timebase_scale=0.001, timebase_offset=0.0,
        ))
        _assert_body_matches_model(body, OscilloscopeConfigureRequest)
        _assert_body_matches_model(body["timebase"], TimebaseConfigRequest)


class TestSignalGeneratorContract:
    def test_configure_signal_matches_model(self):
        body = _capture_body(lambda: CLIENT.configure_signal(
            "tok", channel=1, waveform="SQUARE", freq_hz=1.0,
            amplitude_v=5.0, offset_v=2.5,
        ))
        _assert_body_matches_model(body, SignalGeneratorConfigureRequest)


class TestPowerSupplyContract:
    def test_set_psu_channel_matches_model(self):
        body = _capture_body(lambda: CLIENT.set_psu_channel(
            "tok", channel=1, voltage_v=3.3, current_limit_a=0.5,
        ))
        _assert_body_matches_model(body, PowerSupplyConfigureRequest)


class TestMultimeterContract:
    def test_measure_matches_model(self):
        body = _capture_body(lambda: CLIENT.measure("tok", mode="RES"))
        _assert_body_matches_model(body, MultimeterMeasureRequest)

    def test_log_measurements_matches_model(self):
        body = _capture_body(lambda: CLIENT.log_measurements("tok", mode="VOLT:DC"))
        _assert_body_matches_model(body, MultimeterLogRequest)

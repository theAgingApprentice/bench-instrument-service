"""BIS Python client library.

Provides a thin, synchronous wrapper around the Bench Instrument Service
HTTP API. Intended for use from Virtual Bench (macOS) and RC Experiment
scripts (Windows/Parallels).

Usage — context manager (recommended):

    from bench_client import BenchClient

    with BenchClient() as bench:
        token = bench.acquire_session("rc-experiment-3")
        waveform = bench.capture_waveform(token, channel=1)
        bench.configure_signal(token, waveform="SINE", freq_hz=1000.0, amplitude_v=1.0)
        print(waveform)
    # session released automatically on exit

Usage — manual:

    bench = BenchClient(base_url="https://mitchellnet.local/api/bench")
    token = bench.acquire_session("my-script")
    try:
        result = bench.measure(token, mode="DCV")
    finally:
        bench.release_session(token)
"""

from __future__ import annotations

import urllib.request
import urllib.error
import json
import ssl
from typing import Any


class BISError(Exception):
    """Raised when BIS returns a non-2xx response."""

    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        self.detail = detail
        super().__init__(f"BIS {status}: {detail}")


class BenchClient:
    """Synchronous HTTP client for the Bench Instrument Service.

    Args:
        base_url: Base URL of the BIS instance, without trailing slash.
        api_key:  Value for the X-API-Key header. Must match BIS_API_KEY
                  on the server.
        verify_ssl: Set False to skip TLS certificate verification (required
                    for mitchellnet.local self-signed cert).
        timeout:  Request timeout in seconds.
    """

    def __init__(
        self,
        base_url: str = "https://mitchellnet.local/api/bench",
        api_key: str = "",
        verify_ssl: bool = False,
        timeout: float = 10.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._session_token: str | None = None  # tracks token for context manager

        if verify_ssl:
            self._ssl_ctx: ssl.SSLContext | None = None
        else:
            self._ssl_ctx = ssl.create_default_context()
            self._ssl_ctx.check_hostname = False
            self._ssl_ctx.verify_mode = ssl.CERT_NONE

    # ------------------------------------------------------------------
    # Context manager — acquires / releases session automatically
    # ------------------------------------------------------------------

    def __enter__(self) -> "BenchClient":
        return self

    def __exit__(self, *_: Any) -> None:
        if self._session_token:
            try:
                self.release_session(self._session_token)
            except BISError:
                pass
            self._session_token = None

    # ------------------------------------------------------------------
    # Internal HTTP helpers
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        token: str | None = None,
        binary: bool = False,
    ) -> Any:
        url = f"{self._base}{path}"
        data = json.dumps(body).encode() if body is not None else None

        headers: dict[str, str] = {"Accept": "*/*" if binary else "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if self._api_key:
            headers["X-API-Key"] = self._api_key
        if token:
            headers["X-Session-ID"] = token

        req = urllib.request.Request(url, data=data, headers=headers, method=method)

        try:
            with urllib.request.urlopen(
                req, timeout=self._timeout, context=self._ssl_ctx
            ) as resp:
                raw = resp.read()
                if binary:
                    return raw
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                detail = json.loads(raw).get("detail", raw.decode())
            except Exception:
                detail = raw.decode(errors="replace")
            raise BISError(exc.code, detail) from exc

    def _get(self, path: str, token: str | None = None) -> Any:
        return self._request("GET", path, token=token)

    def _post(self, path: str, body: dict | None = None, token: str | None = None) -> Any:
        return self._request("POST", path, body=body, token=token)

    def _put(self, path: str, body: dict | None = None, token: str | None = None) -> Any:
        return self._request("PUT", path, body=body, token=token)

    def _delete(self, path: str, token: str | None = None) -> Any:
        return self._request("DELETE", path, token=token)

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health(self) -> dict:
        """Return BIS health status. No auth required."""
        return self._get("/health")

    def health_full(self) -> dict:
        """Return BIS health + current session state. No auth required."""
        return self._get("/health/full")

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def acquire_session(self, client_id: str, timeout_seconds: int = 300) -> str:
        """Acquire an exclusive instrument session.

        Returns the session token string. When using the context manager,
        the token is stored internally and released on __exit__.

        Args:
            client_id:       Human-readable label for the session owner.
            timeout_seconds: Seconds before the session auto-expires.

        Returns:
            Session token (UUID string).
        """
        resp = self._post(
            "/v1/sessions/acquire",
            body={"client_id": client_id, "timeout_seconds": timeout_seconds},
        )
        token: str = resp["session_id"]
        self._session_token = token
        return token

    def release_session(self, token: str) -> None:
        """Explicitly release a session before it times out."""
        self._delete(f"/v1/sessions/{token}", token=token)
        if self._session_token == token:
            self._session_token = None

    def keepalive(self, token: str) -> dict:
        """Reset the session expiry timer. Call periodically for long jobs."""
        return self._put(f"/v1/sessions/{token}/keepalive", token=token)

    def session_status(self) -> dict:
        """Return current session state (no auth required)."""
        return self._get("/v1/sessions/status")

    # ------------------------------------------------------------------
    # Oscilloscope
    # ------------------------------------------------------------------

    def capture_waveform(
        self,
        token: str,
        channel: int = 1,
    ) -> dict:
        """Capture a waveform from the oscilloscope.

        Args:
            token:   Session token.
            channel: Oscilloscope channel (1 or 2).

        Returns:
            Full capture envelope: {"timestamp": str,
            "channel_1": <WaveformData dict> or None,
            "channel_2": <WaveformData dict> or None}, matching
            OscilloscopeCaptureResponse exactly. Only the requested
            channel's key is populated -- the other is None.
            WaveformData keys: enabled, sample_rate, timebase,
            volts_per_div, offset, probe_ratio, num_points,
            time_array (list), voltage_array (list).
        """
        return self._post(
            "/v1/oscilloscope/capture",
            body={"channels": [channel]},
            token=token,
        )

    def capture_waveforms(
        self,
        token: str,
        channels: list[int],
    ) -> dict:
        """Capture waveforms from multiple oscilloscope channels in one request.

        Unlike calling capture_waveform() once per channel, this issues a
        single POST to /v1/oscilloscope/capture, so the server only opens
        and closes one instrument connection for the whole capture instead
        of one per channel (see the shared instrument_session() context
        manager in app/dependencies.py -- one connect/disconnect cycle
        wraps the entire request, capturing all requested channels inside
        it, rather than one cycle per channel).

        Args:
            token:    Session token.
            channels: Oscilloscope channels to capture, e.g. [1, 2].

        Returns:
            Same envelope shape as capture_waveform(): {"timestamp": str,
            "channel_1": <WaveformData dict> or None,
            "channel_2": <WaveformData dict> or None}. Both keys are
            populated if both channels were requested.
        """
        return self._post(
            "/v1/oscilloscope/capture",
            body={"channels": channels},
            token=token,
        )

    def configure_oscilloscope(
        self,
        token: str,
        channel: int,
        coupling: str | None = None,
        scale: float | None = None,
        offset: float | None = None,
        probe: int | None = None,
        timebase_scale: float | None = None,
        timebase_offset: float | None = None,
        trigger_source: int | None = None,
        trigger_level: float | None = None,
        trigger_slope: str | None = None,
        trigger_mode: str | None = None,
    ) -> dict:
        """Configure oscilloscope channel, timebase, and/or trigger settings.

        Args:
            token:           Session token.
            channel:         Channel to configure (1 or 2).
            coupling:        "DC", "AC", or "GND".
            scale:           Vertical scale in V/div.
            offset:          Vertical offset in V.
            probe:           Probe attenuation ratio, e.g. 10.
            timebase_scale:  Horizontal timebase in s/div.
            timebase_offset: Trigger delay offset in seconds.
            trigger_source:  Trigger source channel (1 or 2).
            trigger_level:   Trigger level in V.
            trigger_slope:   "POS", "NEG", or "WINDOW".
            trigger_mode:    "AUTO", "NORM", "SINGLE", or "STOP".

        Returns:
            {"ok": True} on success.
        """
        body: dict = {"channel": channel}
        if coupling is not None or scale is not None or offset is not None or probe is not None:
            body["channel_config"] = {
                "coupling": coupling,
                "scale": scale,
                "offset": offset,
                "probe": probe,
            }
        if timebase_scale is not None or timebase_offset is not None:
            body["timebase"] = {"scale": timebase_scale, "offset": timebase_offset}
        if trigger_source is not None or trigger_level is not None or trigger_slope is not None or trigger_mode is not None:
            body["trigger"] = {
                "source": trigger_source,
                "level": trigger_level,
                "slope": trigger_slope,
                "mode": trigger_mode,
            }
        return self._post("/v1/oscilloscope/configure", body=body, token=token)

    def oscilloscope_status(self, token: str) -> dict:
        """Return current oscilloscope timebase and trigger settings."""
        return self._get("/v1/oscilloscope/status", token=token)

    def screenshot(self, token: str) -> bytes:
        """Capture a screenshot of the oscilloscope's current display.

        Returns raw BMP image bytes -- the actual instrument display as an
        image, not a waveform data capture (see capture_waveform() for that).
        """
        return self._request("POST", "/v1/oscilloscope/screenshot", token=token, binary=True)

    # ------------------------------------------------------------------
    # Signal generator
    # ------------------------------------------------------------------

    def configure_signal(
        self,
        token: str,
        channel: int = 1,
        waveform: str = "SINE",
        freq_hz: float = 1000.0,
        amplitude_v: float = 1.0,
        offset_v: float = 0.0,
    ) -> dict:
        """Configure a signal generator channel.

        Args:
            token:       Session token.
            channel:     Output channel (1 or 2).
            waveform:    Waveform type: SINE, SQUARE, RAMP, PULSE, NOISE, DC.
            freq_hz:     Frequency in Hz.
            amplitude_v: Peak-to-peak amplitude in volts.
            offset_v:    DC offset in volts.

        Returns:
            Confirmed channel configuration from the instrument.
        """
        return self._post(
            "/v1/signal-generator/configure",
            body={
                "channel": channel,
                "waveform": waveform,
                "frequency": freq_hz,
                "amplitude": amplitude_v,
                "offset": offset_v,
            },
            token=token,
        )

    def enable_output(self, token: str, channel: int = 1, enabled: bool = True) -> dict:
        """Enable or disable a signal generator output channel."""
        return self._post(
            "/v1/signal-generator/output",
            body={"channel": channel, "enabled": enabled},
            token=token,
        )

    def signal_generator_status(self, token: str) -> dict:
        """Return current signal generator channel configurations."""
        return self._get("/v1/signal-generator/status", token=token)

    # ------------------------------------------------------------------
    # Power supply
    # ------------------------------------------------------------------

    def psu_status(self, token: str) -> dict:
        """Return measured voltage, current, and power for all channels."""
        return self._get("/v1/power-supply/status", token=token)

    def set_psu_channel(
        self,
        token: str,
        channel: int,
        voltage_v: float,
        current_limit_a: float,
    ) -> dict:
        """Set voltage and current limit on a power supply channel.

        Args:
            token:           Session token.
            channel:         Channel number (1, 2, or 3).
            voltage_v:       Target voltage in volts.
            current_limit_a: Current limit in amps.

        Returns:
            Confirmed channel settings from the instrument.
        """
        return self._post(
            "/v1/power-supply/configure",
            body={
                "channel": channel,
                "voltage": voltage_v,
                "current_limit": current_limit_a,
            },
            token=token,
        )

    def enable_psu_channel(self, token: str, channel: int, enabled: bool = True) -> dict:
        """Enable or disable a power supply output channel."""
        return self._post(
            "/v1/power-supply/output",
            body={"channel": channel, "enabled": enabled},
            token=token,
        )

    # ------------------------------------------------------------------
    # Multimeter
    # ------------------------------------------------------------------

    def measure(self, token: str, mode: str = "VOLT:DC", range_: str = "AUTO") -> dict:
        """Take a single measurement.

        Args:
            token:  Session token.
            mode:   Measurement mode: VOLT:DC, VOLT:AC, CURR:DC, CURR:AC, RES, FRES,
                    FREQ, CONT, DIOD, CAP.
            range_: Measurement range or AUTO.

        Returns:
            Dict with keys: mode, value, unit, timestamp.
        """
        return self._post(
            "/v1/multimeter/measure",
            body={"mode": mode, "range": range_},
            token=token,
        )

    def multimeter_status(self, token: str) -> dict:
        """Return current multimeter mode, range, and resolution."""
        return self._get("/v1/multimeter/status", token=token)

    def log_measurements(
        self,
        token: str,
        mode: str = "VOLT:DC",
        duration_s: int = 10,
        interval_s: float = 1.0,
    ) -> dict:
        """Run a timed measurement log.

        Args:
            token:      Session token.
            mode:       Measurement mode (see measure()).
            duration_s: Total logging duration in seconds.
            interval_s: Interval between readings in seconds.

        Returns:
            Dict with log_id, mode, unit, count, readings list,
            and statistics (min, max, mean, std_dev).
        """
        return self._post(
            "/v1/multimeter/log",
            body={
                "mode": mode,
                "duration_seconds": duration_s,
                "interval_seconds": interval_s,
            },
            token=token,
        )

    def get_log_csv_url(self, log_id: str) -> str:
        """Return the URL to download a measurement log as CSV.

        The URL can be opened in a browser or fetched with requests/urllib.
        No session token is required for CSV download.
        """
        return f"{self._base}/v1/multimeter/log/{log_id}/csv"

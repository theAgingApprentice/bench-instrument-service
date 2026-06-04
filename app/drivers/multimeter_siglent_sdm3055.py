import math
import time
from datetime import datetime, timezone

from app.drivers.base import BaseInstrumentDriver

VALID_MODES = {
    "VOLT:DC", "VOLT:AC", "CURR:DC", "CURR:AC",
    "RES", "FRES", "FREQ", "CONT", "DIOD", "CAP",
}

# Unit returned for each measurement mode.
_MODE_UNITS = {
    "VOLT:DC": "V",  "VOLT:AC": "V",
    "CURR:DC": "A",  "CURR:AC": "A",
    "RES": "Ω",      "FRES": "Ω",
    "FREQ": "Hz",    "CONT": "Ω",
    "DIOD": "V",     "CAP": "F",
}


class MultimeterSiglentSDM3055(BaseInstrumentDriver):
    """Driver for the Siglent SDM3055 digital multimeter.

    Communicates via standard LXI/SCPI over TCP port 5025.
    Resource string: TCPIP::{ip}::INSTR
    """

    def __init__(self, ip: str, timeout_ms: int = 5000):
        super().__init__(ip, timeout_ms=timeout_ms)

    # ------------------------------------------------------------------
    # BaseInstrumentDriver interface
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        """Return current measurement mode, range, and resolution."""
        raw = self.query("CONF?").strip()
        # Response: 'VOLT:DC +1.000000E+01,+1.000000E-06' or 'VOLT:DC AUTO,DEF'
        parts = raw.split()
        mode = parts[0] if parts else "UNKNOWN"
        range_str = "AUTO"
        if len(parts) > 1:
            range_field = parts[1].split(",")[0]
            # Numeric range → format it; AUTO → keep as-is.
            try:
                range_str = str(float(range_field))
            except ValueError:
                range_str = range_field.upper()
        return {"mode": mode, "range": range_str, "resolution": "HIGH"}

    # ------------------------------------------------------------------
    # Public instrument operations
    # ------------------------------------------------------------------

    def measure(self, mode: str, range_val: str = "AUTO") -> dict:
        """Configure and take a single measurement. Returns value, unit, timestamp."""
        mode = mode.upper()
        self._validate_mode(mode)
        # MEAS:{mode}? {range} configures and measures in one command.
        raw = self.query(f"MEAS:{mode}? {range_val}")
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode": mode,
            "value": float(raw),
            "unit": _MODE_UNITS[mode],
        }

    def log_measurements(
        self,
        mode: str,
        duration_seconds: float,
        interval_seconds: float,
    ) -> dict:
        """Take repeated measurements and return results with statistics.

        Configures the instrument once, then calls READ? on each interval tick.
        Runs synchronously — the caller blocks for duration_seconds.
        """
        mode = mode.upper()
        self._validate_mode(mode)
        unit = _MODE_UNITS[mode]

        self.write(f"CONF:{mode} AUTO")

        readings = []
        deadline = time.monotonic() + duration_seconds
        while time.monotonic() < deadline:
            tick_start = time.monotonic()
            value = float(self.query("READ?"))
            readings.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "value": value,
            })
            elapsed = time.monotonic() - tick_start
            remaining_sleep = interval_seconds - elapsed
            if remaining_sleep > 0:
                time.sleep(remaining_sleep)

        values = [r["value"] for r in readings]
        return {
            "mode": mode,
            "unit": unit,
            "count": len(readings),
            "readings": readings,
            "statistics": _statistics(values),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_mode(mode: str):
        if mode not in VALID_MODES:
            raise ValueError(f"Unsupported mode {mode!r} — valid modes: {sorted(VALID_MODES)}")


def _statistics(values: list[float]) -> dict:
    """Compute min, max, mean, and population std_dev over a list of floats."""
    if not values:
        return {"min": 0.0, "max": 0.0, "mean": 0.0, "std_dev": 0.0}
    n = len(values)
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n
    return {
        "min": min(values),
        "max": max(values),
        "mean": mean,
        "std_dev": math.sqrt(variance),
    }

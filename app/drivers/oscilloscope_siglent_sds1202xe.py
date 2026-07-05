import re

from app.drivers.base import BaseInstrumentDriver

_CHANNELS = (1, 2)

# Siglent SI-prefix multipliers used in SCPI response strings.
_SI_MULTIPLIERS = {
    "G": 1e9, "M": 1e6, "k": 1e3, "K": 1e3,
    "m": 1e-3, "u": 1e-6, "µ": 1e-6, "n": 1e-9, "p": 1e-12,
}


def _parse_siglent_value(response: str) -> float:
    """Parse Siglent SCPI response values that include command echo and SI units.

    Examples:
        "C1:VDIV 500.00mV"  → 0.5
        "TDIV 1.00ms"       → 0.001
        "C1:SARA 1.00GSa/s" → 1e9
        "C1:ATTN 10"        → 10.0
    """
    token = response.strip().split()[-1]
    m = re.match(r"^([+-]?\d+\.?\d*(?:[eE][+-]?\d+)?)([GMkKmuµnp]?)", token)
    if not m:
        return float(token)
    return float(m.group(1)) * _SI_MULTIPLIERS.get(m.group(2), 1.0)


def _parse_coupling(response: str) -> str:
    """Extract coupling type from Siglent CPL response.

    "C1:CPL D1M" → "DC"
    "C1:CPL A1M" → "AC"
    "C1:CPL GND" → "GND"
    """
    token = response.strip().split()[-1]
    if token.startswith("D"):
        return "DC"
    if token.startswith("A"):
        return "AC"
    return "GND"


def _parse_trigger_source(response: str) -> int:
    """Parse a TRSE? response like 'TRSE EDGE,SR,C1,HT,OFF' and return the channel number."""
    for part in response.strip().split(","):
        part = part.strip().upper()
        if part.startswith("C") and part[1:].isdigit():
            return int(part[1:])
    raise ValueError(f"Could not parse trigger source from: {response!r}")


def _strip_ieee_block_header(raw: bytes) -> bytes:
    """Strip IEEE 488.2 definite-length block header from a binary response.

    Header format: ...#<n><N-digit byte count><data>
    The leading bytes before '#' are the SCPI echo (e.g. "C1:WF DAT2,").
    """
    idx = raw.find(b"#")
    if idx == -1:
        return raw
    n_digits = int(chr(raw[idx + 1]))
    byte_count = int(raw[idx + 2: idx + 2 + n_digits])
    data_start = idx + 2 + n_digits
    return raw[data_start: data_start + byte_count]


class OscilloscopeSiglentSDS1202XE(BaseInstrumentDriver):
    """Driver for the Siglent SDS1202X-E two-channel oscilloscope.

    Communicates via standard LXI/SCPI over TCP port 5025.
    Resource string: TCPIP::{ip}::INSTR
    """

    def __init__(self, ip: str, timeout_ms: int = 5000):
        super().__init__(ip, timeout_ms=timeout_ms)

    # ------------------------------------------------------------------
    # BaseInstrumentDriver interface
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        """Return channel settings for both channels plus timebase and trigger."""
        return {
            "channel_1": self._channel_status(1),
            "channel_2": self._channel_status(2),
            "timebase": self._timebase_status(),
            "trigger": self.trigger_status(),
        }

    # ------------------------------------------------------------------
    # Public instrument operations
    # ------------------------------------------------------------------

    def configure_channel(
        self,
        channel: int,
        coupling: str | None = None,
        scale: float | None = None,
        offset: float | None = None,
        probe: int | None = None,
    ):
        """Set channel parameters. Only supplied arguments are changed."""
        self._validate_channel(channel)
        ch = f"C{channel}"
        if coupling is not None:
            _coupling_wire_values = {"DC": "D1M", "AC": "A1M", "GND": "GND"}
            if coupling not in _coupling_wire_values:
                raise ValueError(f"Invalid coupling {coupling!r} — must be DC, AC, or GND")
            self.write(f"{ch}:CPL {_coupling_wire_values[coupling]}")
        if scale is not None:
            self.write(f"{ch}:VDIV {scale}V")
        if offset is not None:
            self.write(f"{ch}:OFST {offset}V")
        if probe is not None:
            self.write(f"{ch}:ATTN {probe}")

    def configure_timebase(self, scale: float | None = None, offset: float | None = None):
        """Set timebase scale (s/div) and/or trigger delay offset."""
        if scale is not None:
            self.write(f"TDIV {scale}S")
        if offset is not None:
            self.write(f"TRDL {offset}S")

    def configure_trigger(
        self,
        source: int | None = None,
        level: float | None = None,
        slope: str | None = None,
        mode: str | None = None,
    ):
        """Set trigger source/level/slope/mode. Only supplied arguments are changed."""
        if source is not None:
            self._validate_channel(source)
            self.write(f"TRSE EDGE,SR,C{source}")
            if level is not None:
                self.write(f"C{source}:TRLV {level}V")
            if slope is not None:
                self.write(f"C{source}:TRSL {slope}")
        if mode is not None:
            self.write(f"TRMD {mode}")

    def capture_waveform(self, channel: int) -> dict:
        """Capture waveform data from one channel and return scaled arrays."""
        self._validate_channel(channel)
        ch = f"C{channel}"

        vdiv = _parse_siglent_value(self.query(f"{ch}:VDIV?"))
        ofst = _parse_siglent_value(self.query(f"{ch}:OFST?"))
        tdiv = _parse_siglent_value(self.query("TDIV?"))
        probe = int(_parse_siglent_value(self.query(f"{ch}:ATTN?")))
        sara = _parse_siglent_value(self.query(f"{ch}:SARA?"))

        # Request raw ADC data — response is IEEE 488.2 block preceded by echo.
        self._resource.write(f"{ch}:WF? DAT2")
        raw = self._resource.read_raw()
        data = _strip_ieee_block_header(raw)

        num_points = len(data)
        time_step = 1.0 / sara if sara > 0 else (tdiv * 14 / max(num_points, 1))
        half_window = num_points / 2 * time_step

        # SDS1202X-E ADC codes are signed bytes; voltage = code * (vdiv/25) - ofst
        voltage_array = [
            int.from_bytes(bytes([b]), byteorder="big", signed=True) * (vdiv / 25.0) - ofst
            for b in data
        ]
        time_array = [i * time_step - half_window for i in range(num_points)]

        return {
            "enabled": True,
            "sample_rate": sara,
            "timebase": tdiv,
            "volts_per_div": vdiv,
            "offset": ofst,
            "probe_ratio": probe,
            "num_points": num_points,
            "time_array": time_array,
            "voltage_array": voltage_array,
        }

    def screenshot(self) -> bytes:
        """Capture a screenshot from the display. Returns raw BMP bytes."""
        self._resource.write("SCDP")
        return self._resource.read_raw()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _channel_status(self, channel: int) -> dict:
        ch = f"C{channel}"
        trace = self.query(f"{ch}:TRA?").strip().split()[-1].upper()
        return {
            "enabled": trace == "ON",
            "coupling": _parse_coupling(self.query(f"{ch}:CPL?")),
            "scale": _parse_siglent_value(self.query(f"{ch}:VDIV?")),
            "offset": _parse_siglent_value(self.query(f"{ch}:OFST?")),
            "probe": int(_parse_siglent_value(self.query(f"{ch}:ATTN?"))),
        }

    def _timebase_status(self) -> dict:
        return {
            "scale": _parse_siglent_value(self.query("TDIV?")),
            "offset": _parse_siglent_value(self.query("TRDL?")),
        }

    def trigger_status(self) -> dict:
        source = _parse_trigger_source(self.query("TRSE?"))
        ch = f"C{source}"
        return {
            "source": source,
            "mode": self.query("TRMD?").strip().split()[-1].upper(),
            "level": _parse_siglent_value(self.query(f"{ch}:TRLV?")),
            "slope": self.query(f"{ch}:TRSL?").strip().split()[-1].upper(),
        }

    @staticmethod
    def _validate_channel(channel: int):
        if channel not in _CHANNELS:
            raise ValueError(f"Invalid channel {channel!r} — must be 1 or 2")

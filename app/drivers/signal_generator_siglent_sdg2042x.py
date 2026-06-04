import re

from app.drivers.base import BaseInstrumentDriver

_CHANNELS = (1, 2)

VALID_WAVEFORMS = {"SINE", "SQUARE", "RAMP", "PULSE", "NOISE", "ARB", "DC"}

# SI multipliers that appear in SDG2042X response values (e.g. "1000HZ", "2V", "0.001S").
_SI_MULTIPLIERS = {
    "G": 1e9, "M": 1e6, "K": 1e3, "k": 1e3,
    "m": 1e-3, "u": 1e-6, "µ": 1e-6, "n": 1e-9,
}


def _parse_bswv_value(s: str) -> float:
    """Parse numeric BSWV field values that carry optional SI prefix and unit suffix.

    Examples: "1000HZ" → 1000.0,  "2V" → 2.0,  "0.001S" → 0.001,  "50" → 50.0
    """
    s = s.strip()
    m = re.match(r"^([+-]?\d+\.?\d*(?:[eE][+-]?\d+)?)([GMKkmuµn]?)", s)
    if not m:
        return float(s)
    return float(m.group(1)) * _SI_MULTIPLIERS.get(m.group(2), 1.0)


def _parse_bswv_response(response: str) -> dict:
    """Parse the SDG2042X BSWV query response into a key→value dict.

    Response format (after stripping command echo):
        WVTP,SINE,FRQ,1000HZ,PERI,0.001S,AMP,2V,OFST,0V,HLEV,1V,LLEV,-1V,PHSE,0

    Returns a plain-string dict; callers convert numeric fields as needed.
    """
    # Strip leading echo e.g. "C1:BSWV " before the payload.
    payload = response.strip().split(" ", 1)[-1]
    tokens = [t.strip() for t in payload.split(",")]
    # Pair up alternating key, value tokens.
    return {tokens[i]: tokens[i + 1] for i in range(0, len(tokens) - 1, 2)}


class SignalGeneratorSiglentSDG2042X(BaseInstrumentDriver):
    """Driver for the Siglent SDG2042X two-channel signal generator.

    Communicates via standard LXI/SCPI over TCP port 5025.
    Resource string: TCPIP::{ip}::INSTR
    """

    def __init__(self, ip: str, timeout_ms: int = 5000):
        super().__init__(ip, timeout_ms=timeout_ms)

    # ------------------------------------------------------------------
    # BaseInstrumentDriver interface
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        """Return current output configuration for both channels."""
        return {f"channel_{ch}": self._channel_status(ch) for ch in _CHANNELS}

    # ------------------------------------------------------------------
    # Public instrument operations
    # ------------------------------------------------------------------

    def configure_channel(
        self,
        channel: int,
        waveform: str | None = None,
        frequency: float | None = None,
        amplitude: float | None = None,
        offset: float | None = None,
        duty_cycle: float | None = None,
        phase: float | None = None,
        output: bool | None = None,
    ):
        """Configure one channel. Only supplied arguments are written to the instrument."""
        self._validate_channel(channel)
        ch = f"C{channel}"

        if waveform is not None:
            waveform = waveform.upper()
            if waveform not in VALID_WAVEFORMS:
                raise ValueError(f"Unsupported waveform {waveform!r}")
            self.write(f"{ch}:BSWV WVTP,{waveform}")

        if frequency is not None:
            self.write(f"{ch}:BSWV FRQ,{frequency}")

        if amplitude is not None:
            self.write(f"{ch}:BSWV AMP,{amplitude}")

        if offset is not None:
            self.write(f"{ch}:BSWV OFST,{offset}")

        if duty_cycle is not None:
            self.write(f"{ch}:BSWV DUTY,{duty_cycle}")

        if phase is not None:
            self.write(f"{ch}:BSWV PHSE,{phase}")

        if output is not None:
            self.set_output(channel, output)

    def set_output(self, channel: int, enabled: bool):
        """Enable or disable channel output without changing other settings."""
        self._validate_channel(channel)
        state = "ON" if enabled else "OFF"
        self.write(f"C{channel}:OUTP {state}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _channel_status(self, channel: int) -> dict:
        ch = f"C{channel}"

        outp_resp = self.query(f"{ch}:OUTP?").strip().split()
        # Response: "C1:OUTP ON,LOAD,HZ,PLRT,NOR" — second token, first comma-delimited field.
        output_enabled = outp_resp[-1].split(",")[0].upper() == "ON"

        fields = _parse_bswv_response(self.query(f"{ch}:BSWV?"))

        return {
            "output_enabled": output_enabled,
            "waveform": fields.get("WVTP", "SINE"),
            "frequency": _parse_bswv_value(fields["FRQ"]) if "FRQ" in fields else 0.0,
            "amplitude": _parse_bswv_value(fields["AMP"]) if "AMP" in fields else 0.0,
            "offset": _parse_bswv_value(fields["OFST"]) if "OFST" in fields else 0.0,
            "duty_cycle": _parse_bswv_value(fields["DUTY"]) if "DUTY" in fields else 50.0,
            "phase": _parse_bswv_value(fields["PHSE"]) if "PHSE" in fields else 0.0,
        }

    @staticmethod
    def _validate_channel(channel: int):
        if channel not in _CHANNELS:
            raise ValueError(f"Invalid channel {channel!r} — must be 1 or 2")

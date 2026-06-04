from app.drivers.base import BaseInstrumentDriver

_CHANNELS = (1, 2, 3)


class PowerSupplyRigolDP832(BaseInstrumentDriver):
    """Driver for the Rigol DP832 three-channel power supply.

    Uses raw socket mode on port 5555 — not the standard LXI port 5025.
    Resource string: TCPIP::{ip}::5555::SOCKET
    """

    def __init__(self, ip: str, timeout_ms: int = 5000):
        super().__init__(ip, port=5555, timeout_ms=timeout_ms)

    def _resource_string(self) -> str:
        return f"TCPIP::{self.ip}::5555::SOCKET"

    def connect(self) -> bool:
        connected = super().connect()
        if connected:
            # Raw SOCKET resources require explicit line termination.
            self._resource.read_termination = "\n"
            self._resource.write_termination = "\n"
        return connected

    # ------------------------------------------------------------------
    # BaseInstrumentDriver interface
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        """Return measured and set-point values for all three channels."""
        return {f"channel_{ch}": self._channel_status(ch) for ch in _CHANNELS}

    # ------------------------------------------------------------------
    # Public instrument operations
    # ------------------------------------------------------------------

    def configure_channel(self, channel: int, voltage: float, current_limit: float):
        """Set voltage set-point and current limit for one channel."""
        self._validate_channel(channel)
        self.write(f":SOUR{channel}:VOLT {voltage:.4f}")
        self.write(f":SOUR{channel}:CURR {current_limit:.4f}")

    def set_output(self, channel: int, enabled: bool):
        """Enable or disable one channel's output."""
        self._validate_channel(channel)
        state = "ON" if enabled else "OFF"
        self.write(f":OUTP CH{channel},{state}")

    def all_off(self):
        """Disable all three channel outputs immediately."""
        self.write(":OUTP:ALL OFF")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _channel_status(self, channel: int) -> dict:
        return {
            "output_enabled": self.query(f":OUTP? CH{channel}").upper() == "ON",
            "voltage_set": float(self.query(f":SOUR{channel}:VOLT?")),
            "current_limit": float(self.query(f":SOUR{channel}:CURR?")),
            "voltage_actual": float(self.query(f":MEAS:VOLT? CH{channel}")),
            "current_actual": float(self.query(f":MEAS:CURR? CH{channel}")),
            "power_actual": float(self.query(f":MEAS:POWE? CH{channel}")),
        }

    @staticmethod
    def _validate_channel(channel: int):
        if channel not in _CHANNELS:
            raise ValueError(f"Invalid channel {channel!r} — must be 1, 2, or 3")

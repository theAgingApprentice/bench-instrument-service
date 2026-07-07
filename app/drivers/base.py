from abc import ABC, abstractmethod
import threading
import pyvisa

from app.services.command_logger import command_logger


class BaseInstrumentDriver(ABC):
    """Abstract base class for all instrument drivers."""

    def __init__(self, ip: str, port: int = 5025, timeout_ms: int = 5000):
        self.ip = ip
        self.port = port
        self.timeout_ms = timeout_ms
        self._rm = pyvisa.ResourceManager('@py')
        self._resource = None
        self._lock = threading.Lock()

    def connect(self) -> bool:
        """Open VISA connection. Returns True if successful."""
        try:
            resource_string = self._resource_string()
            self._resource = self._rm.open_resource(resource_string)
            # Siglent programming guide: 500k+ recommended chunk size for
            # WF?/PNSU? block transfers, and a timeout floor of 10s for the
            # same large-block reads.
            self._resource.chunk_size = 500000
            self._resource.timeout = max(self.timeout_ms, 10000)
            return True
        except Exception:
            self._resource = None
            return False

    def _resource_string(self) -> str:
        """Build the PyVISA resource string. Override for non-standard connections."""
        return f"TCPIP::{self.ip}::INSTR"

    def disconnect(self):
        if self._resource:
            self._resource.close()
            self._resource = None

    def query(self, command: str) -> str:
        """Send command and read response."""
        if not self._resource:
            raise RuntimeError("Not connected")
        raw_response = self._resource.query(command)
        response = raw_response.strip()
        command_logger.log_query(type(self).__name__, self.ip, command, response)
        return response

    def write(self, command: str):
        """Send command with no response expected."""
        if not self._resource:
            raise RuntimeError("Not connected")
        self._resource.write(command)
        command_logger.log_write(type(self).__name__, self.ip, command)

    def identify(self) -> str:
        """Query *IDN? and return identity string."""
        return self.query("*IDN?")

    def is_reachable(self) -> bool:
        """Attempt connection and IDN query. Returns True if instrument responds."""
        try:
            connected = self.connect()
            if connected:
                self.identify()
                return True
        except Exception:
            pass
        finally:
            self.disconnect()
        return False

    @abstractmethod
    def get_status(self) -> dict:
        """Return current instrument status as a dict."""
        ...

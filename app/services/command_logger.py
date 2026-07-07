"""SCPI command logger.

Every query() and write() call made by any driver is recorded here with:
  - timestamp (UTC ISO-8601)
  - instrument class name and IP
  - client IP (set per-request via set_client_ip())
  - the command sent
  - the response received (queries only)

Client IP flows in via a contextvars.ContextVar so it propagates naturally
through FastAPI's async/sync request handling without explicit threading.

Usage in middleware / dependencies:
    token = command_logger.set_client_ip(request.client.host)
    try:
        ...
    finally:
        command_logger.reset_client_ip(token)
"""

import contextvars
import logging
# TEMP DIAGNOSTIC — remove before merging real fix
import time
# END TEMP DIAGNOSTIC

_scpi_logger = logging.getLogger("bis.scpi")

# Holds the HTTP client IP for the duration of one request.
_client_ip_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "client_ip", default="unknown"
)


class CommandLogger:
    """Records every SCPI command dispatched through the driver layer."""

    def log_write(self, instrument: str, ip: str, command: str) -> None:
        """Record a write command (no response expected)."""
        _scpi_logger.info(
            "WRITE instrument=%s ip=%s client=%s command=%r",
            instrument, ip, _client_ip_var.get(), command,
        )

    def log_query(self, instrument: str, ip: str, command: str, response: str) -> None:
        """Record a query command and its response."""
        # TEMP DIAGNOSTIC — remove before merging real fix
        _diag_ctx_client = _client_ip_var.get()
        _diag_t = time.monotonic()
        # END TEMP DIAGNOSTIC
        _scpi_logger.info(
            "QUERY instrument=%s ip=%s client=%s command=%r response=%r",
            instrument, ip, _client_ip_var.get(), command, response,
        )
        # TEMP DIAGNOSTIC — remove before merging real fix
        _scpi_logger.info(
            "DIAG log_query t=%.6f ctx_client=%s",
            _diag_t, _diag_ctx_client,
        )
        # END TEMP DIAGNOSTIC

    # ------------------------------------------------------------------
    # Client context management
    # ------------------------------------------------------------------

    @staticmethod
    def set_client_ip(ip: str) -> contextvars.Token:
        """Set the client IP for the current request context. Returns a reset token."""
        return _client_ip_var.set(ip)

    @staticmethod
    def reset_client_ip(token: contextvars.Token) -> None:
        """Restore the previous client IP value using the token from set_client_ip().

        Falls back to set("unknown") when the token was created in a different async
        context (stacked FastAPI dependencies can run setup and teardown in separate
        context copies, making reset() raise ValueError).
        """
        try:
            _client_ip_var.reset(token)
        except ValueError:
            _client_ip_var.set("unknown")


# Module-level singleton used by BaseInstrumentDriver and middleware.
command_logger = CommandLogger()

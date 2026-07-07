"""FastAPI dependency injection helpers.

Provides:
    get_instrument_registry — yields the InstrumentRegistry singleton and sets
                              the per-request client IP context for the command logger.
    instrument_session      — context manager that connects a named driver for one
                              operation and always disconnects on exit.
"""

import hmac
import logging
import os
from contextlib import contextmanager
from typing import Generator, Optional

from fastapi import Header, HTTPException, Request, Security
from fastapi.security.api_key import APIKeyHeader

from app.services.command_logger import command_logger
from app.services.instrument_registry import InstrumentRegistry, get_registry
from app.services.session_manager import SessionInfo, session_manager

logger = logging.getLogger(__name__)


def get_instrument_registry(request: Request) -> Generator[InstrumentRegistry, None, None]:
    """FastAPI dependency — yields the registry and manages client IP context."""
    client_ip = request.client.host if request.client else "unknown"
    token = command_logger.set_client_ip(client_ip)
    try:
        yield get_registry()
    finally:
        command_logger.reset_client_ip(token)


def check_session(
    x_session_id: Optional[str] = Header(default=None),
) -> Optional[SessionInfo]:
    """Validate an optional X-Session-ID header against the active session.

    Passes through if no session is active (open access).
    Raises 423 if a session is held by someone else.
    """
    return session_manager.validate(x_session_id or "")


@contextmanager
def instrument_session(registry: InstrumentRegistry, name: str):
    """Connect a named instrument driver for one operation, then always disconnect.

    Raises:
        HTTPException 500 — if no driver is registered for the name (bug, not user error).
        HTTPException 503 — if the instrument cannot be connected (powered off, network down).
    """
    driver = registry.get_driver(name)
    if driver is None:
        logger.error("No driver registered for instrument '%s'", name)
        raise HTTPException(status_code=500, detail="Instrument unavailable")

    entry = registry.get_entry(name)
    ip = entry.ip if entry else "unknown"

    # Hold driver._lock for the whole connect/operate/disconnect span so the
    # background discover() health-check poll (main.py's 30s task, running on
    # the asyncio event loop thread) can't reconnect this instrument out from
    # under a request handler mid-operation (FastAPI sync-route thread pool).
    # Discovered via live diagnostic logging 7 July 2026 — see roadmap §4.7.
    with driver._lock:
        try:
            connected = driver.connect()
            if not connected:
                raise HTTPException(
                    status_code=503,
                    detail="Instrument unavailable — check power and network",
                )
            yield driver
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("Instrument connection error for '%s': %s", name, exc, exc_info=True)
            raise HTTPException(status_code=503, detail="Instrument unavailable") from exc
        finally:
            try:
                driver.disconnect()
            except Exception:
                pass


_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(api_key: str = Security(_api_key_header)) -> None:
    """Reject requests that do not carry a valid X-API-Key header."""
    expected = os.environ.get("API_KEY", "")
    if not expected:
        raise HTTPException(status_code=500, detail="Server misconfiguration")
    if not api_key or not hmac.compare_digest(api_key, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")

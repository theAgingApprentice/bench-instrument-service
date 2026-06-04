"""FastAPI dependency injection helpers.

Provides:
    get_instrument_registry — yields the InstrumentRegistry singleton and sets
                              the per-request client IP context for the command logger.
    instrument_session      — context manager that connects a named driver for one
                              operation and always disconnects on exit.
"""

from contextlib import contextmanager
from typing import Generator

from fastapi import HTTPException, Request

from app.services.command_logger import command_logger
from app.services.instrument_registry import InstrumentRegistry, get_registry


def get_instrument_registry(request: Request) -> Generator[InstrumentRegistry, None, None]:
    """FastAPI dependency — yields the registry and manages client IP context."""
    client_ip = request.client.host if request.client else "unknown"
    token = command_logger.set_client_ip(client_ip)
    try:
        yield get_registry()
    finally:
        command_logger.reset_client_ip(token)


@contextmanager
def instrument_session(registry: InstrumentRegistry, name: str):
    """Connect a named instrument driver for one operation, then always disconnect.

    Raises:
        HTTPException 500 — if no driver is registered for the name (bug, not user error).
        HTTPException 503 — if the instrument cannot be connected (powered off, network down).
    """
    driver = registry.get_driver(name)
    if driver is None:
        raise HTTPException(status_code=500, detail=f"No driver registered for '{name}'")

    entry = registry.get_entry(name)
    ip = entry.ip if entry else "unknown"

    try:
        connected = driver.connect()
        if not connected:
            raise HTTPException(
                status_code=503,
                detail=f"{name} ({ip}) is not reachable — instrument may be powered off",
            )
        yield driver
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        try:
            driver.disconnect()
        except Exception:
            pass

"""Bench Instrument Service — FastAPI application entry point.

Startup sequence (Section 6 of BIS_Implementation_Blueprint.md):
  1. Configure logging
  2. Load settings from environment variables (pydantic-settings, app/config.py)
  3. Initialise instrument registry
  4. Probe all four instruments via *IDN? (if BIS_DISCOVER_ON_STARTUP=true)
  5. Begin serving requests

Unreachable instruments are not a startup failure — the service starts
normally and reports them as unreachable via GET /health.
"""

import json
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.dependencies import verify_api_key
from app.routers import (
    health,
    instruments,
    multimeter,
    oscilloscope,
    power_supply,
    sessions,
    signal_generator,
)
from app.services import instrument_registry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

class _JsonFormatter(logging.Formatter):
    """Single-line JSON log records — easy to ingest with Loki / Grafana."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def _configure_logging(log_level: str) -> None:
    level = getattr(logging, log_level.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # pyvisa is chatty at DEBUG; keep it at WARNING unless explicitly overridden.
    logging.getLogger("pyvisa").setLevel(max(level, logging.WARNING))


# ---------------------------------------------------------------------------
# Application lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_logging(settings.log_level)

    logger.info(
        "BIS starting — oscilloscope=%s signal_generator=%s multimeter=%s power_supply=%s",
        settings.oscilloscope_ip,
        settings.signal_generator_ip,
        settings.multimeter_ip,
        settings.power_supply_ip,
    )

    registry = instrument_registry.initialise(settings)

    if settings.discover_on_startup:
        logger.info("Running instrument discovery on startup")
        registry.discover()
    else:
        logger.info("Skipping startup discovery (BIS_DISCOVER_ON_STARTUP=false)")

    logger.info("BIS ready — health_status=%s", registry.health_status)

    yield

    logger.info("BIS shutting down")


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Bench Instrument Service",
    root_path="/api/bench",
    description=(
        "REST API that abstracts four LXI/Ethernet bench instruments behind a clean "
        "HTTP interface. See /docs for the full OpenAPI specification."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://192.168.2.10",
        "https://mitchellnet.local",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Health endpoint — unprotected
app.include_router(health.router)

# All instrument routers require API key auth
_auth = [Depends(verify_api_key)]
app.include_router(sessions.router,         dependencies=_auth)
app.include_router(instruments.router,      dependencies=_auth)
app.include_router(oscilloscope.router,     dependencies=_auth)
app.include_router(signal_generator.router, dependencies=_auth)
app.include_router(multimeter.router,       dependencies=_auth)
app.include_router(power_supply.router,     dependencies=_auth)

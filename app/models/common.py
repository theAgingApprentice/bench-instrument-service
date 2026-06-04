from typing import Optional

from pydantic import BaseModel


class InstrumentInfo(BaseModel):
    reachable: bool
    ip: str
    identity: Optional[str] = None


class HealthResponse(BaseModel):
    status: str  # "ok" | "degraded"
    uptime_seconds: float
    instruments: dict[str, InstrumentInfo]


class InstrumentsResponse(BaseModel):
    instruments: dict[str, InstrumentInfo]


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None

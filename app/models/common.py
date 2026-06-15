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


class SessionInfo(BaseModel):
    session_id: str
    client_id: str
    expires_at: str

class HealthFullResponse(BaseModel):
    status: str  # "ok" | "degraded"
    uptime_seconds: float
    instruments: dict[str, InstrumentInfo]
    session: Optional[SessionInfo] = None

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel


class SessionInfo(BaseModel):
    session_id: str
    client_ip: str
    acquired_at: datetime
    expires_at: datetime


class SessionManager:
    def __init__(self, timeout_seconds: int = 300):
        self._timeout = timeout_seconds
        self._session: Optional[SessionInfo] = None

    def acquire(self, client_ip: str) -> SessionInfo:
        if self._session is not None:
            if datetime.now(timezone.utc) < self._session.expires_at:
                raise HTTPException(status_code=409, detail="A session is already active")
            self._session = None

        now = datetime.now(timezone.utc)
        session = SessionInfo(
            session_id=str(uuid.uuid4()),
            client_ip=client_ip,
            acquired_at=now,
            expires_at=now + timedelta(seconds=self._timeout),
        )
        self._session = session
        return session

    def release(self, session_id: str) -> bool:
        if self._session is None or self._session.session_id != session_id:
            return False
        self._session = None
        return True

    def validate(self, session_id: str) -> Optional[SessionInfo]:
        if self._session is None:
            return None

        now = datetime.now(timezone.utc)
        if now >= self._session.expires_at:
            self._session = None
            return None

        if self._session.session_id != session_id:
            raise HTTPException(
                status_code=423,
                detail={"expires_at": self._session.expires_at.isoformat()},
            )

        return self._session

    def keepalive(self, session_id: str) -> SessionInfo:
        if self._session is None:
            raise HTTPException(status_code=404, detail="Session not found")

        now = datetime.now(timezone.utc)
        if now >= self._session.expires_at:
            self._session = None
            raise HTTPException(status_code=404, detail="Session not found or expired")

        if self._session.session_id != session_id:
            raise HTTPException(status_code=404, detail="Session not found")

        self._session = self._session.model_copy(
            update={"expires_at": now + timedelta(seconds=self._timeout)}
        )
        return self._session

    @property
    def current(self) -> Optional[SessionInfo]:
        if self._session is None:
            return None
        if datetime.now(timezone.utc) >= self._session.expires_at:
            self._session = None
        return self._session


def _make_session_manager() -> SessionManager:
    try:
        from app.config import settings
        timeout = getattr(settings, "session_timeout_seconds", 300)
    except Exception:
        timeout = 300
    return SessionManager(timeout_seconds=timeout)


session_manager = _make_session_manager()

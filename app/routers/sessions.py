from fastapi import APIRouter, HTTPException, Request

from app.services.session_manager import SessionInfo, session_manager

router = APIRouter(prefix="/v1/sessions", tags=["Sessions"])


@router.post("/acquire", response_model=SessionInfo, status_code=201)
def acquire(request: Request):
    """Reserve exclusive access to all instruments. Returns a session token."""
    client_ip = request.client.host if request.client else "unknown"
    return session_manager.acquire(client_ip)


@router.delete("/{session_id}", status_code=204)
def release(session_id: str):
    """Release an active session. Returns 404 if the session ID is not found."""
    if not session_manager.release(session_id):
        raise HTTPException(status_code=404, detail="Session not found")


@router.put("/{session_id}/keepalive", response_model=SessionInfo)
def keepalive(session_id: str):
    """Reset the session expiry timer. Returns 404 if not found or already expired."""
    return session_manager.keepalive(session_id)


@router.get("/status")
def status():
    """Return the current session or {"active": false} if none is held."""
    current = session_manager.current
    if current is None:
        return {"active": False}
    return current

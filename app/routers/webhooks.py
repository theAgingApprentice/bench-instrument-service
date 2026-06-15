"""Webhook registration endpoints.

POST   /v1/webhooks          — register a URL + event filter
GET    /v1/webhooks          — list all registrations
DELETE /v1/webhooks/{id}     — remove a registration
"""

from fastapi import APIRouter, HTTPException
from app.models.webhook import WebhookRegistration, WebhookRegistrationRequest
from app.services.webhook_manager import webhook_manager

router = APIRouter(prefix="/v1/webhooks", tags=["Webhooks"])

VALID_EVENTS = {
    "measurement.log_complete",
    "instrument.unreachable",
    "instrument.recovered",
    "session.expired",
}


@router.post("", response_model=WebhookRegistration, status_code=201)
def register_webhook(req: WebhookRegistrationRequest):
    """Register a webhook URL to receive event notifications.

    Valid event names: measurement.log_complete, instrument.unreachable,
    instrument.recovered, session.expired.
    """
    unknown = set(req.events) - VALID_EVENTS
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown event type(s): {sorted(unknown)}. Valid: {sorted(VALID_EVENTS)}",
        )
    if not req.events:
        raise HTTPException(status_code=422, detail="events list must not be empty")
    return webhook_manager.register(url=req.url, events=req.events, description=req.description)


@router.get("", response_model=list[WebhookRegistration])
def list_webhooks():
    """Return all registered webhook subscriptions."""
    return webhook_manager.list_all()


@router.delete("/{webhook_id}", status_code=204)
def delete_webhook(webhook_id: str):
    """Remove a webhook registration by ID."""
    if not webhook_manager.delete(webhook_id):
        raise HTTPException(status_code=404, detail=f"Webhook '{webhook_id}' not found")

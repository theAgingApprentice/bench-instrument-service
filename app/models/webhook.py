"""Pydantic models for the webhook system."""

from typing import Any, Optional
from pydantic import BaseModel, HttpUrl


class WebhookRegistration(BaseModel):
    """A registered webhook endpoint."""
    id: str
    url: str
    events: list[str]  # e.g. ["measurement.log_complete", "instrument.unreachable"]
    description: Optional[str] = None


class WebhookRegistrationRequest(BaseModel):
    """Request body for POST /v1/webhooks."""
    url: str
    events: list[str]
    description: Optional[str] = None


class WebhookEvent(BaseModel):
    """Payload POSTed to a registered webhook URL when an event fires."""
    event: str
    timestamp: str
    data: dict[str, Any]

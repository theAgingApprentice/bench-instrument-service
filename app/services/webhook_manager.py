"""Webhook delivery service.

Maintains an in-memory registry of webhook subscriptions and delivers
event payloads via fire-and-forget HTTP POST with one retry on failure.
All network I/O uses the stdlib urllib — no extra dependencies.

Event names:
    measurement.log_complete   — multimeter log job finished
    instrument.unreachable     — instrument failed health check
    instrument.recovered       — instrument came back online
    session.expired            — session timed out
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any

from app.models.webhook import WebhookEvent, WebhookRegistration

logger = logging.getLogger(__name__)

# Timeout for each outbound webhook delivery attempt (seconds)
_DELIVERY_TIMEOUT = 5
# Seconds to wait before the single retry
_RETRY_DELAY = 5


class WebhookManager:
    """Thread-safe in-memory webhook registry and delivery engine."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._registrations: dict[str, WebhookRegistration] = {}

    # ------------------------------------------------------------------
    # Registration CRUD
    # ------------------------------------------------------------------

    def register(self, url: str, events: list[str], description: str | None = None) -> WebhookRegistration:
        """Add a new webhook subscription. Returns the created registration."""
        reg = WebhookRegistration(
            id=str(uuid.uuid4()),
            url=url,
            events=events,
            description=description,
        )
        with self._lock:
            self._registrations[reg.id] = reg
        logger.info("webhook registered id=%s url=%s events=%s", reg.id, url, events)
        return reg

    def list_all(self) -> list[WebhookRegistration]:
        """Return all registered webhooks."""
        with self._lock:
            return list(self._registrations.values())

    def delete(self, webhook_id: str) -> bool:
        """Remove a webhook by ID. Returns True if found and deleted."""
        with self._lock:
            if webhook_id not in self._registrations:
                return False
            del self._registrations[webhook_id]
        logger.info("webhook deleted id=%s", webhook_id)
        return True

    # ------------------------------------------------------------------
    # Event firing
    # ------------------------------------------------------------------

    def fire(self, event: str, data: dict[str, Any]) -> None:
        """Fire an event to all matching subscribers in background threads.

        Returns immediately — delivery is asynchronous and best-effort.
        """
        payload = WebhookEvent(
            event=event,
            timestamp=datetime.now(timezone.utc).isoformat(),
            data=data,
        )
        with self._lock:
            targets = [r for r in self._registrations.values() if event in r.events]

        for reg in targets:
            t = threading.Thread(
                target=self._deliver,
                args=(reg, payload),
                daemon=True,
            )
            t.start()

    # ------------------------------------------------------------------
    # Internal delivery
    # ------------------------------------------------------------------

    def _deliver(self, reg: WebhookRegistration, payload: WebhookEvent) -> None:
        """POST payload to reg.url with one retry on failure."""
        body = payload.model_dump_json().encode()
        headers = {"Content-Type": "application/json", "X-BIS-Event": payload.event}

        for attempt in (1, 2):
            try:
                req = urllib.request.Request(
                    reg.url, data=body, headers=headers, method="POST"
                )
                with urllib.request.urlopen(req, timeout=_DELIVERY_TIMEOUT):
                    pass
                logger.info(
                    "webhook delivered id=%s event=%s attempt=%d", reg.id, payload.event, attempt
                )
                return
            except Exception as exc:
                logger.warning(
                    "webhook delivery failed id=%s event=%s attempt=%d error=%s",
                    reg.id, payload.event, attempt, exc,
                )
                if attempt == 1:
                    time.sleep(_RETRY_DELAY)

        logger.error(
            "webhook delivery abandoned id=%s event=%s after 2 attempts", reg.id, payload.event
        )


# Module-level singleton
webhook_manager = WebhookManager()

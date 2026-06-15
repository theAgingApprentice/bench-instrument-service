"""Tests for the webhook registration router and delivery system.

Delivery is tested by patching urllib.request.urlopen — no real HTTP server needed.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from app.services.webhook_manager import WebhookManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mgr() -> WebhookManager:
    """Fresh WebhookManager per test — isolated from the module singleton."""
    return WebhookManager()


@pytest.fixture(autouse=True)
def _clear_module_singleton():
    """Reset the module-level webhook_manager between tests."""
    from app.services import webhook_manager as wm_module
    wm_module.webhook_manager._registrations.clear()
    yield
    wm_module.webhook_manager._registrations.clear()


# ---------------------------------------------------------------------------
# WebhookManager unit tests
# ---------------------------------------------------------------------------

class TestWebhookManager:
    def test_register_returns_registration_with_id(self, mgr):
        reg = mgr.register("http://example.com/hook", ["measurement.log_complete"])
        assert reg.id
        assert reg.url == "http://example.com/hook"
        assert "measurement.log_complete" in reg.events

    def test_list_all_returns_registered(self, mgr):
        mgr.register("http://a.com", ["instrument.unreachable"])
        mgr.register("http://b.com", ["instrument.recovered"])
        assert len(mgr.list_all()) == 2

    def test_delete_returns_true_when_found(self, mgr):
        reg = mgr.register("http://a.com", ["session.expired"])
        assert mgr.delete(reg.id) is True

    def test_delete_returns_false_when_not_found(self, mgr):
        assert mgr.delete("nonexistent-id") is False

    def test_delete_removes_from_list(self, mgr):
        reg = mgr.register("http://a.com", ["session.expired"])
        mgr.delete(reg.id)
        assert mgr.list_all() == []

    def test_fire_delivers_to_matching_subscriber(self, mgr):
        mgr.register("http://recv.com/hook", ["measurement.log_complete"])
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            mgr.fire("measurement.log_complete", {"log_id": "abc"})
            time.sleep(0.1)  # let daemon thread run
        assert mock_open.called

    def test_fire_does_not_deliver_to_non_matching_subscriber(self, mgr):
        mgr.register("http://recv.com/hook", ["instrument.unreachable"])
        with patch("urllib.request.urlopen") as mock_open:
            mgr.fire("measurement.log_complete", {"log_id": "abc"})
            time.sleep(0.1)
        assert not mock_open.called

    def test_fire_delivers_to_multiple_subscribers(self, mgr):
        mgr.register("http://a.com", ["measurement.log_complete"])
        mgr.register("http://b.com", ["measurement.log_complete"])
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            mgr.fire("measurement.log_complete", {"log_id": "xyz"})
            time.sleep(0.1)
        assert mock_open.call_count == 2

    def test_fire_retries_on_failure(self, mgr):
        mgr.register("http://flaky.com", ["session.expired"])
        import urllib.error
        err = urllib.error.URLError("connection refused")
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        side_effects = [err, mock_resp]
        with patch("urllib.request.urlopen", side_effect=side_effects) as mock_open:
            with patch("app.services.webhook_manager._RETRY_DELAY", 0):  # don't actually wait 5s in tests
                mgr.fire("session.expired", {"reason": "timeout"})
                time.sleep(0.1)  # real sleep — lets the daemon thread finish both attempts
        assert mock_open.call_count == 2


# ---------------------------------------------------------------------------
# Webhook router tests (via FastAPI TestClient)
# ---------------------------------------------------------------------------

class TestWebhookRouter:
    def test_register_webhook_returns_201(self, client):
        resp = client.post("/v1/webhooks", json={
            "url": "http://example.com/hook",
            "events": ["measurement.log_complete"],
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["url"] == "http://example.com/hook"
        assert "id" in data

    def test_register_webhook_unknown_event_returns_422(self, client):
        resp = client.post("/v1/webhooks", json={
            "url": "http://example.com/hook",
            "events": ["not.a.real.event"],
        })
        assert resp.status_code == 422

    def test_register_webhook_empty_events_returns_422(self, client):
        resp = client.post("/v1/webhooks", json={
            "url": "http://example.com/hook",
            "events": [],
        })
        assert resp.status_code == 422

    def test_list_webhooks_returns_registered(self, client):
        client.post("/v1/webhooks", json={
            "url": "http://example.com/hook",
            "events": ["instrument.unreachable"],
        })
        resp = client.get("/v1/webhooks")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_delete_webhook_returns_204(self, client):
        reg = client.post("/v1/webhooks", json={
            "url": "http://example.com/hook",
            "events": ["instrument.recovered"],
        }).json()
        resp = client.delete(f"/v1/webhooks/{reg['id']}")
        assert resp.status_code == 204

    def test_delete_nonexistent_webhook_returns_404(self, client):
        resp = client.delete("/v1/webhooks/does-not-exist")
        assert resp.status_code == 404

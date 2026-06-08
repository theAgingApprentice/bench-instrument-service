"""Tests for CommandLogger, including the cross-context ContextVar reset regression."""

import contextvars

from app.services.command_logger import _client_ip_var, command_logger


def test_set_and_reset_client_ip_normal():
    original = _client_ip_var.get()
    token = command_logger.set_client_ip("10.0.0.1")
    assert _client_ip_var.get() == "10.0.0.1"
    command_logger.reset_client_ip(token)
    assert _client_ip_var.get() == original


def test_reset_client_ip_cross_context_does_not_raise():
    """Regression: token created inside copy_context().run() is foreign to the caller.

    Before the fix, reset_client_ip() propagated the ValueError that ContextVar.reset()
    raises when the token was created in a different Context object.  After the fix it
    silently falls back to set("unknown") instead.
    """
    captured: list[contextvars.Token] = []

    def capture():
        captured.append(command_logger.set_client_ip("10.0.0.99"))

    # Run capture inside a *copy* of the current context — the token it produces is
    # bound to that copy, not to the context we're running in now.
    contextvars.copy_context().run(capture)

    # Must not raise ValueError.
    command_logger.reset_client_ip(captured[0])

    # Falls back to the sentinel value rather than leaving "10.0.0.99".
    assert _client_ip_var.get() == "unknown"

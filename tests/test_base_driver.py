"""Tests for BaseInstrumentDriver — currently just query() retry-with-backoff.

BaseInstrumentDriver is abstract (get_status() has no implementation), so
these tests use a minimal concrete subclass with a mocked VISA resource,
bypassing real connect().
"""

from unittest.mock import MagicMock, patch

import pyvisa
import pytest

from app.drivers.base import BaseInstrumentDriver


class _ConcreteDriver(BaseInstrumentDriver):
    def get_status(self) -> dict:
        return {}


@pytest.fixture
def driver():
    d = _ConcreteDriver(ip="192.0.2.1")
    d._resource = MagicMock()
    return d


def _timeout_error() -> pyvisa.errors.VisaIOError:
    return pyvisa.errors.VisaIOError(pyvisa.constants.StatusCode.error_timeout)


class TestQueryRetry:
    def test_retries_once_then_succeeds(self, driver):
        driver._resource.query.side_effect = [_timeout_error(), "OK"]

        with patch("app.drivers.base.time.sleep") as mock_sleep:
            result = driver.query("*IDN?")

        assert result == "OK"
        assert driver._resource.query.call_count == 2
        mock_sleep.assert_called_once_with(1)

    def test_raises_after_exhausting_all_retries(self, driver):
        driver._resource.query.side_effect = [
            _timeout_error(), _timeout_error(), _timeout_error(),
        ]

        with patch("app.drivers.base.time.sleep") as mock_sleep:
            with pytest.raises(pyvisa.errors.VisaIOError):
                driver.query("*IDN?")

        assert driver._resource.query.call_count == 3
        assert mock_sleep.call_count == 2

    def test_success_on_first_try_makes_one_call_no_retry(self, driver):
        driver._resource.query.return_value = "OK"

        with patch("app.drivers.base.time.sleep") as mock_sleep:
            result = driver.query("*IDN?")

        assert result == "OK"
        driver._resource.query.assert_called_once_with("*IDN?")
        mock_sleep.assert_not_called()

"""Live hardware regression tests against the real Siglent SDS1202X-E oscilloscope.

Every real bug found in this service this week -- block-transfer corruption
(6 July 2026), acquisition-settle timing after a timebase change (7 July 2026),
and the per-channel TRMD-restore bug that emptied channel 2 on dual-channel
captures (7 July 2026) -- was discovered by manually running scripts against
real hardware (examples/raw_scope_test.py), never caught by the mocked driver
or router test suite. Mocks can only ever be as correct as the assumptions
baked into them, and all three of these bugs were exactly the kind of thing a
mock would happily paper over.

These tests close that gap by making real-hardware validation a standard,
repeatable part of this repo's test suite instead of an afterthought. They
are skipped by default (see tests/conftest.py's "hardware" marker handling)
because they require the SDS1202X-E to be powered on and reachable at
BIS_OSCILLOSCOPE_IP. Run them explicitly with:

    BIS_HARDWARE_TESTS=1 pytest tests/test_oscilloscope_hardware.py -v
"""

import os

import pytest
from fastapi.testclient import TestClient

from app.drivers.oscilloscope_siglent_sds1202xe import OscilloscopeSiglentSDS1202XE
from app.main import app

OSCILLOSCOPE_IP = os.environ.get("BIS_OSCILLOSCOPE_IP", "192.168.2.45")


@pytest.mark.hardware
def test_real_dual_channel_capture_both_channels_populated():
    """Direct regression test for the 7 July 2026 per-channel-TRMD-restore bug.

    Before the fix, capture_waveform() ran its own stop/read/restore cycle per
    channel, so the scope resumed free-running acquisition between channel 1
    and channel 2 and then got stopped again before a full sweep completed --
    confirmed on real hardware as channel 1 returning 7,000,000 points and
    channel 2 returning num_points=0 in the same request. capture_waveforms()
    now uses a single stop/read-both/restore cycle, so both channels must come
    back populated.
    """
    driver = OscilloscopeSiglentSDS1202XE(ip=OSCILLOSCOPE_IP)
    assert driver.connect(), f"could not connect to oscilloscope at {OSCILLOSCOPE_IP}"
    try:
        data = driver.capture_waveforms([1, 2])
    finally:
        driver.disconnect()

    assert data[1]["num_points"] > 0, "channel 1 returned an empty capture"
    assert data[2]["num_points"] > 0, (
        "channel 2 returned an empty capture -- this is the exact 7 July 2026 "
        "regression (channel 1 had 7,000,000 points, channel 2 had 0)"
    )


@pytest.mark.hardware
def test_real_capture_immediately_after_timebase_change_not_empty():
    """Direct regression test for the acquisition-settle-delay fix.

    The settle delay lives in the /configure router endpoint (a time.sleep()
    after a timebase change), not in the driver's configure_timebase() method
    itself -- /configure and /capture are separate HTTP requests, each with
    its own connect/disconnect cycle, and a /capture issued right after
    /configure could call TRMD STOP before the first sweep under the new
    timebase completed, freezing an empty acquisition buffer. Calling
    driver.configure_timebase() directly would skip that endpoint entirely
    and could never exercise (or fail to exercise) the fix, so this test goes
    through TestClient(app) against the real instrument instead of the driver
    directly -- the same connect/operate/disconnect-per-request cycle
    production traffic uses. No artificial delay is added in the test itself;
    the router's own settle delay is what's under test.
    """
    headers = {"X-API-Key": os.environ["API_KEY"]}
    with TestClient(app) as client:
        configure_resp = client.post(
            "/v1/oscilloscope/configure",
            json={"channel": 1, "timebase": {"scale": 0.001}},
            headers=headers,
        )
        assert configure_resp.status_code == 200, configure_resp.text

        capture_resp = client.post(
            "/v1/oscilloscope/capture",
            json={"channels": [1]},
            headers=headers,
        )

    assert capture_resp.status_code == 200, capture_resp.text
    data = capture_resp.json()
    assert data["channel_1"] is not None
    assert data["channel_1"]["num_points"] > 0, (
        "capture immediately after a timebase change returned an empty buffer -- "
        "this is the exact 7 July 2026 acquisition-settle regression"
    )


@pytest.mark.hardware
def test_real_large_single_channel_capture_completes_without_corruption():
    """Direct regression test for the 6 July 2026 block-transfer corruption bug.

    A single read_raw() call was found to under-read a multi-megabyte
    waveform block at deep memory depth, leaving leftover bytes sitting in
    the socket buffer that corrupted the next SCPI command -- confirmed on
    real hardware as a channel 2 TRMD? query coming back as
    'C1:WF DAT2,#9000000000\\nTRMD AUTO' right after a channel 1 capture.
    This asserts both that a full-depth capture returns the expected
    millions of points, and that an unrelated query issued immediately
    afterward comes back clean (no stray waveform header/echo bytes).
    """
    driver = OscilloscopeSiglentSDS1202XE(ip=OSCILLOSCOPE_IP)
    assert driver.connect(), f"could not connect to oscilloscope at {OSCILLOSCOPE_IP}"
    try:
        data = driver.capture_waveforms([1])[1]
        assert data["num_points"] > 1_000_000, (
            f"expected a deep-memory capture in the millions of points, got {data['num_points']}"
        )

        trmd_response = driver.query("TRMD?")
    finally:
        driver.disconnect()

    assert "#" not in trmd_response, f"leftover IEEE block header bytes in response: {trmd_response!r}"
    assert "WF" not in trmd_response, f"leftover waveform echo bytes in response: {trmd_response!r}"
    assert trmd_response.strip().split()[-1].upper() in {"AUTO", "NORM", "STOP", "SINGLE"}

"""Standalone, BIS-independent diagnostic for the Siglent SDS1202X-E scope.

This script talks to the oscilloscope directly over pyvisa — it does not
import or depend on anything in app/. That's the point: when a waveform
capture looks wrong (corrupted, truncated, or intermittently failing), the
first question is always "is this a bug in BIS's driver/abstraction layer,
or is the raw instrument communication itself doing this?" This script
answers that question by reproducing the same low-level read pattern
BaseInstrumentDriver/OscilloscopeSiglentSDS1202XE use — explicit
chunk_size/timeout, loop-until-declared-byte-count block reads, and a
query-with-retry helper — with per-read logging and full-array statistics,
so nothing about the capture is guessed at.

Anyone extending BIS or adding a new instrument driver can reuse or adapt
this as a template for isolating "is it us or is it the instrument" bugs.
See docs/scpi-block-transfer-protocol.md for the background this script was
written to investigate, and examples/README.md for how to run it.

Requires: pyvisa, pyvisa-py (already in requirements.txt).
"""

from __future__ import annotations

import argparse
import logging
import statistics
import sys
import time

import pyvisa

logger = logging.getLogger("raw_scope_test")

CHUNK_SIZE = 500_000
TIMEOUT_MS = 10_000
CHANNELS = (1, 2)

QUERY_RETRY_ATTEMPTS = 2
QUERY_RETRY_DELAY_S = 1

_SI_MULTIPLIERS = {
    "G": 1e9, "M": 1e6, "k": 1e3, "K": 1e3,
    "m": 1e-3, "u": 1e-6, "µ": 1e-6, "n": 1e-9, "p": 1e-12,
}


def parse_siglent_value(response: str) -> float:
    """Parse a Siglent SCPI response like 'C1:VDIV 500.00mV' -> 0.5."""
    import re

    token = response.strip().split()[-1]
    m = re.match(r"^([+-]?\d+\.?\d*(?:[eE][+-]?\d+)?)([GMkKmuµnp]?)", token)
    if not m:
        return float(token)
    return float(m.group(1)) * _SI_MULTIPLIERS.get(m.group(2), 1.0)


def query_with_retry(resource, command: str) -> str:
    """Query the instrument, retrying on a transient VISA timeout.

    Mirrors the retry pattern in BaseInstrumentDriver.query() (app/drivers/base.py):
    up to QUERY_RETRY_ATTEMPTS additional tries, QUERY_RETRY_DELAY_S seconds
    apart, re-raising if every attempt times out.
    """
    attempt = 0
    while True:
        try:
            return resource.query(command)
        except pyvisa.errors.VisaIOError as exc:
            is_timeout = exc.error_code == pyvisa.constants.StatusCode.error_timeout
            if not is_timeout or attempt >= QUERY_RETRY_ATTEMPTS:
                raise
            attempt += 1
            logger.warning(
                "query timed out, retrying (attempt %d/%d): command=%r",
                attempt, QUERY_RETRY_ATTEMPTS, command,
            )
            time.sleep(QUERY_RETRY_DELAY_S)


def read_ieee_block(resource) -> bytes:
    """Read a complete IEEE 488.2 definite-length binary block, with per-read logging.

    Loops read_raw() until the byte count declared in the block's own header
    (#<n-digits><byte-count>) has actually been received — see
    docs/scpi-block-transfer-protocol.md for why a single read_raw() call
    cannot be trusted to return the whole block on this instrument.
    """
    read_num = 1
    buf = resource.read_raw()
    logger.info("read #%d: got %d bytes (total=%d)", read_num, len(buf), len(buf))

    hash_idx = buf.find(b"#")
    while hash_idx == -1:
        read_num += 1
        chunk = resource.read_raw()
        buf += chunk
        logger.info("read #%d: got %d bytes (total=%d)", read_num, len(chunk), len(buf))
        hash_idx = buf.find(b"#")

    while len(buf) < hash_idx + 2:
        read_num += 1
        chunk = resource.read_raw()
        buf += chunk
        logger.info("read #%d: got %d bytes (total=%d)", read_num, len(chunk), len(buf))
    n_digits = int(chr(buf[hash_idx + 1]))

    header_end = hash_idx + 2 + n_digits
    while len(buf) < header_end:
        read_num += 1
        chunk = resource.read_raw()
        buf += chunk
        logger.info("read #%d: got %d bytes (total=%d)", read_num, len(chunk), len(buf))
    byte_count = int(buf[hash_idx + 2: header_end])
    logger.info("header parsed: n_digits=%d byte_count=%d", n_digits, byte_count)

    total_needed = header_end + byte_count
    while len(buf) < total_needed:
        read_num += 1
        chunk = resource.read_raw()
        buf += chunk
        logger.info("read #%d: got %d bytes (total=%d, need=%d)", read_num, len(chunk), len(buf), total_needed)

    return buf[hash_idx:total_needed]


def strip_ieee_block_header(raw: bytes) -> bytes:
    """Strip the '#<n><byte-count>' header, returning just the payload bytes."""
    idx = raw.find(b"#")
    n_digits = int(chr(raw[idx + 1]))
    byte_count = int(raw[idx + 2: idx + 2 + n_digits])
    data_start = idx + 2 + n_digits
    return raw[data_start: data_start + byte_count]


def array_stats(data: bytes) -> dict:
    """Full-array statistics on decoded waveform bytes — not a spot check.

    A truncated or corrupted capture usually still "looks plausible" if you
    only inspect a handful of points; min/max/mean/stdev/distinct-count over
    the whole array catches shape anomalies a spot check would miss.
    """
    if not data:
        return {"count": 0, "min": None, "max": None, "mean": None, "stdev": None, "distinct": 0}
    values = list(data)
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": statistics.mean(values),
        "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
        "distinct": len(set(values)),
    }


def capture_channel(resource, channel: int) -> dict:
    """Capture one channel's waveform directly, bypassing BIS entirely."""
    ch = f"C{channel}"

    prior_trmd = query_with_retry(resource, "TRMD?").strip().split()[-1].upper()
    resource.write("TRMD STOP")

    vdiv = parse_siglent_value(query_with_retry(resource, f"{ch}:VDIV?"))
    ofst = parse_siglent_value(query_with_retry(resource, f"{ch}:OFST?"))
    sara = parse_siglent_value(query_with_retry(resource, "SARA?"))

    logger.info("channel %d: requesting waveform block (%s:WF? DAT2)", channel, ch)
    resource.write(f"{ch}:WF? DAT2")
    raw = read_ieee_block(resource)
    data = strip_ieee_block_header(raw)

    resource.write(f"TRMD {prior_trmd}")

    stats = array_stats(data)
    logger.info(
        "channel %d: num_points=%d min=%s max=%s mean=%.2f stdev=%.2f distinct=%d",
        channel, stats["count"], stats["min"], stats["max"],
        stats["mean"] or 0.0, stats["stdev"] or 0.0, stats["distinct"],
    )
    return {"channel": channel, "vdiv": vdiv, "ofst": ofst, "sara": sara, **stats}


def run_cycle(resource, cycle_num: int) -> bool:
    """Capture both channels once. Returns True on success, False on any failure."""
    logger.info("--- cycle %d: start ---", cycle_num)
    try:
        for channel in CHANNELS:
            capture_channel(resource, channel)
    except Exception:
        logger.exception("cycle %d: FAILED", cycle_num)
        return False
    logger.info("--- cycle %d: PASS ---", cycle_num)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ip", help="Oscilloscope IP address, e.g. 192.168.2.45")
    parser.add_argument("--runs", type=int, default=20, help="Number of capture cycles to run (default: 20)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable per-read DEBUG logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    rm = pyvisa.ResourceManager("@py")
    resource = rm.open_resource(f"TCPIP::{args.ip}::INSTR")
    resource.chunk_size = CHUNK_SIZE
    resource.timeout = TIMEOUT_MS

    try:
        identity = query_with_retry(resource, "*IDN?").strip()
        logger.info("connected: %s (chunk_size=%d timeout=%dms)", identity, CHUNK_SIZE, TIMEOUT_MS)

        results = [run_cycle(resource, i) for i in range(1, args.runs + 1)]
    finally:
        resource.close()

    passed = sum(results)
    failed = len(results) - passed
    rate = (failed / len(results) * 100) if results else 0.0
    logger.info("=== summary: %d/%d passed, %d failed (%.1f%% failure rate) ===",
                passed, len(results), failed, rate)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

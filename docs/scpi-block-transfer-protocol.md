# SCPI IEEE-488.2 Block Transfers on the Siglent Scope

**Last updated:** July 2026
**Scope:** `app/drivers/base.py`, `app/drivers/oscilloscope_siglent_sds1202xe.py`, `app/routers/oscilloscope.py`
**Related:** [ARCHITECTURE.md § Binary waveform reads and IEEE block chunking](ARCHITECTURE.md)

This document covers the wire format used by `WF?`/`PNSU?` waveform queries
on the Siglent SDS1202X-E, the failure mode that format caused before the
`chunk_size`/`timeout` fix, a separate, smaller finding — transient
per-query timeouts — that led to the retry logic now in
`BaseInstrumentDriver.query()`, and a third, unrelated finding — an empty
acquisition buffer caused by capturing before the scope settles after a
timebase change — that led to the settle delay in `configure()`.

---

## 1. The IEEE-488.2 definite-length block format

SCPI binary responses (waveform data, in our case) are wrapped in an
IEEE-488.2 "definite-length arbitrary block" header:

```
#<n><byte-count><data>
```

- `#` — block marker.
- `<n>` — a single digit, the number of digits in the byte-count field that
  follows.
- `<byte-count>` — an `n`-digit ASCII decimal number giving the exact length
  of `<data>` in bytes.
- `<data>` — the raw payload, exactly `byte-count` bytes.

For example, a channel 1 waveform query response might start:

```
C1:WF DAT2,#9000700000<700000 bytes of waveform data>
```

Here `n=9`, so the next 9 characters (`000700000`) are read as the byte
count: 700,000. Everything before the `#` (`C1:WF DAT2,`) is the SCPI
command echo, not payload.

`_strip_ieee_block_header()` and `_read_ieee_block()` in
`oscilloscope_siglent_sds1202xe.py` parse and consume this format.

---

## 2. Large transfers can report `byte_count=0` before the payload is ready

On real hardware, a large `WF?`/`PNSU?` transfer (deep-memory capture, e.g.
7,000,000 points) does not always arrive as one clean header-then-payload
sequence. The scope can emit — or the client can read, mid-assembly — a
header where the byte-count field is still all zeros:

```
#9000000000
```

Read literally, that's `n=9`, byte-count field `000000000` → **byte_count =
0**, even though the scope is in the middle of preparing a multi-megabyte
payload for that same command. If a driver trusts that header at face value
(treats a 0 byte-count block as "done, no data"), it stops reading while the
real payload is still arriving on the socket.

This is exactly the shape of the corruption `_read_ieee_block()`'s docstring
describes hitting on real hardware: a channel 2 `TRMD?` query — sent
immediately after a channel 1 waveform read — came back as

```
C1:WF DAT2,#9000000000
TRMD AUTO
```

i.e. leftover bytes from the still-in-flight channel 1 transfer (including
this zero-byte-count placeholder header) were sitting in the socket buffer
and got prepended to the next command's response.

### Why `_read_ieee_block()` doesn't trust a single `read_raw()`

`_read_ieee_block()` never treats one `read_raw()` call as the whole
answer. It loops `read_raw()` — accumulating into `buf` — until it has:

1. seen the `#` marker,
2. enough bytes to read the `n`-digit-count digit itself,
3. enough bytes to read the full `n`-digit byte-count field, and
4. `header_end + byte_count` total bytes buffered,

before returning exactly `buf[:total_needed]`. This makes the parse correct
regardless of how the underlying transport chops the transfer into
`read_raw()`-sized pieces, and — critically — it guarantees the driver
doesn't move on to the next SCPI command until the *entire* declared payload
has actually been drained from the socket.

---

## 3. Why `chunk_size >= 500000` and `timeout >= 10000` ms

`BaseInstrumentDriver.connect()` (`app/drivers/base.py`) sets both explicitly
on every VISA resource it opens:

```python
# Siglent programming guide: 500k+ recommended chunk size for
# WF?/PNSU? block transfers, and a timeout floor of 10s for the
# same large-block reads.
self._resource.chunk_size = 500000
self._resource.timeout = max(self.timeout_ms, 10000)
```

Both settings exist to keep the loop in §2 from tripping over the
placeholder-header behavior:

- **`chunk_size = 500000`** — PyVISA's default chunk size (20,000 bytes) is
  far smaller than a deep-memory waveform (up to ~7,000,000 bytes for the
  SDS1202X-E). A small chunk size means many more `read_raw()` round trips
  to drain one transfer, which widens the window in which the driver can
  observe an in-progress, not-yet-backfilled header — and correspondingly
  widens the window for the next SCPI command to race a still-draining
  socket. A chunk size at or above the recommended 500,000 bytes lets most
  transfers complete in one or two `read_raw()` calls instead of dozens.
- **`timeout >= 10000` ms** — assembling and streaming a multi-megabyte
  waveform payload out of the scope takes real time. The default 5-second
  driver timeout (`timeout_ms=5000` in most driver constructors) is not
  reliably enough time for that to finish. If `read_raw()` times out
  mid-transfer, the driver's calling code has no way to know whether the
  remaining bytes will still show up later on the same socket — and per §2,
  they often do, corrupting whatever command runs next. Flooring the
  timeout at 10 seconds (`max(self.timeout_ms, 10000)`, never *lower* than
  whatever the driver was constructed with) gives large transfers enough
  time to actually finish inside the read loop instead of aborting into it.

Both values are enforced in `connect()`, once per VISA resource, so every
driver that goes through `BaseInstrumentDriver` gets them automatically —
no per-driver opt-in required.

---

## 4. The corruption failure mode (pre-fix)

Before `chunk_size`/`timeout` were raised, the failure sequence on real
hardware was:

1. Client sends `C1:WF? DAT2` for a deep-memory capture.
2. The scope's response doesn't arrive as one clean block. With the small
   default chunk size and a timeout too short for the full transfer, the
   read loop stops — either because it saw a not-yet-backfilled
   `#9000000000` header and (in earlier, non-looping code) accepted it at
   face value, or because `read_raw()` timed out — while bytes belonging to
   that same transfer are still in flight on the socket.
3. The driver moves on to the *next* SCPI command (e.g. a channel 2
   `TRMD?` query).
4. The leftover channel 1 bytes are still sitting in the socket's receive
   buffer. They get read as part of the channel 2 command's response,
   producing a garbage reply like `C1:WF DAT2,#9000000000\nTRMD AUTO`
   instead of a clean `TRMD STOP`/`TRMD AUTO` answer.
5. Every subsequent parse on that connection is now working from a
   corrupted buffer — wrong values, exceptions, or silently wrong waveform
   data, depending on where the leftover bytes happen to land.

The fix in `app/drivers/base.py` (raising `chunk_size`/`timeout`) plus the
"loop until the declared byte count is fully drained" logic in
`_read_ieee_block()` (`app/drivers/oscilloscope_siglent_sds1202xe.py`)
together close this: nothing is ever left behind in the socket for the next
command to trip over, because the driver does not return from reading a
block until it has consumed every byte that block declared.

---

## 5. A separate, smaller finding: transient per-query timeouts

Even after the fix above, individual SCPI *queries* (not just large block
transfers) can still time out occasionally and unpredictably —
`pyvisa.errors.VisaIOError` with `error_code == StatusCode.error_timeout`,
with no corruption and no pattern tied to payload size. In isolated testing
using the methodology in §7 below, this showed up at roughly a 6–7%
per-query rate — infrequent enough to be easy to miss in normal use, but
frequent enough to intermittently fail real requests.

This is unrelated to the block-chunking corruption in §2–4: it's not a
leftover-bytes problem, it's a single query occasionally just not getting a
timely reply from the instrument. Because it's transient, a retry is a
reasonable and sufficient mitigation, so `BaseInstrumentDriver.query()` now
retries on a `VisaIOError` timeout:

```python
_QUERY_RETRY_ATTEMPTS = 2
_QUERY_RETRY_DELAY_S = 1
```

On a timeout, `query()` logs a warning (attempt number and the command that
timed out), sleeps `_QUERY_RETRY_DELAY_S` seconds, and retries. If all
attempts (the original call plus `_QUERY_RETRY_ATTEMPTS` retries) time out,
the last `VisaIOError` is re-raised to the caller — a total failure is not
swallowed, only a transient one is smoothed over. Because this lives inside
`BaseInstrumentDriver.query()` itself, every instrument driver gets it
automatically; no per-driver changes were needed.

---

## 6. Acquisition settle time after timebase reconfiguration

`/configure` and `/capture` are separate HTTP requests, and each opens and
closes its own instrument connection (`instrument_session()` in
`app/dependencies.py`). Nothing ties them together beyond the caller issuing
one after the other.

Changing the timebase (`TDIV`) invalidates whatever acquisition the scope
was in the middle of — the new horizontal scale means the in-progress sweep
no longer matches the settings the scope is now configured for. If a
`/capture` request lands immediately after a `/configure` that changed the
timebase, its `TRMD STOP` call can freeze the acquisition buffer before the
first sweep under the new settings has completed. The result is a
legitimately empty capture: `num_points=0` on both channels, with a clean,
valid IEEE block header (`#9000000000`, this time genuinely zero bytes, not
the in-flight placeholder from §2). Confirmed on real hardware 7 July 2026
via RC-Experiments' `run_experiment.py`, where `capture_waveform()` returned
`num_points=0` for both channels immediately after a timebase
reconfiguration with no gap before the capture call.

The fix: `configure()` (`app/routers/oscilloscope.py`) now sleeps after a
timebase change, before releasing the instrument connection:

```python
settle_seconds = req.timebase.scale * 14 + 0.5
time.sleep(settle_seconds)
```

`scale * 14` is one full horizontal sweep — the SDS1202X-E display is 14
horizontal divisions, and `scale` is seconds/division — plus a fixed 0.5
second margin. This guarantees at least one full sweep completes under the
new settings before any subsequent `/capture` can call `TRMD STOP` and
freeze the buffer. The sleep only runs when `timebase` was actually part of
the request; channel- or trigger-only configure calls don't invalidate an
in-progress sweep the same way and skip it.

This is a different failure mode from both findings above: unlike the
block-transfer corruption in §2–4, the header is clean and both channels are
affected equally with no leftover bytes involved — it's an empty-but-valid
capture, not a corrupted one. And unlike the transient query timeout in §5,
it isn't a `VisaIOError` at all — the request succeeds; it just captures
nothing.

---

## 7. How to diagnose this class of bug

Both findings above were isolated with the same approach: **talk to the
instrument directly, with no BIS abstraction in the way, and log everything
instead of guessing.**

The methodology:

1. **Bypass BIS entirely.** Connect via `pyvisa` directly to the
   instrument's LAN/VISA resource string — no `BaseInstrumentDriver`, no
   FastAPI, no routers. This rules out BIS's own code as a variable and
   proves whether a bug is in the abstraction layer or in the raw
   instrument communication.
2. **Set the same low-level VISA settings BIS uses** (`chunk_size`,
   `timeout`) explicitly, so the standalone script's behavior is
   comparable to what BIS actually does in production, not PyVISA's
   defaults.
3. **Log every individual read**, not just the final assembled result —
   per-`read_raw()`-call length, cumulative length, and the raw bytes
   themselves. Corruption and partial-read bugs are only visible at this
   granularity; logging only the final parsed value hides exactly the
   evidence needed to diagnose them (as it did in this case, until
   per-read logging showed the `#9000000000` leftover header).
4. **Compute full-array statistics on the decoded result** (min, max,
   mean, standard deviation, distinct value count) instead of eyeballing a
   sample of points. A corrupted or truncated capture usually looks
   "plausible" if you only check a few values; full-array statistics catch
   shape anomalies (e.g. all-zero runs, wildly wrong ranges, suspiciously
   few distinct values) that a spot check would miss.
5. **Repeat the capture many times in a loop** and report a pass/fail
   summary. Both bugs in this document were intermittent — a single
   successful run proves nothing. Only running enough cycles to get a
   meaningful failure rate (e.g. the ~6–7% figure in §5) turns "seems to
   sometimes glitch" into an actual, comparable measurement.

[`examples/raw_scope_test.py`](../examples/raw_scope_test.py) is the
reference implementation of this methodology — a standalone,
BIS-independent diagnostic script for the SDS1202X-E that anyone adding or
debugging an instrument driver can reuse or adapt. See
[`examples/README.md`](../examples/README.md) for how to run it.

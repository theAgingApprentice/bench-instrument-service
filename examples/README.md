# examples/

Standalone scripts that talk to instruments directly over `pyvisa`, with no
dependency on the BIS app (`app/`). They exist to answer one question when a
capture or query looks wrong: **is this a bug in BIS's driver/abstraction
layer, or is the raw instrument communication itself doing this?**

Run one of these against real hardware to get a BIS-independent ground truth
before digging into `app/drivers/`.

## raw_scope_test.py

Diagnostic for the Siglent SDS1202X-E oscilloscope. Connects directly,
reads waveform blocks from both channels with per-read logging, computes
full-array statistics on the decoded samples, and repeats for a configurable
number of cycles, reporting a pass/fail summary at the end.

See [`docs/scpi-block-transfer-protocol.md`](../docs/scpi-block-transfer-protocol.md)
for the background on why this script's read pattern (chunk size, timeout,
loop-until-declared-byte-count block reads, query retry) matters.

### Requirements

```
pip install pyvisa pyvisa-py
```

(Both are already in the project's `requirements.txt` if you're running
inside the BIS dev environment.)

### Usage

```
python examples/raw_scope_test.py <scope-ip> [--runs 20] [-v]
```

- `<scope-ip>` — the oscilloscope's LAN IP (required), e.g.:
  ```
  python examples/raw_scope_test.py 192.168.2.45
  ```
- `--runs` — number of capture cycles to run, default `20`. Because the
  failure modes this script investigates are intermittent, a single run
  proves little — use enough runs to get a meaningful pass/fail rate.
- `-v` / `--verbose` — enable per-read DEBUG logging (every `read_raw()`
  call, not just per-cycle summaries).

Exit code is `0` if every cycle passed, `1` if any cycle failed.

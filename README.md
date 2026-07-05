# Bench Instrument Service (BIS)

BIS is a FastAPI REST API that abstracts four LXI/Ethernet bench instruments behind a clean HTTP interface. Client applications — Virtual Bench on macOS, RC Experiment scripts, and future projects — make HTTP calls to BIS instead of talking to instruments directly via PyVISA or raw SCPI. The service is deployed as a Docker container on the MitchellNET Ubuntu server (`192.168.2.10`) and is accessible through an NGINX reverse proxy at `https://mitchellnet.local/api/bench/`.

---

## Instruments

| Role | Model | IP | Confirmed Identity (`*IDN?`) |
| --- | --- | --- | --- |
| Oscilloscope | Siglent SDS1202X-E | `192.168.2.45` | `Siglent Technologies,SDS1202X-E,SDS1EDED5R3218,1.3.27` |
| Signal Generator | Siglent SDG-2042X | `192.168.2.46` | `Siglent Technologies,SDG2042X,SDG2XFBQ902599,2.01.01.38R4` |
| Multimeter | Siglent SDM3055 | `192.168.2.20` | `Siglent Technologies,SDM3055,SDM35HBC900580,1.02.01.28` |
| Power Supply | Rigol DP832 | `192.168.2.27` | `RIGOL TECHNOLOGIES,DP832,DP8C277M00511,00.01.19` |

IPs confirmed via `lxi discover` on 4 June 2026.

---

## Quick Links

- [Status Dashboard](https://mitchellnet.local/api/bench/) — `https://mitchellnet.local/api/bench/`
- [Swagger UI](https://mitchellnet.local/api/bench/docs) — `https://mitchellnet.local/api/bench/docs`
- [Health check](https://mitchellnet.local/api/bench/health) — `https://mitchellnet.local/api/bench/health`
- [Health + session state](https://mitchellnet.local/api/bench/health/full) — `https://mitchellnet.local/api/bench/health/full`
- [GitHub Actions](https://github.com/theAgingApprentice/bench-instrument-service/actions) — CI/CD pipeline status

---

## API Summary

### Health & Discovery

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| GET | `/health` | None | Service status and instrument reachability |
| GET | `/health/full` | None | Service status, instrument reachability, and active session state — used by the dashboard |
| GET | `/v1/instruments` | API key | Current instrument registry |
| POST | `/v1/instruments/discover` | API key | Re-probe all instruments and refresh registry |

### Session Management

Instrument endpoints are openly accessible when no session is active. When a session is held, all instrument endpoints reject requests from non-holders with `423 Locked`.

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| POST | `/v1/sessions/acquire` | API key | Reserve exclusive instrument access — returns session token and expiry |
| DELETE | `/v1/sessions/{id}` | API key | Release a session before it times out |
| PUT | `/v1/sessions/{id}/keepalive` | API key | Reset the session expiry timer |
| GET | `/v1/sessions/status` | API key | Return current session or `{"active": false}` |

### Oscilloscope — Siglent SDS1202X-E

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| GET | `/v1/oscilloscope/status` | API key | Channel coupling, scale, offset, probe ratio, timebase, and trigger |
| POST | `/v1/oscilloscope/configure` | API key | Set channel, timebase, and trigger parameters |
| POST | `/v1/oscilloscope/capture` | API key | Capture waveform data from one or both channels |
| POST | `/v1/oscilloscope/screenshot` | API key | Capture display screenshot (returns PNG binary) |

### Signal Generator — Siglent SDG-2042X

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| GET | `/v1/signal-generator/status` | API key | Current output configuration for both channels |
| POST | `/v1/signal-generator/configure` | API key | Configure channel waveform, frequency, amplitude, offset |
| POST | `/v1/signal-generator/output` | API key | Enable or disable channel output |

### Multimeter — Siglent SDM3055

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| GET | `/v1/multimeter/status` | API key | Current measurement mode and configuration |
| POST | `/v1/multimeter/measure` | API key | Take a single measurement |
| POST | `/v1/multimeter/log` | API key | Take repeated measurements over a duration with statistics. Fires `measurement.log_complete` webhook on completion. |
| GET | `/v1/multimeter/log/{log_id}/csv` | None | Download a previous measurement log as CSV |

### Power Supply — Rigol DP832

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| GET | `/v1/power-supply/status` | API key | Measured V, I, P for all three channels |
| POST | `/v1/power-supply/configure` | API key | Set voltage and current limit for one channel |
| POST | `/v1/power-supply/output` | API key | Enable or disable one channel output |
| POST | `/v1/power-supply/all-off` | API key | Disable all three channel outputs immediately |

### Webhooks

BIS fires outbound HTTP POST events to registered URLs. Delivery is best-effort with one retry after 5 seconds.

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| POST | `/v1/webhooks` | API key | Register a URL and event filter |
| GET | `/v1/webhooks` | API key | List all registered webhooks |
| DELETE | `/v1/webhooks/{id}` | API key | Remove a webhook registration |

**Event types:**

| Event | Fired when |
| --- | --- |
| `measurement.log_complete` | A `POST /v1/multimeter/log` job completes |
| `instrument.unreachable` | An instrument fails the 30-second background health check |
| `instrument.recovered` | An instrument comes back online after being unreachable |
| `session.expired` | A session times out without being explicitly released |

**Example registration:**
```bash
curl -X POST https://mitchellnet.local/api/bench/v1/webhooks \
  -H "X-API-Key: <your-key>" \
  -H "Content-Type: application/json" \
  -d '{"url": "http://192.168.2.10:9000/hook", "events": ["measurement.log_complete", "instrument.unreachable"]}'
```

---

## `bench_client.py` — Python Client Library

`bench_client.py` (repo root) is a zero-dependency Python wrapper around the BIS HTTP API. Copy it into any project that needs instrument access.

```python
from bench_client import BenchClient

# Context manager — session acquired on enter, released on exit
with BenchClient(api_key="your-key") as bench:
    token = bench.acquire_session("rc-experiment-3")

    # Oscilloscope
    waveform = bench.capture_waveform(token, channel=1)

    # Signal generator
    bench.configure_signal(token, waveform="SINE", freq_hz=1000.0, amplitude_v=1.0)
    bench.enable_output(token, channel=1, enabled=True)

    # Power supply
    bench.set_psu_channel(token, channel=1, voltage_v=3.3, current_limit_a=0.5)

    # Multimeter
    reading = bench.measure(token, mode="VOLT:DC")
    log = bench.log_measurements(token, mode="VOLT:DC", duration_s=10, interval_s=1.0)
    print(f"Mean: {log['statistics']['mean']} {log['unit']}")
    print(f"CSV: {bench.get_log_csv_url(log['log_id'])}")
```

`BenchClient` defaults to `https://mitchellnet.local/api/bench` with `verify_ssl=False` (required for the self-signed MitchellNET certificate).

---

## Deployment

The service runs on the MitchellNET Ubuntu server at `192.168.2.10` and is accessible at `https://mitchellnet.local/api/bench/` via the NGINX reverse proxy in InternalWebServer.

**Port mapping:** The container runs uvicorn on internal port `8000`. `docker-compose.yml` maps this to host port `8001` because port `8000` is occupied by LibreNMS on the production server. Only the host-side mapping differs — the container and uvicorn configuration are unchanged.

**Docker network:** The `mitchellnet` external Docker network must exist on the host before deploying. Create it once with:

```bash
docker network create mitchellnet
```

**CI/CD venv:** The self-hosted GitHub Actions runner (`imac-server-runner-bis`, installed at `/home/andrew/actions-runner-bis`) requires a persistent Python virtual environment at `/home/andrew/bis-venv` for the CI test job. Create it once with:

```bash
python3 -m venv /home/andrew/bis-venv
/home/andrew/bis-venv/bin/pip install -r requirements-dev.txt
```

**Automated deploy:** Merging a pull request to `main` triggers the GitHub Actions workflow, which runs tests against the venv and deploys to production using the self-hosted runner — no SSH credentials required.

---

## Development Workflow

All changes go through pull requests. Use `aaGitPromote` to open a PR and `aaGitCleanupBranches` to remove merged branches.

For the full developer workflow — branching conventions, PR checklist, and deployment verification steps — see [`mitchellnet-infra/docs/runbook.md`](https://github.com/theAgingApprentice/mitchellnet-infra/blob/main/docs/runbook.md).

---

## Project Structure

```
bench-instrument-service/
├── app/
│   ├── main.py                  # FastAPI app factory, router registration, lifespan (health-check loop)
│   ├── config.py                # Settings loaded from environment variables (pydantic-settings)
│   ├── dependencies.py          # FastAPI dependency injection (instrument registry, session check)
│   │
│   ├── routers/
│   │   ├── health.py            # GET /health, GET /health/full
│   │   ├── instruments.py       # GET /v1/instruments, POST /v1/instruments/discover
│   │   ├── sessions.py          # POST/DELETE/PUT /v1/sessions/*
│   │   ├── oscilloscope.py      # All /v1/oscilloscope/* endpoints
│   │   ├── signal_generator.py  # All /v1/signal-generator/* endpoints
│   │   ├── multimeter.py        # All /v1/multimeter/* endpoints
│   │   ├── power_supply.py      # All /v1/power-supply/* endpoints
│   │   └── webhooks.py          # POST/GET/DELETE /v1/webhooks
│   │
│   ├── drivers/
│   │   ├── base.py              # Abstract base class all drivers inherit from
│   │   ├── oscilloscope_siglent_sds1202xe.py
│   │   ├── signal_generator_siglent_sdg2042x.py
│   │   ├── multimeter_siglent_sdm3055.py
│   │   └── power_supply_rigol_dp832.py
│   │
│   ├── services/
│   │   ├── instrument_registry.py  # Tracks discovered instruments and their status
│   │   ├── session_manager.py      # Exclusive instrument reservation
│   │   ├── webhook_manager.py      # Webhook registry, fire-and-forget delivery, retry
│   │   └── command_logger.py       # Logs every SCPI command with timestamp + client info
│   │
│   ├── models/
│   │   ├── oscilloscope.py      # Pydantic request/response models for oscilloscope
│   │   ├── signal_generator.py  # Pydantic request/response models for signal generator
│   │   ├── multimeter.py        # Pydantic request/response models for multimeter
│   │   ├── power_supply.py      # Pydantic request/response models for power supply
│   │   ├── webhook.py           # WebhookRegistration, WebhookEvent models
│   │   └── common.py            # Shared models (HealthResponse, HealthFullResponse, etc.)
│   │
│   └── static/
│       ├── index.html           # Status dashboard — instrument cards + session panel
│       ├── style.css            # Dashboard styles
│       └── dashboard.js         # Polling logic — GET /health/full every 10s
│
├── tests/
│   ├── conftest.py              # Pytest fixtures, mock instrument factory
│   ├── test_auth.py
│   ├── test_bench_client.py
│   ├── test_command_logger.py
│   ├── test_health.py
│   ├── test_oscilloscope.py
│   ├── test_signal_generator.py
│   ├── test_multimeter.py
│   ├── test_power_supply.py
│   ├── test_sessions.py
│   └── test_webhooks.py
│
├── docs/
│   └── BIS_Implementation_Blueprint.md
│
├── bench_client.py              # Zero-dependency Python client library
├── Dockerfile
├── docker-compose.yml
├── docker-compose.dev.yml       # Dev override: mounts source, enables hot-reload
├── requirements.txt
├── requirements-dev.txt
├── .env.example
├── .gitignore
└── README.md
```

---

## Phase Status

| Phase | Description | Status | Date |
| --- | --- | --- | --- |
| 1 | Core service — all four instruments, full API, Docker deploy, CI/CD | Complete | 4 June 2026 |
| 2 | Session management — exclusive instrument reservation, session timeout | Complete | 8 June 2026 |
| 3 | Enhancements — status dashboard, bench_client.py, webhook support | Complete | 15 June 2026 |

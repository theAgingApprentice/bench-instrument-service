# Bench Instrument Service — Architecture

**Last updated:** June 2026  
**Status:** Live at `https://mitchellnet.local/api/bench/`  
**Framework:** FastAPI  
**Full implementation reference:** [BIS_Implementation_Blueprint.md](BIS_Implementation_Blueprint.md)

---

## Overview

The Bench Instrument Service (BIS) is a FastAPI REST API that abstracts four
LXI/Ethernet bench instruments behind a clean HTTP interface. It runs as a
Docker container on the MitchellNET Ubuntu server and is proxied by NGINX at
`/api/bench/`.

### Instruments

| Instrument | Model | LAN IP |
| --- | --- | --- |
| Oscilloscope | Siglent SDS1202X-E | 192.168.2.45 |
| Signal Generator | Siglent SDG-2042X | 192.168.2.46 |
| Multimeter | Siglent SDM3055 | 192.168.2.20 |
| Power Supply | Rigol DP832 | 192.168.2.27 |

Instruments are on the Lab VLAN (planned: VLAN 40, `192.168.40.x`). Unreachable
instruments are not a startup failure — BIS starts normally and reports them as
unreachable via `GET /health`.

---

## Repository Structure
bench-instrument-service/
├── app/
│   ├── main.py              # FastAPI app, router registration, lifespan handler
│   ├── config.py            # Pydantic settings (BIS_* env var prefix)
│   ├── dependencies.py      # Shared dependencies: registry, session, API key auth
│   ├── routers/
│   │   ├── health.py        # GET /health — unprotected
│   │   ├── instruments.py   # GET /v1/instruments, POST /v1/instruments/discover
│   │   ├── sessions.py      # Session acquire/release/keepalive
│   │   ├── oscilloscope.py  # Oscilloscope control
│   │   ├── signal_generator.py
│   │   ├── multimeter.py
│   │   └── power_supply.py
│   ├── models/              # Pydantic request/response models
│   ├── drivers/             # Low-level SCPI instrument drivers
│   └── services/            # InstrumentRegistry, SessionManager, CommandLogger
├── tests/
│   ├── conftest.py                     # Shared fixtures; auth bypassed for business-logic tests
│   ├── test_auth.py                    # Auth-specific tests with real verify_api_key
│   ├── test_bench_client.py            # bench_client.py HTTP behavior against a mocked BIS
│   ├── test_bench_client_contracts.py  # Asserts bench_client.py request bodies match Pydantic models
│   ├── test_command_logger.py
│   ├── test_health.py
│   ├── test_sessions.py
│   ├── test_oscilloscope.py            # Router-level: mocks the driver
│   ├── test_oscilloscope_driver.py     # Driver-level: asserts literal SCPI strings sent to write()
│   ├── test_signal_generator.py
│   ├── test_multimeter.py
│   ├── test_power_supply.py
│   └── test_webhooks.py
├── docs/
│   ├── ARCHITECTURE.md      # This file
│   └── BIS_Implementation_Blueprint.md
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── .github/workflows/       # CI: test on PR; deploy on merge

---

## Framework: FastAPI

BIS uses FastAPI (not Flask). See
[mitchellnet-infra/docs/FRAMEWORKS.md](../../mitchellnet-infra/docs/FRAMEWORKS.md)
for the full comparison and the decision guide for future services.

FastAPI was chosen for BIS because:
- Automatic OpenAPI docs at `/api/bench/docs` — invaluable during instrument driver development
- Pydantic models enforce the API contract for all request/response types
- `Depends()` injection applies auth and session checks consistently across all routes
- Native async support for concurrent instrument polling

---

## Security

### API Authentication

All instrument endpoints require an `X-API-Key` header. The `/health` endpoint
is exempt.

Authentication is implemented as a FastAPI dependency in `app/dependencies.py`:

```python
def verify_api_key(api_key: str = Security(_api_key_header)) -> None:
    expected = os.environ.get("API_KEY", "")
    if not expected:
        raise HTTPException(status_code=500, detail="Server misconfiguration")
    if not api_key or not hmac.compare_digest(api_key, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")
```

Applied at router registration in `main.py`:

```python
_auth = [Depends(verify_api_key)]
app.include_router(sessions.router,         dependencies=_auth)
app.include_router(instruments.router,      dependencies=_auth)
app.include_router(oscilloscope.router,     dependencies=_auth)
app.include_router(signal_generator.router, dependencies=_auth)
app.include_router(multimeter.router,       dependencies=_auth)
app.include_router(power_supply.router,     dependencies=_auth)
# Health is registered without _auth:
app.include_router(health.router)
```

The `API_KEY` value is stored in `~/services/bench-instrument-service/.env`
on the server. It is never committed to version control.

### Secrets

| Secret | Storage |
| --- | --- |
| `API_KEY` | `~/services/bench-instrument-service/.env` on server; `.env` at repo root on Dev Machine (gitignored) |
| `BIS_*` instrument IPs | Same `.env` files |

---

## Environment Variables

All BIS environment variables use the `BIS_` prefix (loaded by pydantic-settings).
`API_KEY` is the exception — read directly from the environment without a prefix.

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `API_KEY` | Yes | — | X-API-Key header value for all protected endpoints |
| `BIS_OSCILLOSCOPE_IP` | Yes | — | Oscilloscope LAN IP |
| `BIS_SIGNAL_GENERATOR_IP` | Yes | — | Signal generator LAN IP |
| `BIS_MULTIMETER_IP` | Yes | — | Multimeter LAN IP |
| `BIS_POWER_SUPPLY_IP` | Yes | — | Power supply LAN IP |
| `BIS_SCPI_TIMEOUT_MS` | No | 5000 | SCPI command timeout in milliseconds |
| `BIS_LOG_LEVEL` | No | info | Logging level (debug/info/warning/error) |
| `BIS_DISCOVER_ON_STARTUP` | No | true | Run instrument discovery on startup |
| `BIS_SESSION_TIMEOUT_SECONDS` | No | 300 | Instrument session timeout |

See `.env.example` for a complete template.

---

## API Endpoints

OpenAPI docs available live at `https://mitchellnet.local/api/bench/docs`.

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| GET | `/health` | None | Service status and instrument reachability |
| GET | `/v1/instruments` | Required | List all instruments and their status |
| POST | `/v1/instruments/discover` | Required | Re-probe all instruments |
| POST | `/v1/sessions/acquire` | Required | Acquire exclusive instrument session |
| DELETE | `/v1/sessions/{id}` | Required | Release session |
| PUT | `/v1/sessions/{id}/keepalive` | Required | Extend session timeout |
| GET | `/v1/sessions/status` | Required | Current session status |
| GET | `/v1/oscilloscope/status` | Required | Oscilloscope current state (channels, timebase, trigger) |
| POST | `/v1/oscilloscope/configure` | Required | Configure oscilloscope channels, timebase, and trigger |
| POST | `/v1/oscilloscope/capture` | Required | Capture waveform |
| POST | `/v1/oscilloscope/screenshot` | Required | Capture screen image |
| GET | `/v1/signal-generator/status` | Required | Signal generator current state |
| POST | `/v1/signal-generator/configure` | Required | Configure signal generator |
| POST | `/v1/signal-generator/output` | Required | Enable/disable output |
| GET | `/v1/multimeter/status` | Required | Multimeter current state |
| POST | `/v1/multimeter/measure` | Required | Take a single measurement |
| POST | `/v1/multimeter/log` | Required | Start/stop measurement logging |
| GET | `/v1/multimeter/log/{id}/csv` | Required | Download log as CSV |
| GET | `/v1/power-supply/status` | Required | Power supply current state |
| POST | `/v1/power-supply/configure` | Required | Configure channel |
| POST | `/v1/power-supply/output` | Required | Enable/disable output |
| POST | `/v1/power-supply/all-off` | Required | Emergency all-off |

---

## Docker and Deployment

```yaml
# docker-compose.yml summary
services:
  bench-instrument-service:
    build: .
    env_file: .env
    ports:
      - "8001:8000"   # 8001 on host due to LibreNMS conflict on 8000
    networks:
      - mitchellnet
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
```

Deployed to `~/services/bench-instrument-service/` on the Ubuntu server.
CI/CD via GitHub Actions self-hosted runner — tests run on PR, deploy runs on merge to main.

---

## Testing

```bash
# Run all tests
API_KEY=test-key python -m pytest tests/ -v

# Auth tests only
API_KEY=test-key python -m pytest tests/test_auth.py -v
```

The `conftest.py` fixture overrides `verify_api_key` with a no-op for all
business-logic tests, so instrument tests do not need to supply the header.
Only `test_auth.py` uses the real `verify_api_key` dependency.

### Router-level vs. driver-level instrument tests

Most instrument test files (`test_oscilloscope.py`, `test_signal_generator.py`,
etc.) mock the driver itself and assert that the router calls it with the
correct Python arguments. This is fast and good for catching request-shape
and routing bugs, but it cannot catch bugs in the actual SCPI strings a
driver sends to hardware — the driver is mocked out entirely.

`test_oscilloscope_driver.py` fills that gap: it mocks only the underlying
VISA resource and asserts on the literal SCPI string passed to `write()`
(e.g. `"C1:CPL D1M"`). This pattern exists because a real bug shipped in
July 2026 where `configure_channel()` sent bare `DC`/`AC` coupling values
that the SDS1202X-E silently rejected — router-level tests passed the whole
time since they never touched the wire format. See PR #25/#26.

New drivers or new SCPI-emitting methods should get an equivalent
driver-level test file alongside their router-level test.

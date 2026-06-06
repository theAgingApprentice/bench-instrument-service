# Bench Instrument Service (BIS)

BIS is a FastAPI REST API that abstracts four LXI/Ethernet bench instruments behind a clean HTTP interface. Client applications — Virtual Bench on macOS, RC Experiment scripts, and future projects — make HTTP calls to BIS instead of talking to instruments directly via PyVISA or raw SCPI. The service is deployed as a Docker container on the MitchellNET Ubuntu server (`192.168.2.10`) and is accessible through an NGINX reverse proxy at `https://mitchellnet.local/api/bench/`.

---

## Instruments

| Role | Model | IP | Confirmed Identity (`*IDN?`) |
|---|---|---|---|
| Oscilloscope | Siglent SDS1202X-E | `192.168.2.45` | `Siglent Technologies,SDS1202X-E,SDS1EDED5R3218,1.3.27` |
| Signal Generator | Siglent SDG-2042X | `192.168.2.46` | `Siglent Technologies,SDG2042X,SDG2XFBQ902599,2.01.01.38R4` |
| Multimeter | Siglent SDM3055 | `192.168.2.20` | `Siglent Technologies,SDM3055,SDM35HBC900580,1.02.01.28` |
| Power Supply | Rigol DP832 | `192.168.2.27` | `RIGOL TECHNOLOGIES,DP832,DP8C277M00511,00.01.19` |

IPs confirmed via `lxi discover` on 4 June 2026.

---

## Quick Links

- [Swagger UI](https://mitchellnet.local/api/bench/docs) — `https://mitchellnet.local/api/bench/docs`
- [Health check](https://mitchellnet.local/api/bench/health) — `https://mitchellnet.local/api/bench/health`
- [GitHub Actions](https://github.com/theAgingApprentice/bench-instrument-service/actions) — CI/CD pipeline status

---

## API Summary

### Health & Discovery

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Service status and instrument reachability |
| GET | `/v1/instruments` | Current instrument registry |
| POST | `/v1/instruments/discover` | Re-probe all instruments and refresh registry |

### Oscilloscope — Siglent SDS1202X-E

| Method | Path | Description |
|---|---|---|
| GET | `/v1/oscilloscope/status` | Channel coupling, scale, offset, probe ratio, and timebase |
| POST | `/v1/oscilloscope/configure` | Set channel and timebase parameters |
| POST | `/v1/oscilloscope/capture` | Capture waveform data from one or both channels |
| POST | `/v1/oscilloscope/screenshot` | Capture display screenshot (returns PNG binary) |

### Signal Generator — Siglent SDG-2042X

| Method | Path | Description |
|---|---|---|
| GET | `/v1/signal-generator/status` | Current output configuration for both channels |
| POST | `/v1/signal-generator/configure` | Configure channel waveform, frequency, amplitude, offset |
| POST | `/v1/signal-generator/output` | Enable or disable channel output |

### Multimeter — Siglent SDM3055

| Method | Path | Description |
|---|---|---|
| GET | `/v1/multimeter/status` | Current measurement mode and configuration |
| POST | `/v1/multimeter/measure` | Take a single measurement |
| POST | `/v1/multimeter/log` | Take repeated measurements over a duration with statistics |
| GET | `/v1/multimeter/log/{log_id}/csv` | Download a previous measurement log as CSV |

### Power Supply — Rigol DP832

| Method | Path | Description |
|---|---|---|
| GET | `/v1/power-supply/status` | Measured V, I, P for all three channels |
| POST | `/v1/power-supply/configure` | Set voltage and current limit for one channel |
| POST | `/v1/power-supply/output` | Enable or disable one channel output |
| POST | `/v1/power-supply/all-off` | Disable all three channel outputs immediately |

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
│   ├── main.py                  # FastAPI app factory, router registration, startup/shutdown
│   ├── config.py                # Settings loaded from environment variables (pydantic-settings)
│   ├── dependencies.py          # FastAPI dependency injection (instrument registry, session manager)
│   │
│   ├── routers/
│   │   ├── health.py            # GET /health
│   │   ├── instruments.py       # GET /v1/instruments (discovery + registry)
│   │   ├── oscilloscope.py      # All /v1/oscilloscope/* endpoints
│   │   ├── signal_generator.py  # All /v1/signal-generator/* endpoints
│   │   ├── multimeter.py        # All /v1/multimeter/* endpoints
│   │   └── power_supply.py      # All /v1/power-supply/* endpoints
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
│   │   ├── session_manager.py      # Exclusive instrument reservation (Phase 2)
│   │   └── command_logger.py       # Logs every SCPI command with timestamp + client info
│   │
│   └── models/
│       ├── oscilloscope.py      # Pydantic request/response models for oscilloscope
│       ├── signal_generator.py  # Pydantic request/response models for signal generator
│       ├── multimeter.py        # Pydantic request/response models for multimeter
│       ├── power_supply.py      # Pydantic request/response models for power supply
│       └── common.py            # Shared models (InstrumentStatus, HealthResponse, etc.)
│
├── tests/
│   ├── conftest.py              # Pytest fixtures, mock instrument factory
│   ├── test_health.py
│   ├── test_oscilloscope.py
│   ├── test_signal_generator.py
│   ├── test_multimeter.py
│   └── test_power_supply.py
│
├── docs/
│   └── BIS_Implementation_Blueprint.md
│
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
|---|---|---|---|
| 1 | Core service — all four instruments, full API, Docker deploy, CI/CD | Complete | 4 June 2026 |
| 2 | Session management — exclusive instrument reservation, session timeout | Planned | — |
| 3 | Enhancements — web dashboard, Python client library, webhook support | Planned | — |

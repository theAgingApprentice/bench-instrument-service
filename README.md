# bench-instrument-service

FastAPI REST API that abstracts four LXI/Ethernet bench instruments behind a clean HTTP interface.

**Direct access:** `http://192.168.2.10:8001`  
**Via NGINX:** `https://mitchellnet.local/api/bench/` (once the NGINX routing block is configured)  
**OpenAPI docs:** `http://192.168.2.10:8001/docs`

> **Port note:** The container runs uvicorn on internal port 8000 as normal, but `docker-compose.yml`
> maps it to host port **8001** because port 8000 is already allocated by LibreNMS on the MitchellNET
> server.

---

## Instruments

| Role | Model | IP | Port |
|---|---|---|---|
| Oscilloscope | Siglent SDS1202X-E | 192.168.2.45 | 5025 (LXI) |
| Signal Generator | Siglent SDG2042X | 192.168.2.46 | 5025 (LXI) |
| Multimeter | Siglent SDM3055 | 192.168.2.20 | 5025 (LXI) |
| Power Supply | Rigol DP832 | 192.168.2.27 | 5555 (raw socket) |

---

## API Summary

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | Service status and instrument reachability |
| GET | `/v1/instruments` | Current instrument registry |
| POST | `/v1/instruments/discover` | Re-probe all instruments |
| GET | `/v1/oscilloscope/status` | Channel and timebase settings |
| POST | `/v1/oscilloscope/configure` | Set channel/timebase parameters |
| POST | `/v1/oscilloscope/capture` | Capture waveform data |
| POST | `/v1/oscilloscope/screenshot` | Capture display screenshot (BMP) |
| GET | `/v1/signal-generator/status` | Channel output configuration |
| POST | `/v1/signal-generator/configure` | Configure channel (waveform, frequency, amplitude…) |
| POST | `/v1/signal-generator/output` | Enable/disable channel output |
| GET | `/v1/multimeter/status` | Current measurement mode |
| POST | `/v1/multimeter/measure` | Take a single measurement |
| POST | `/v1/multimeter/log` | Take repeated measurements with statistics |
| GET | `/v1/multimeter/log/{log_id}/csv` | Download a previous log as CSV |
| GET | `/v1/power-supply/status` | Measured V, I, P for all three channels |
| POST | `/v1/power-supply/configure` | Set voltage and current limit |
| POST | `/v1/power-supply/output` | Enable/disable one channel |
| POST | `/v1/power-supply/all-off` | Disable all outputs immediately |

---

## Quick start

### Local development (hot-reload)

```bash
cp .env.example .env          # fill in real IPs if different
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

### Docker (production image)

```bash
cp .env.example .env
docker compose up -d
```

### Docker (dev — hot-reload with source mount)

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

---

## Environment variables

All instrument IPs and service behaviour are configured via environment variables.  
Copy `.env.example` to `.env` and adjust for your network.

| Variable | Default | Description |
|---|---|---|
| `BIS_OSCILLOSCOPE_IP` | — | IP address of the SDS1202X-E |
| `BIS_SIGNAL_GENERATOR_IP` | — | IP address of the SDG2042X |
| `BIS_MULTIMETER_IP` | — | IP address of the SDM3055 |
| `BIS_POWER_SUPPLY_IP` | — | IP address of the DP832 |
| `BIS_SCPI_TIMEOUT_MS` | `5000` | SCPI command timeout in milliseconds |
| `BIS_LOG_LEVEL` | `info` | Log level: `debug` / `info` / `warning` / `error` |
| `BIS_DISCOVER_ON_STARTUP` | `true` | Probe instruments with `*IDN?` at startup |

---

## Testing

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

Tests use FastAPI's `TestClient` with mocked instrument drivers — no real instruments required in CI. See [`tests/conftest.py`](tests/conftest.py) for fixture design.

---

## Adding a new instrument

1. Create `app/drivers/{role}_{manufacturer}_{model}.py` inheriting from `BaseInstrumentDriver`.
2. Add its IP to `.env.example`, `app/config.py`, and `app/services/instrument_registry.py`.
3. Add a router under `app/routers/` and register it in `app/main.py`.

No changes to existing drivers required.

---

## Deployment Notes

### Port mapping

The container runs uvicorn on internal port **8000**. `docker-compose.yml` maps it to host port **8001** because port 8000 is already allocated by LibreNMS on the MitchellNET Ubuntu server. Do not change the internal port — only the host-side mapping is 8001.

### Access URLs

| Route | URL |
|---|---|
| Direct (host network) | `http://192.168.2.10:8001` |
| Via NGINX proxy | `https://mitchellnet.local/api/bench/` |
| Swagger UI | `https://mitchellnet.local/api/bench/docs` |

The `root_path="/api/bench"` parameter in the FastAPI constructor is required for Swagger UI to generate correct URLs when accessed through the NGINX proxy at `/api/bench/`.

### Docker network prerequisite

The `mitchellnet` external Docker network must exist on the host before running `docker compose up`. Create it once with:

```bash
docker network create mitchellnet
```

If the network does not exist, `docker compose up` will fail with a network not found error.

### CI/CD Python environment

The self-hosted GitHub Actions runner on the Ubuntu server (`/home/andrew/actions-runner-bis`) requires a Python virtual environment at `/home/andrew/bis-venv` for the CI test job. Create it once with:

```bash
python3 -m venv /home/andrew/bis-venv
/home/andrew/bis-venv/bin/pip install -r requirements-dev.txt
```

The workflow's test job activates this venv rather than relying on the system Python.

---

## Architecture

See [`docs/BIS_Implementation_Blueprint.md`](docs/BIS_Implementation_Blueprint.md) for the full implementation reference.

# Bench Instrument Service (BIS) — Implementation Blueprint

**Repo:** `bench-instrument-service`  
**Language:** Python 3.11  
**Framework:** FastAPI  
**Deployed on:** Ubuntu Server 24.04.2 · `192.168.2.10`  
**Accessible at:** `https://mitchellnet.local/api/bench/`  
**Internal port:** `8000`  

This document is the complete implementation guide for the BIS. It covers repo structure, every file to create, the full API contract, instrument driver design, Docker/Compose setup, and CI/CD. Use it as the primary reference when building the service.

---

## Table of Contents

1. [What BIS Does](#1-what-bis-does)
2. [Repo Structure](#2-repo-structure)
3. [Technology Stack](#3-technology-stack)
4. [Instruments](#4-instruments)
5. [API Contract](#5-api-contract)
6. [Internal Architecture](#6-internal-architecture)
7. [Driver Design](#7-driver-design)
8. [Data Models](#8-data-models)
9. [Docker & Compose](#9-docker--compose)
10. [Environment Variables](#10-environment-variables)
11. [CI/CD](#11-cicd)
12. [Phased Delivery](#12-phased-delivery)
13. [Testing Strategy](#13-testing-strategy)

---

## 1. What BIS Does

BIS is a FastAPI REST API that abstracts four LXI/Ethernet bench instruments behind a clean HTTP interface. Client applications (Virtual Bench on macOS, RC Experiment scripts, future projects) make HTTP calls to BIS instead of talking to instruments directly via PyVISA or SCPI.

**Before BIS — client must know:**
- Each instrument's IP address
- PyVISA resource strings (`TCPIP::192.168.2.46::INSTR`)
- SCPI command syntax per instrument model
- How to handle instrument-specific quirks

**After BIS — client only needs:**
```python
import requests
BIS = "http://192.168.2.10:8000"
requests.post(f"{BIS}/v1/signal-generator/configure",
              json={"channel": 1, "waveform": "SQUARE", "frequency": 1000.0, "output": True})
```

Any future project on any platform — Python, JavaScript, Jupyter, any language that can make HTTP requests — gets immediate access to all bench instruments with zero instrument-specific knowledge.

---

## 2. Repo Structure

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
│   └── ARCHITECTURE.md          # Points to this file and the original BRD
│
├── Dockerfile
├── docker-compose.yml
├── docker-compose.dev.yml       # Dev override: mounts source, enables hot-reload
├── requirements.txt
├── requirements-dev.txt         # pytest, httpx, pytest-asyncio
├── .env.example
├── .gitignore
└── README.md
```

---

## 3. Technology Stack

| Component | Choice | Reason |
|---|---|---|
| Web framework | FastAPI 0.115+ | Async, auto OpenAPI docs, Pydantic validation built in |
| ASGI server | Uvicorn | Standard FastAPI deployment |
| Instrument comms | PyVISA 1.14+ | Mature LXI/TCPIP instrument control library |
| VISA backend | PyVISA-py | Pure Python, no NI-VISA required on Ubuntu |
| Settings | pydantic-settings | Typed environment variable loading |
| Logging | Python stdlib logging + structlog | Structured JSON logs, easy Grafana ingestion |
| Testing | pytest + httpx | httpx provides async test client for FastAPI |
| Containerisation | Docker + Compose | Matches all other MitchellNET services |

**Do not use NI-VISA.** Use `pyvisa-py` as the VISA backend — it works over TCP/IP with LXI instruments on Linux without any NI driver installation.

---

## 4. Instruments

| Role | Model | IP | Protocol | Default Port | Confirmed Identity |
|---|---|---|---|---|---|
| Oscilloscope | Siglent SDS1202X-E | `192.168.2.45` | LXI / SCPI over TCP | 5025 | `Siglent Technologies,SDS1202X-E,SDS1EDED5R3218,1.3.27` |
| Signal Generator | Siglent SDG-2042X | `192.168.2.46` | LXI / SCPI over TCP | 5025 | `Siglent Technologies,SDG2042X,SDG2XFBQ902599,2.01.01.38R4` |
| Multimeter | Siglent SDM3055 | `192.168.2.20` | LXI / SCPI over TCP | 5025 | `Siglent Technologies,SDM3055,SDM35HBC900580,1.02.01.28` |
| Power Supply | Rigol DP832 | `192.168.2.27` | LXI / SCPI over TCP | 5555 | `RIGOL TECHNOLOGIES,DP832,DP8C277M00511,00.01.19` |

All instruments are on the MitchellNET LAN. Their IPs are configured as environment variables (see Section 10) — never hardcoded in source. IPs confirmed via `lxi discover` on 4 June 2026.

**PyVISA resource string format:**
```
TCPIP::{ip_address}::INSTR          # Standard LXI
TCPIP::{ip_address}::{port}::SOCKET # Raw socket (Rigol DP832 uses this)
```

**Confirmed PyVISA resource strings:**
```
TCPIP::192.168.2.45::INSTR   # Oscilloscope  SDS1202X-E
TCPIP::192.168.2.46::INSTR   # Signal Gen    SDG2042X
TCPIP::192.168.2.20::INSTR   # Multimeter    SDM3055
TCPIP::192.168.2.27::5555::SOCKET  # Power Supply  DP832
```

**Identity query** — all instruments respond to `*IDN?` with a comma-separated string. Expected responses:
```
Siglent Technologies,SDS1202X-E,SDS1EDED5R3218,1.3.27
Siglent Technologies,SDG2042X,SDG2XFBQ902599,2.01.01.38R4
Siglent Technologies,SDM3055,SDM35HBC900580,1.02.01.28
RIGOL TECHNOLOGIES,DP832,DP8C277M00511,00.01.19
```
Use these to verify connectivity and populate the instrument registry on startup.

---

## 5. API Contract

All endpoints are prefixed `/v1/`. The NGINX proxy in InternalWebServer routes `https://mitchellnet.local/api/bench/` → `http://bench-instrument-service:8000/`. FastAPI's auto-generated OpenAPI docs are available at `http://192.168.2.10:8000/docs` (internal) and `https://mitchellnet.local/api/bench/docs` (via NGINX).

### 5.1 Health & Discovery

#### `GET /health`
Returns service status, uptime, and reachability of all four instruments.

**Response 200:**
```json
{
  "status": "ok",
  "uptime_seconds": 3600,
  "instruments": {
    "oscilloscope":     {"reachable": true,  "ip": "192.168.2.45", "identity": "Siglent Technologies,SDS1202X-E,SDS1EDED5R3218,1.3.27"},
    "signal_generator": {"reachable": true,  "ip": "192.168.2.46", "identity": "Siglent Technologies,SDG2042X,SDG2XFBQ902599,2.01.01.38R4"},
    "multimeter":       {"reachable": true,  "ip": "192.168.2.20", "identity": "Siglent Technologies,SDM3055,SDM35HBC900580,1.02.01.28"},
    "power_supply":     {"reachable": true,  "ip": "192.168.2.27", "identity": "RIGOL TECHNOLOGIES,DP832,DP8C277M00511,00.01.19"}
  }
}
```

#### `GET /v1/instruments`
Returns current instrument registry — discovered IPs, identity strings, and availability.

#### `POST /v1/instruments/discover`
Triggers an immediate LXI discovery scan and refreshes the registry. Returns updated registry.

---

### 5.2 Oscilloscope — Siglent SDS1202X-E

#### `GET /v1/oscilloscope/status`
Returns current channel settings (coupling, scale, offset, probe ratio, enabled state) for both channels plus timebase.

**Response 200:**
```json
{
  "channel_1": {"enabled": true, "coupling": "DC", "scale": 1.0, "offset": 0.0, "probe": 10},
  "channel_2": {"enabled": false, "coupling": "DC", "scale": 1.0, "offset": 0.0, "probe": 1},
  "timebase": {"scale": 0.001, "offset": 0.0}
}
```

#### `POST /v1/oscilloscope/configure`
Sets channel and timebase parameters.

**Request body:**
```json
{
  "channel": 1,
  "coupling": "DC",
  "scale": 0.5,
  "offset": 0.0,
  "probe": 10,
  "timebase_scale": 0.001
}
```

#### `POST /v1/oscilloscope/capture`
Captures waveform data from one or both channels.

**Request body:**
```json
{
  "channels": [1, 2]
}
```

**Response 200:**
```json
{
  "timestamp": "2026-06-04T14:22:00Z",
  "channel_1": {
    "enabled": true,
    "sample_rate": 1000000.0,
    "timebase": 0.001,
    "volts_per_div": 0.5,
    "offset": 0.0,
    "probe_ratio": 10,
    "num_points": 1400,
    "time_array": [0.0, 0.000001, ...],
    "voltage_array": [0.12, 0.15, ...]
  },
  "channel_2": null
}
```

#### `POST /v1/oscilloscope/screenshot`
Captures a screenshot from the oscilloscope display.

**Response:** `image/png` binary

---

### 5.3 Signal Generator — Siglent SDG-2042X

#### `GET /v1/signal-generator/status`
Returns current output configuration for both channels.

**Response 200:**
```json
{
  "channel_1": {
    "output_enabled": true,
    "waveform": "SINE",
    "frequency": 1000.0,
    "amplitude": 2.0,
    "offset": 0.0,
    "duty_cycle": 50.0,
    "phase": 0.0
  },
  "channel_2": {
    "output_enabled": false,
    "waveform": "SINE",
    "frequency": 1000.0,
    "amplitude": 1.0,
    "offset": 0.0,
    "duty_cycle": 50.0,
    "phase": 0.0
  }
}
```

#### `POST /v1/signal-generator/configure`
Configures one channel. All fields except `channel` are optional — only supplied fields are changed.

**Request body:**
```json
{
  "channel": 1,
  "waveform": "SQUARE",
  "frequency": 1000.0,
  "amplitude": 3.3,
  "offset": 1.65,
  "duty_cycle": 50.0,
  "phase": 0.0,
  "output": true
}
```

**Supported waveform values:** `SINE`, `SQUARE`, `RAMP`, `PULSE`, `NOISE`, `ARB`, `DC`

#### `POST /v1/signal-generator/output`
Enables or disables channel output without changing other settings.

**Request body:**
```json
{"channel": 1, "enabled": true}
```

---

### 5.4 Multimeter — Siglent SDM3055

#### `GET /v1/multimeter/status`
Returns current measurement mode and configuration.

**Response 200:**
```json
{
  "mode": "VOLT:DC",
  "range": "AUTO",
  "resolution": "HIGH"
}
```

#### `POST /v1/multimeter/measure`
Takes a single measurement and returns the result.

**Request body:**
```json
{
  "mode": "VOLT:DC",
  "range": "AUTO"
}
```

**Supported mode values:** `VOLT:DC`, `VOLT:AC`, `CURR:DC`, `CURR:AC`, `RES`, `FRES`, `FREQ`, `CONT`, `DIOD`, `CAP`

**Response 200:**
```json
{
  "timestamp": "2026-06-04T14:22:00Z",
  "mode": "VOLT:DC",
  "value": 3.296,
  "unit": "V"
}
```

#### `POST /v1/multimeter/log`
Takes repeated measurements over a duration.

**Request body:**
```json
{
  "mode": "VOLT:DC",
  "duration_seconds": 60,
  "interval_seconds": 1.0
}
```

**Response 200:**
```json
{
  "mode": "VOLT:DC",
  "unit": "V",
  "count": 60,
  "readings": [
    {"timestamp": "2026-06-04T14:22:00Z", "value": 3.296},
    {"timestamp": "2026-06-04T14:22:01Z", "value": 3.294},
    ...
  ],
  "statistics": {
    "min": 3.291,
    "max": 3.301,
    "mean": 3.296,
    "std_dev": 0.002
  }
}
```

#### `GET /v1/multimeter/log/{log_id}/csv`
Downloads a previous measurement log as CSV.

---

### 5.5 Power Supply — Rigol DP832

#### `GET /v1/power-supply/status`
Returns actual measured values and set points for all three channels.

**Response 200:**
```json
{
  "channel_1": {
    "output_enabled": true,
    "voltage_set": 5.0,
    "current_limit": 1.0,
    "voltage_actual": 4.998,
    "current_actual": 0.234,
    "power_actual": 1.169
  },
  "channel_2": {
    "output_enabled": false,
    "voltage_set": 3.3,
    "current_limit": 0.5,
    "voltage_actual": 0.0,
    "current_actual": 0.0,
    "power_actual": 0.0
  },
  "channel_3": {
    "output_enabled": false,
    "voltage_set": 12.0,
    "current_limit": 2.0,
    "voltage_actual": 0.0,
    "current_actual": 0.0,
    "power_actual": 0.0
  }
}
```

#### `POST /v1/power-supply/configure`
Sets voltage and current limit for one channel.

**Request body:**
```json
{
  "channel": 1,
  "voltage": 5.0,
  "current_limit": 1.0
}
```

#### `POST /v1/power-supply/output`
Enables or disables one channel's output.

**Request body:**
```json
{"channel": 1, "enabled": true}
```

#### `POST /v1/power-supply/all-off`
Disables all three channel outputs immediately. No request body required.

---

## 6. Internal Architecture

```
HTTP Client
     │
     ▼
┌─────────────────────────────────────────────┐
│  FastAPI Application (main.py)              │
│                                             │
│  ┌─────────────┐  ┌──────────────────────┐ │
│  │  Routers    │  │  Instrument Registry  │ │
│  │  (5 files)  │  │  (service singleton)  │ │
│  └──────┬──────┘  └──────────────────────┘ │
│         │                                   │
│  ┌──────▼──────────────────────────────┐   │
│  │  Drivers (one class per instrument) │   │
│  │  base.py → connect / query / write  │   │
│  └──────────────────┬──────────────────┘   │
│                     │                       │
│  ┌──────────────────▼──────────────────┐   │
│  │  Command Logger                     │   │
│  │  (every SCPI command logged)        │   │
│  └─────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
     │
     ▼ PyVISA-py (TCPIP)
┌────────────────────────┐
│  Bench instruments     │
│  SDS1202X-E  (scope)   │
│  SDG-2042X   (siggen)  │
│  SDM3055     (dmm)     │
│  DP832       (psu)     │
└────────────────────────┘
```

**Startup sequence:**
1. Load settings from environment variables
2. Initialise instrument registry (empty)
3. Attempt `*IDN?` query on each configured instrument IP
4. Populate registry with results (reachable/unreachable, identity string)
5. Start uvicorn and begin serving requests

**Instrument unreachability is not a startup failure.** If a bench instrument is powered off, the service starts normally and reports that instrument as unreachable via `/health`. Clients check `/health` before beginning experiments.

---

## 7. Driver Design

All four drivers inherit from `BaseInstrumentDriver` in `drivers/base.py`.

### `drivers/base.py`

```python
from abc import ABC, abstractmethod
import pyvisa

class BaseInstrumentDriver(ABC):
    """Abstract base class for all instrument drivers."""

    def __init__(self, ip: str, port: int = 5025, timeout_ms: int = 5000):
        self.ip = ip
        self.port = port
        self.timeout_ms = timeout_ms
        self._rm = pyvisa.ResourceManager('@py')  # Use pyvisa-py backend
        self._resource = None

    def connect(self) -> bool:
        """Open VISA connection. Returns True if successful."""
        try:
            resource_string = f"TCPIP::{self.ip}::INSTR"
            self._resource = self._rm.open_resource(resource_string)
            self._resource.timeout = self.timeout_ms
            return True
        except Exception:
            self._resource = None
            return False

    def disconnect(self):
        if self._resource:
            self._resource.close()
            self._resource = None

    def query(self, command: str) -> str:
        """Send command and read response."""
        if not self._resource:
            raise RuntimeError("Not connected")
        return self._resource.query(command).strip()

    def write(self, command: str):
        """Send command with no response expected."""
        if not self._resource:
            raise RuntimeError("Not connected")
        self._resource.write(command)

    def identify(self) -> str:
        """Query *IDN? and return identity string."""
        return self.query("*IDN?")

    def is_reachable(self) -> bool:
        """Attempt connection and IDN query. Returns True if instrument responds."""
        try:
            connected = self.connect()
            if connected:
                self.identify()
                return True
        except Exception:
            pass
        finally:
            self.disconnect()
        return False

    @abstractmethod
    def get_status(self) -> dict:
        """Return current instrument status as a dict."""
        ...
```

### Driver naming convention

Each driver file is named: `{role}_{manufacturer}_{model}.py`

- `oscilloscope_siglent_sds1202xe.py`
- `signal_generator_siglent_sdg2042x.py`
- `multimeter_siglent_sdm3055.py`
- `power_supply_rigol_dp832.py`

This means adding a new instrument model in future is a new file — zero changes to existing drivers.

### Key SCPI commands per instrument

**SDS1202X-E (Oscilloscope)**
```
*IDN?                           → Identity
C1:VDIV?                        → Volts per division channel 1
C1:OFST?                        → Channel 1 offset
TDIV?                           → Timebase
C1:WF? DAT2                     → Waveform data channel 1
SCDP                            → Screenshot (returns BMP binary)
C1:CPL DC                       → Set coupling DC
C1:VDIV 0.5V                    → Set 0.5 V/div
```

**SDG-2042X (Signal Generator)**
```
*IDN?                           → Identity
C1:BSWV?                        → Channel 1 basic wave query
C1:BSWV WVTP,SINE               → Set waveform type
C1:BSWV FRQ,1000                → Set frequency 1 kHz
C1:BSWV AMP,2.0                 → Set amplitude 2 Vpp
C1:BSWV OFST,0.0                → Set DC offset
C1:OUTP ON                      → Enable output
C1:OUTP OFF                     → Disable output
```

**SDM3055 (Multimeter)**
```
*IDN?                           → Identity
CONF:VOLT:DC AUTO               → Configure DC voltage auto range
MEAS:VOLT:DC? AUTO              → Measure DC voltage
CONF:CURR:DC AUTO               → Configure DC current
READ?                           → Take measurement in current mode
```

**DP832 (Power Supply)**
```
*IDN?                           → Identity
:MEAS:VOLT? CH1                 → Measure actual voltage channel 1
:MEAS:CURR? CH1                 → Measure actual current channel 1
:MEAS:POWE? CH1                 → Measure actual power channel 1
:SOUR1:VOLT 5.0                 → Set channel 1 voltage
:SOUR1:CURR 1.0                 → Set channel 1 current limit
:OUTP CH1,ON                    → Enable channel 1 output
:OUTP CH1,OFF                   → Disable channel 1 output
:OUTP:ALL OFF                   → Disable all outputs
```

Note: the DP832 uses port 5555 and raw socket mode:
```python
resource_string = f"TCPIP::{self.ip}::5555::SOCKET"
```

---

## 8. Data Models

All request and response bodies are Pydantic models. Place them in `app/models/`. FastAPI validates automatically and includes them in the OpenAPI schema.

Key shared models in `app/models/common.py`:

```python
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class InstrumentInfo(BaseModel):
    reachable: bool
    ip: str
    identity: Optional[str] = None

class HealthResponse(BaseModel):
    status: str                          # "ok" | "degraded"
    uptime_seconds: float
    instruments: dict[str, InstrumentInfo]

class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
```

---

## 9. Docker & Compose

### `Dockerfile`

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system deps for pyvisa-py
RUN apt-get update && apt-get install -y \
    libusb-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### `docker-compose.yml`

```yaml
services:
  bench-instrument-service:
    image: ghcr.io/theagingapprentice/bench-instrument-service:latest
    container_name: bench-instrument-service
    restart: unless-stopped
    env_file:
      - .env
    ports:
      - "8000:8000"       # Direct access during development; close in production
    networks:
      - mitchellnet
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s

networks:
  mitchellnet:
    external: true
```

### `docker-compose.dev.yml`

```yaml
# Development override — adds hot-reload and source mount
# Usage: docker compose -f docker-compose.yml -f docker-compose.dev.yml up
services:
  bench-instrument-service:
    build: .
    volumes:
      - ./app:/app/app
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## 10. Environment Variables

All instrument IPs and configuration are environment variables. Never hardcode them.

```bash
# Instrument IPs — confirmed via lxi discover 2026-06-04
BIS_OSCILLOSCOPE_IP=192.168.2.45
BIS_SIGNAL_GENERATOR_IP=192.168.2.46
BIS_MULTIMETER_IP=192.168.2.20
BIS_POWER_SUPPLY_IP=192.168.2.27

# SCPI timeout in milliseconds (default: 5000)
BIS_SCPI_TIMEOUT_MS=5000

# Log level (default: info)
BIS_LOG_LEVEL=info

# Whether to run instrument discovery on startup (default: true)
BIS_DISCOVER_ON_STARTUP=true
```

Load these in `app/config.py` using pydantic-settings:

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    oscilloscope_ip: str
    signal_generator_ip: str
    multimeter_ip: str
    power_supply_ip: str
    scpi_timeout_ms: int = 5000
    log_level: str = "info"
    discover_on_startup: bool = True

    class Config:
        env_prefix = "BIS_"

settings = Settings()
```

---

## 11. CI/CD

### `.github/workflows/deploy.yml`

```yaml
name: Deploy BIS

on:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r requirements-dev.txt
      - run: pytest tests/ -v

  deploy:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to production
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.PROD_HOST }}
          username: ${{ secrets.PROD_USER }}
          key: ${{ secrets.PROD_SSH_KEY }}
          script: |
            cd /home/andrew/services/bench-instrument-service
            git pull origin main
            docker compose pull
            docker compose up -d --no-deps bench-instrument-service
            sleep 5
            curl -f http://localhost:8000/health || exit 1
```

---

## 12. Phased Delivery

### Phase 1 — Core Service (build this first)

The working API for all four instruments. No session management yet — one client at a time is fine for solo use.

**Deliverables:**
- `app/main.py` with startup/shutdown and all routers registered
- `app/config.py` with pydantic-settings
- All four driver files (inheriting from `base.py`)
- All five routers (`health`, `instruments`, `oscilloscope`, `signal_generator`, `multimeter`, `power_supply`)
- All Pydantic models
- `Dockerfile` and `docker-compose.yml`
- GitHub Actions deploy workflow
- Basic pytest test suite with mocked instruments
- `README.md`

**Definition of done for Phase 1:**
- `GET /health` returns correct reachability for all connected instruments
- `POST /v1/oscilloscope/capture` returns waveform JSON with time and voltage arrays
- `POST /v1/signal-generator/configure` sets waveform on SDG-2042X and confirms via status query
- `GET /v1/power-supply/status` returns actual measured V, I, P for all three channels
- `POST /v1/multimeter/log` runs a 10-second measurement series and returns results with statistics
- Container deploys cleanly and is reachable at `https://mitchellnet.local/api/bench/`
- Existing Virtual Bench project can replace its PyVISA calls with BIS HTTP calls

### Phase 2 — Session Management

Adds exclusive instrument reservation so two clients can't conflict.

**Deliverables:**
- `app/services/session_manager.py`
- `POST /v1/sessions/acquire` and `DELETE /v1/sessions/{session_id}`
- Session timeout and auto-release
- All instrument endpoints reject requests from non-session holders when an active session exists

### Phase 3 — Enhancements

Quality-of-life additions.

**Deliverables:**
- Simple web status dashboard (served by FastAPI static files at `/`)
- `bench_client.py` Python client library with convenience wrappers around the HTTP calls
- Webhook support for long-running measurement jobs (multimeter log > 60 seconds)
- Support for adding new instrument models via additional driver files only

---

## 13. Testing Strategy

### Unit tests — instrument drivers

Drivers are tested with a mock VISA resource, not real instruments. The mock records every `write()` call and returns canned `query()` responses.

```python
# tests/conftest.py
import pytest
from unittest.mock import MagicMock

@pytest.fixture
def mock_visa_resource():
    resource = MagicMock()
    resource.query.return_value = "Siglent Technologies,SDM3055,SDM35HBC900580,1.02.01.28"
    return resource
```

### Integration tests — live instruments (manual)

A separate `tests/integration/` directory contains tests that require real instrument connectivity. These are never run in CI — only run manually on the bench by running:

```bash
BIS_OSCILLOSCOPE_IP=192.168.2.45 pytest tests/integration/ -v
```

### API tests — FastAPI test client

All routers are tested using FastAPI's built-in `TestClient` (via httpx). Instrument dependencies are mocked via FastAPI dependency overrides — no real instruments required in CI.

```python
# tests/test_health.py
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health_returns_200():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] in ("ok", "degraded")
```

---

## Appendix: NGINX Configuration (in InternalWebServer repo)

Add this `location` block to the NGINX config in InternalWebServer:

```nginx
location /api/bench/ {
    proxy_pass http://bench-instrument-service:8000/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # Longer timeout for waveform captures and measurement logging
    proxy_read_timeout 120s;
    proxy_send_timeout 120s;
}
```

The `proxy_read_timeout 120s` is important — multimeter logging jobs and waveform captures can take longer than NGINX's default 60-second timeout.

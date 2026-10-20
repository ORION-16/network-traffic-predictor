# Network Traffic Predictor

A modern, full-stack network telemetry and packet monitoring platform built with **React**, **FastAPI**, and **Scapy**.

Phase 1 delivers real-time packet metadata capture, safe header-only telemetry extraction, interactive dual-axis traffic visualization, protocol composition analysis, streaming WebSockets, and CSV export.

---

## Architecture Overview

The system is organized strictly by system responsibilities:

- **Frontend (`frontend/`)**: React 19, Vite, Tailwind CSS, Plotly.js.
  - `src/components/`: Reusable telemetry widgets, metric cards, control buttons, interface selector, and packet feed.
  - `src/charts/`: Dual-axis live traffic time-series chart and protocol distribution donut chart.
  - `src/hooks/`: Resilient WebSocket connection hook with cursor-based incremental streaming and auto-reconnect.
  - `src/services/`: REST API client layer.
  - `src/pages/`: Main monitoring dashboard.
- **Backend (`backend/`)**: Python, FastAPI, Uvicorn, Scapy, Pydantic v2.
  - `app/main.py`: Application lifespan management, CORS middleware, route mounting.
  - `api/routes/`: REST endpoints for interfaces (`/api/interfaces`) and capture control (`/api/capture`).
  - `api/websockets.py`: WebSocket streamer (`/ws/capture`) with cursor-based delta tracking.
  - `capture/`: Thread-safe capture lifecycle worker (`sniffer.py`) and global state machine (`state.py`).
  - `processing/`: Safe packet metadata parsing (`parser.py`) and rolling telemetry aggregator (`aggregator.py`).
  - `analytics/`: Reserved for statistical analysis modules.
  - `ml/`: Reserved for Phase 2 machine learning, PCA, and anomaly detection.
  - `schemas/`: Pydantic data schemas.
  - `tests/`: Automated test suite with mocked Scapy workers (no root required for CI/testing).

---

## Prerequisites

- **Python**: 3.10+ (tested with Python 3.14)
- **Node.js**: 18+ (tested with Node 24 and npm 11)
- **OS**: macOS or Linux

---

## Setup & Running

### 1. Backend Setup

```bash
cd backend

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy environment configuration
cp .env.example .env
```

#### Running the Backend

Raw packet capture requires appropriate OS privileges. See [docs/PERMISSIONS.md](docs/PERMISSIONS.md) for details.

**macOS (Recommended for Development)**:
```bash
# Run with elevated privileges for raw BPF access
sudo .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

*Or grant read/write access to macOS BPF devices once per boot:*
```bash
sudo chown $(whoami):admin /dev/bpf*
sudo chmod 660 /dev/bpf*
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Linux**:
```bash
# Set capability once on the virtualenv binary (no root required to run!)
sudo setcap cap_net_raw,cap_net_admin+eip $(readlink -f .venv/bin/python)

# Run normally
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Verify backend health:
```bash
curl http://localhost:8000/api/health
# {"status":"ok"}
```

---

### 2. Frontend Setup

In a separate terminal window:

```bash
cd frontend

# Install dependencies
npm install

# Start Vite development server
npm run dev
```

Open [http://localhost:5173](http://localhost:5173) in your browser.

---

## Operating Instructions

1. **Select Network Interface**: Use the interface dropdown in the top control bar to pick your target network interface (e.g., `en0` on macOS Wi-Fi, `eth0` on Linux, or `lo0`/`lo` for local traffic).
2. **Start Capture**: Click the green **Start Capture** button.
3. **Generate Traffic**: Browse websites, send requests, or run `ping 8.8.8.8` in another terminal.
4. **Observe Live Telemetry**:
   - Real-time counters: Total Packets, Total Volume, Packet Rate (pkts/s), and Throughput (bytes/s).
   - Traffic Intensity chart: Live dual-axis line chart updating at 1 Hz.
   - Protocol Composition chart: Donut chart displaying Layer 3/4 distribution (TCP, UDP, ICMP, ARP).
   - Recent Packet Feed: Scrollable table with instantaneous search and protocol filtering.
5. **Stop Capture**: Click **Stop Capture** to gracefully shut down the Scapy worker thread.
6. **Export Metadata**: Click **Export CSV** to download captured packet headers (`timestamp`, `src_ip`, `dst_ip`, `protocol`, `length`, `info`).

---

## API Specification

### REST Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/health` | `GET` | Health status probe (`{"status":"ok"}`) |
| `/api/interfaces` | `GET` | List available network interfaces with status & loopback flags |
| `/api/capture/status` | `GET` | Current capture status, active interface, and totals |
| `/api/capture/start` | `POST` | Start packet sniffer worker `{ "interface": "en0" }` |
| `/api/capture/stop` | `POST` | Terminate active sniffer worker |
| `/api/capture/export/csv` | `GET` | Download captured metadata as CSV attachment |

### WebSocket Endpoint (`/ws/capture`)

Streams telemetry updates at 1 Hz:
```json
{
  "metrics": {
    "total_packets": 1284,
    "total_bytes": 1048576,
    "packet_rate": 32.5,
    "throughput": 26214.4,
    "protocol_distribution": { "TCP": 950, "UDP": 310, "ICMP": 24 }
  },
  "new_packets": [
    {
      "timestamp": 1729432800.123,
      "src_ip": "192.168.1.15",
      "dst_ip": "142.250.190.46",
      "protocol": "TCP",
      "length": 1420,
      "info": "49821→443 [PA]"
    }
  ],
  "traffic_series": [
    { "timestamp": 1729432799, "packets": 31, "bytes": 24500 }
  ],
  "is_capturing": true,
  "error": null
}
```

---

## Automated Tests

Run backend unit tests (uses mocked Scapy fixtures, requiring no root privileges):

```bash
cd backend
source .venv/bin/activate
pytest tests/ -v
```

---

## Documentation

- [System Architecture](docs/ARCHITECTURE.md)
- [Permissions & Security Guide](docs/PERMISSIONS.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)

---

## Known Limitations & Phase 2 Roadmap

### Current Limitations (Phase 1)
- Bounded in-memory retention: Buffer holds up to 10,000 packets (`MAX_PACKETS`) to prevent memory exhaustion.
- Header-only parsing: Payloads are intentionally discarded for security and privacy.
- Single active capture worker: One interface can be actively sniffed at a time.

### Phase 2 Roadmap
- **PCA & Dimensionality Reduction** in `backend/ml/` for packet feature space projection.
- **Unsupervised Anomaly Detection** (Isolation Forest, DBSCAN) to flag unusual traffic surges or port scans.
- **Traffic Forecasting** using sliding-window statistical and regression models.

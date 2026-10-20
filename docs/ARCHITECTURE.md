# System Architecture — Network Traffic Predictor (Phase 1)

This document describes the architectural design, component responsibilities, data flow, concurrency patterns, and communication protocols for Phase 1.

---

## 1. System Responsibilities & Boundaries

The codebase is strictly organized by system responsibilities:

```
MINIPROJECT/
├── backend/
│   ├── app/                # Application bootstrap & lifespan management
│   │   ├── __init__.py
│   │   └── main.py         # FastAPI application, CORS middleware, route mounting
│   ├── api/                # Network transport boundary
│   │   ├── routes/         # REST API endpoints
│   │   │   ├── capture.py  # Capture lifecycle control & CSV export
│   │   │   └── interfaces.py # Interface enumeration
│   │   └── websockets.py   # WebSocket handler with cursor-based streaming
│   ├── capture/            # Low-level network sniffer worker
│   │   ├── sniffer.py      # Scapy sniff() integration & worker thread lifecycle
│   │   └── state.py        # Thread-safe global CaptureState singleton
│   ├── processing/         # Data transformation & metrics computation
│   │   ├── parser.py       # Safe packet header parsing (zero payload storage)
│   │   └── aggregator.py   # Ring-buffered in-memory aggregation & telemetry math
│   ├── analytics/          # Future statistical models & analysis (Phase 2)
│   ├── ml/                 # Future PCA, clustering, anomaly detection (Phase 2+)
│   ├── schemas/            # Pydantic data transfer models & validation contracts
│   ├── core/               # Environment & global settings
│   └── tests/              # Automated unit and integration tests (mocked capture)
│
├── frontend/
│   ├── src/
│   │   ├── components/     # Reusable UI widgets (cards, badges, tables, selectors)
│   │   ├── pages/          # Full page layout (Dashboard)
│   │   ├── hooks/          # React hooks (useCaptureSocket with auto-reconnect)
│   │   ├── services/       # REST API client
│   │   └── charts/         # Plotly-powered real-time interactive charts
│   └── vite.config.js      # Vite build configuration with Tailwind CSS plugin
│
└── docs/                   # Architectural, permission, and troubleshooting guides
```

---

## 2. High-Level Data Flow

```
[ Network Interface (e.g. en0 / eth0) ]
                 │
                 ▼ (Raw Layer 2/3 Frames)
       [ Scapy Sniffer Thread ]
                 │
                 ▼ (Raw Packet)
     [ processing/parser.py ] ──► Extracts Safe Header Metadata Only
                 │                 (Timestamp, IPs, Protocol, Length, Ports)
                 ▼ (PacketMeta)
   [ processing/aggregator.py ] ──► Thread-Safe Ring Buffer (Bounded Deque)
                 │                 - Computes Rolling Packet Rate
                 │                 - Computes Rolling Throughput
                 │                 - Protocol Distribution Tally
                 │                 - 1-Second Time Series Buckets
                 │
        ┌────────┴────────┐
        ▼                 ▼
[ REST API Router ]   [ WebSocket Streamer (/ws/capture) ]
 - /api/interfaces     - Pushes incremental updates at 1 Hz
 - /api/capture/start  - Cursor-based delta tracking (no retransmissions)
 - /api/capture/stop   - Auto-reconnection support
 - /api/capture/export
        │                 │
        └────────┬────────┘
                 ▼
       [ React Frontend Dashboard ]
        - Plotly Traffic Chart (Dual-Axis)
        - Plotly Protocol Donut Chart
        - Telemetry Cards & Live Badges
        - Searchable Recent Packets Feed
        - CSV Download
```

---

## 3. Concurrency & Thread Safety

- **Non-blocking Capture Worker**:
  Scapy's `sniff()` is blocking. It runs inside a dedicated daemon thread (`sniffer-{interface}`).
- **Graceful Worker Termination**:
  A `threading.Event` (`stop_event`) is passed to Scapy's `stop_filter`. When the user requests a capture stop via `POST /api/capture/stop`, the event is set, Scapy exits cleanly on the next packet or timeout, and `worker.join(timeout=5.0)` reaps the thread.
- **Aggregator Mutex**:
  All methods in `Aggregator` are guarded by a reentrant `threading.Lock`. Reads from the async WebSocket coroutine and writes from the synchronous Scapy worker thread never corrupt state.
- **Bounded In-Memory Footprint**:
  Storage uses `collections.deque(maxlen=10000)`. Memory consumption remains strictly bounded regardless of how long the capture runs.

---

## 4. Communication Protocol

### REST Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Backend liveness check |
| `GET` | `/api/interfaces` | Enumerate local network interfaces |
| `GET` | `/api/capture/status` | Read current capture status and totals |
| `POST` | `/api/capture/start` | Start capture on `{ "interface": "en0" }` |
| `POST` | `/api/capture/stop` | Stop active capture worker |
| `GET` | `/api/capture/export/csv` | Stream metadata as downloadable CSV |

### WebSocket Endpoint (`/ws/capture`)

Clients connect via WebSocket to receive live telemetry without polling.
- **Interval**: 1.0 second (configurable via `WS_INTERVAL`).
- **Cursor Tracking**: The server tracks client position (`total_ever - last_seen`) and only transmits newly ingested packets, preventing redundant bandwidth usage.
- **Reconnection**: When the frontend reconnects, it retrieves current metrics and resumes streaming from the active cursor without losing previous UI state.

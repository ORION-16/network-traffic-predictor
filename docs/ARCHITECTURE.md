# System Architecture — Network Traffic Predictor

Counter monitoring, statistical forecasting, and the original packet-capture path share one FastAPI process and one React dashboard.

Interface counters are the source for live Mbps, history, forecasts, and evaluation. The dashboard shows that graph and a short forecast summary. Packet capture, protocol charts, and the scenario simulator are not on the page. The capture API remains for the existing tests. The simulator module was removed, so it cannot write anywhere.

The sections below keep the original capture design, then describe the monitoring path added on top of it. Real-network checks in this repository were run on Windows. macOS and Linux capture notes were not re-verified here.

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
│   │   │   ├── interfaces.py # Interface enumeration
│   │   │   └── monitoring.py # Counters, history, forecast, capacity, congestion
│   │   └── websockets.py   # WebSocket handler with cursor-based streaming
│   ├── capture/            # Low-level network sniffer worker
│   │   ├── sniffer.py      # Scapy sniff() integration & worker thread lifecycle
│   │   └── state.py        # Thread-safe global CaptureState singleton
│   ├── processing/         # Data transformation & metrics computation
│   │   ├── parser.py       # Safe packet header parsing (zero payload storage)
│   │   └── aggregator.py   # Ring-buffered in-memory aggregation & telemetry math
│   ├── monitoring/         # Interface discovery, counter rates, SQLite, ICMP probe
│   ├── analytics/          # Moving average, exponential smoothing, congestion assessment
│   ├── ml/                 # Unused. No model is loaded from this package
│   ├── data/               # Local SQLite observations (gitignored)
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

---

## 5. Interface-counter monitoring

```
psutil.net_io_counters(pernic=True)  →  one selected interface
        │
        ▼
monitoring/rates.py
  Mbps = byte_delta * 8 / elapsed_seconds / 1_000_000
  qualities: baseline, ok, gap, counter_reset, interface_changed, too_soon, unsupported
        │
        ▼
monitoring/store.py  (SQLite, WAL)
  observations unique on (interface_name, sampled_at_ms)
  settings JSON for capacity, thresholds, selected interface
  retention: RETENTION_HOURS (default 24)
        │
        ▼
analytics/forecasting.py
  latest contiguous run only (gap within 0.5×–1.5× the sample interval)
  moving average, simple exponential smoothing, persistence baseline
  walk-forward evaluation; no shuffling; no gap fill
        │
analytics/assessment.py
  utilization only from capacity_source == "user"
  spikes, probe evidence, and forecast breaches stay separate alert bases
        │
        ▼
GET /api/monitoring/dashboard   (frontend polls about once a second)
```

`monitoring/collector.py` is a singleton started in the FastAPI lifespan and stopped on shutdown. The first sample after start or an interface change stores counters and leaves rates null. `too_soon` samples (elapsed under 0.05 s) are not stored. A gap or a decreased byte counter stores the new counters with null rates and advances the previous reading so the next delta is not computed across the break.

`monitoring/interfaces.py` lists psutil interfaces and, on Windows, merges a fixed `Get-NetAdapter` query (`shell=False`, no user-supplied command). The default route is the local address of a UDP connect to `1.1.1.1:443`. Responses omit IP and MAC addresses. `reported_link_speed_mbps` is informational. Assessment ignores it unless `capacity_source` is `user`, which the NIC path never sets.

`monitoring/probe.py` runs the system `ping` with a validated hostname or IPv4, count clamped to 1–5, and no shell. Loss and jitter describe that probe only.

Forecast state is not checkpointed. Each request rebuilds the level from stored valid observations. A one-step empirical residual interval (at least 30 residuals) is attached to the forecast payload only when the horizon is one sample. Longer horizons say that the one-step quantiles were not relabeled as a horizon interval.

The React simulator (`src/lib/simulatorMath.js`) classifies hypothetical demand against a typed capacity. It has no `fetch`. Preset values 30, 85, and 130 Mbps exist only there.

---

## 6. What is still in memory

Packet capture still uses a `deque(maxlen=10000)` in the aggregator. That buffer is independent of `observations.sqlite`. Clearing the packet feed does not delete counter history. Deleting capacity does not delete observations.

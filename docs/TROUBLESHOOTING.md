# Troubleshooting Guide — Network Traffic Predictor

Checked on Windows 11 during implementation. macOS and Linux commands below are the original capture guidance and were not re-run here.

---

## 1. Counter monitoring

### Dashboard stays on "unavailable" or the browser shows a CORS error

- The API allows `http://localhost:5173` and `http://127.0.0.1:5173` by default. Open one of those URLs.
- GET requests from the frontend do not send `Content-Type`, so they do not trigger a preflight. A custom `CORS_ORIGINS` that omits the page's origin will block the dashboard.
- Confirm `curl http://127.0.0.1:8000/api/health` returns JSON with `"status": "ok"`.

### Rates are blank on the first sample, or after switching interface

- The first reading is a baseline. Mbps stays null until a second reading of the same interface arrives. That is not a zero-traffic measurement.
- Selecting another interface starts a new baseline. Counters are not differenced across interfaces.

### History exists, but the forecast says the latest run is short

- A gap longer than `max(5 × SAMPLE_INTERVAL, 15 seconds)` ends the contiguous run. Restarting the backend does this. Older rows stay stored and are excluded from the model. They are not interpolated.
- A forecast needs 2 equally spaced valid points for exponential smoothing, or `window` points (default 12) for the moving average. Evaluation needs one more origin than that, on the shared method set.

### "Unknown capacity" and no congestion verdict

- Until you save a capacity, utilization is not calculated. The NIC speed line (for example `1201 Mbps reported`) is not capacity.
- Latency and loss readings do not become a congestion verdict until you set those thresholds. A statistical spike is labeled separately and is not congestion evidence.
- Clear capacity with the dashboard button or `DELETE /api/capacity`. Clearing capacity does not delete observations.

### Probe status is an error, or loss looks like a small sample

- The probe is a few ICMP echoes. `DISABLE_PROBES=true` skips it. A failed ping is a failed probe, not 0% loss.
- Loss percent is the missing share of that probe only.

### Throughput looks nothing like the NIC speed

- Decimal Mbps is the counter delta over the elapsed second, not the link rate. A quiet machine at well under 1 Mbps on a 1201 Mbps-reported adapter is a real reading. It is not a broken conversion.

---

## 2. Packet capture

The packet feed is optional. An empty "Awaiting traffic data" state does not mean interface counters failed. Counters do not use Scapy.

### "Permission denied capturing on '<interface>'" or `[Errno 1] Operation not permitted`

### "Permission denied capturing on '<interface>'" or `[Errno 1] Operation not permitted`

- **Cause**: Packet sniffing via raw sockets requires superuser or specific capture permissions on POSIX systems.
- **Resolution**:
  - **macOS**: Run the backend with `sudo`:
    ```bash
    cd backend
    source .venv/bin/activate
    sudo .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
    ```
    Or grant read/write access to BPF devices:
    ```bash
    sudo chown $(whoami):admin /dev/bpf*
    sudo chmod 660 /dev/bpf*
    ```
  - **Linux**: Assign file capabilities to the Python executable:
    ```bash
    sudo setcap cap_net_raw,cap_net_admin+eip $(readlink -f backend/.venv/bin/python)
    ```

### "Interface '<name>' not found" or empty interface list

- **Cause**: Network interface names vary across operating systems.
  - macOS typically uses `en0` (Wi-Fi), `en1`/`en2` (Ethernet/adapters), and `lo0` (loopback).
  - Linux uses `eth0`, `wlan0`, `enp3s0`, or `lo`.
- **Resolution**:
  - Click the **Refresh Interfaces** button in the dashboard navigation bar.
  - Check interfaces in terminal:
    - macOS / Linux: `ifconfig -a`
    - Linux: `ip link show`
  - For counter monitoring, prefer the option marked `default route`. The label includes `physical`, `virtual`, or `loopback` when the OS provided that classification. A disconnected adapter can still appear in the list.

### "Capture is already running" (HTTP 409)

- **Cause**: An active capture worker is already bound to an interface.
- **Resolution**: Click **Stop Capture** before initiating a capture on a new interface.

---

## 3. WebSocket connection issues

### Dashboard shows "Disconnected" badge or "WebSocket connection error"

- **Cause 1**: The FastAPI backend is not running on `http://localhost:8000`.
  - **Check**: Run `curl http://localhost:8000/api/health` — it should return `{"status":"ok"}`.
- **Cause 2**: Port conflict on 8000.
  - **Check**: On Windows, `netstat -ano | findstr :8000`. On macOS or Linux, `lsof -i :8000`.
- **Cause 4**: On Windows, closing the capture socket can log `ConnectionResetError` / WinError 10054. The capture hook reconnects. Interface-counter charts use HTTP polling and keep updating if that socket blips.
- **Cause 3**: Custom API URL.
  - If running on a non-standard port or host, set `VITE_API_URL` in `frontend/.env`:
    ```ini
    VITE_API_URL=http://localhost:8000
    ```

---

## 4. Frontend build and display

### Chart appears empty after clicking "Start Capture"

- **Cause**: The selected interface might not have active traffic at the moment.
- **Verification**:
  - Open a new terminal and generate network traffic (e.g., `ping -c 5 8.8.8.8` or browse any web page).
  - If capturing on loopback (`lo0` on macOS or `lo` on Linux), run `curl http://localhost:8000/api/health` repeatedly to see loopback packets.

---

## 5. Stopping the servers

If you need to force-stop any lingering background uvicorn or sniffer processes:

```bash
# Locate and terminate uvicorn processes on port 8000
kill $(lsof -t -i:8000) 2>/dev/null || true
```

On Windows, stop the `uvicorn` and `npm run dev` terminals, or end the process IDs shown by `netstat -ano | findstr :8000` and `findstr :5173`. Stopping the backend ends collection. It does not delete `backend/data/observations.sqlite`.

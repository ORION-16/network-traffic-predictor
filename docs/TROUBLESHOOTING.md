# Troubleshooting Guide — Network Traffic Predictor

This guide covers common issues encountered during setup, startup, live capture, and dashboard streaming.

---

## 1. Capture Issues

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
  - Select the active interface that displays `(Active)` in the dropdown.

### "Capture is already running" (HTTP 409)

- **Cause**: An active capture worker is already bound to an interface.
- **Resolution**: Click **Stop Capture** before initiating a capture on a new interface.

---

## 2. WebSocket Connection Issues

### Dashboard shows "Disconnected" badge or "WebSocket connection error"

- **Cause 1**: The FastAPI backend is not running on `http://localhost:8000`.
  - **Check**: Run `curl http://localhost:8000/api/health` — it should return `{"status":"ok"}`.
- **Cause 2**: Port conflict on 8000.
  - **Check**: Run `lsof -i :8000` to inspect processes occupying port 8000.
- **Cause 3**: Custom API URL.
  - If running on a non-standard port or host, set `VITE_API_URL` in `frontend/.env`:
    ```ini
    VITE_API_URL=http://localhost:8000
    ```

---

## 3. Frontend Build & Display Issues

### Chart appears empty after clicking "Start Capture"

- **Cause**: The selected interface might not have active traffic at the moment.
- **Verification**:
  - Open a new terminal and generate network traffic (e.g., `ping -c 5 8.8.8.8` or browse any web page).
  - If capturing on loopback (`lo0` on macOS or `lo` on Linux), run `curl http://localhost:8000/api/health` repeatedly to see loopback packets.

---

## 4. Safe Shutdown & Cleanup

If you need to force-stop any lingering background uvicorn or sniffer processes:

```bash
# Locate and terminate uvicorn processes on port 8000
kill $(lsof -t -i:8000) 2>/dev/null || true
```

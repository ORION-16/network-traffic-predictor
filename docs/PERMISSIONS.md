# Network Traffic Predictor — Permissions & Security Guide

Packet sniffing requires raw packet access at Layer 2/3 of the network stack. Operating systems restrict raw packet capture to prevent unprivileged processes from snooping on user traffic.

This document describes the minimum operating system permissions required to run the Scapy capture worker on macOS and Linux.

---

## Security Architecture Principles

1. **Header-Only Capture**:
   - The capture engine *only* parses and extracts safe packet metadata: timestamp, source IP, destination IP, protocol number, packet length, and TCP/UDP port numbers with TCP flags.
   - **Payload contents are never read, stored in memory, logged, or exposed** through API endpoints or WebSocket channels.

2. **Least Privilege Separation**:
   - Only the Python backend process requires raw packet capture privileges.
   - The Vite/React frontend runs completely unprivileged in standard user space.
   - Do **not** run the frontend dev server or terminal with `sudo`.

3. **No Silent Fallbacks**:
   - If permissions are missing, the backend raises an explicit `PermissionError` and reports an actionable error status to the frontend.
   - The backend will **never** silently substitute simulated or fake network traffic when real capture fails.

---

## macOS Permission Setup

macOS uses Berkeley Packet Filter (`/dev/bpf*`) devices for low-level packet capture. Accessing `/dev/bpf*` requires elevated privileges or appropriate device group permissions.

### Option A: Run Backend with `sudo` (Recommended for Development)

Run only the Python backend worker with elevated privileges:

```bash
cd backend
source .venv/bin/activate
sudo .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Option B: Grant Read/Write Permissions to BPF Devices

To run without `sudo` on macOS, grant read/write access to the BPF device nodes for your user or group:

```bash
# Grant current user read/write access to BPF devices
sudo chown $(whoami):admin /dev/bpf*
sudo chmod 660 /dev/bpf*
```

> **Note**: macOS resets permissions on `/dev/bpf*` upon system reboot. For permanent non-root access, create a LaunchDaemon or install Wireshark's ChmodBPF package (`brew install --cask wireshark-chmodbpf`).

---

## Linux Permission Setup

Linux uses `AF_PACKET` raw sockets for Scapy packet inspection.

### Option A: Linux File Capabilities (Recommended — No Root Required)

Grant Python the `CAP_NET_RAW` and `CAP_NET_ADMIN` capabilities without giving full superuser access:

```bash
# Locate your python3 executable inside the virtualenv
VENV_PYTHON=$(readlink -f backend/.venv/bin/python)

# Set capabilities
sudo setcap cap_net_raw,cap_net_admin+eip "$VENV_PYTHON"
```

Verify capabilities:
```bash
getcap "$VENV_PYTHON"
# Output: /path/to/backend/.venv/bin/python cap_net_admin,cap_net_raw=eip
```

Now you can run the backend as a normal user:
```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Option B: Run Backend with `sudo`

```bash
cd backend
source .venv/bin/activate
sudo .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

---

## Verifying Network Interface Names

- **macOS**: Common interfaces are `en0` (Wi-Fi), `en1`/`en2` (Ethernet/Thunderbolt), and `lo0` (loopback).
- **Linux**: Common interfaces are `eth0`, `wlan0`, `enp3s0`, or `lo`.

You can view available interfaces in the dashboard dropdown or check manually:
```bash
# macOS / Linux
ifconfig -a
# Linux modern
ip link show
```

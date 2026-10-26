# Network Traffic Predictor — Permissions & Security Guide

## Interface counters and probes

Live Mbps does not read packet payloads. `psutil.net_io_counters` reads OS interface totals. On the Windows machine used for verification, that call succeeded as a normal user. No administrator shell was required for collection, SQLite, forecasting, or the dashboard.

The latency probe runs `ping` against `LATENCY_PROBE_TARGET` (default `1.1.1.1`). The target is configured on the server. Clients cannot supply a host, a count above 5, or a shell string. ICMP may be blocked by policy; the API then returns the probe failure instead of a zero-loss result.

Windows adapter kind, media, and NIC speed come from a fixed `Get-NetAdapter` command. The interface name is not interpolated into that command. If the command fails, interfaces still list from psutil and the kind fields say the adapter metadata is unavailable.

The API does not return addresses or MAC addresses. Documentation and the real-network result file omit them as well.

`DEMO_MODE` can synthesize packets for the optional sniffer. It does not synthesize counter observations. Leave it `false`.

## Packet capture

Packet sniffing requires raw packet access at Layer 2/3. That privilege is separate from counter monitoring, and capture is optional. The stored throughput always comes from OS counters.

### Windows (verified on Windows 11)

- **Npcap.** Scapy needs [Npcap](https://npcap.com). On the verification machine, the Npcap service was running, `C:\Windows\System32\Npcap` existed, and capture worked from a normal user shell. Npcap was installed without "Restrict Npcap driver's access to Administrators only". With that option on, capture needs an elevated shell, and the API returns `permission_denied` instead of a rate.
- **Interface names.** Use the Windows interface name, for example `Wi-Fi` or `Ethernet`. The backend maps it to Scapy's Npcap device. `GET /api/capture/availability` reports whether capture can be attempted and why not. It starts nothing.
- **Accuracy.** With promiscuous mode off, capture matched the counters within about 2% at idle. During a 20 MB download it saw about 55% of the received packets, because the Python callback drops packets under load. Use the result as a diagnostic, not as a throughput source.
- **Without Npcap.** If Npcap is missing, availability says so. Counter monitoring, forecasting, and alerts are unaffected.

The macOS and Linux steps below are the original project guidance and were not re-tested.

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

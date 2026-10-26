"""Measure one real HTTPS download with Scapy and OS counters at the same time.

Run from backend/:  python -m scripts.measure_download "Wi-Fi" 20000000
The download is real traffic generated on this host. Its body is discarded.
"""

from __future__ import annotations

import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from capture.packet_rates import probe_capture  # noqa: E402

URL = "https://speed.cloudflare.com/__down?bytes={size}"


def download(size: int, out: dict) -> None:
    started = time.monotonic()
    received = 0
    request = urllib.request.Request(URL.format(size=size), headers={"User-Agent": "network-traffic-predictor/0.2 measurement"})
    with urllib.request.urlopen(request, timeout=60) as response:
        while True:
            chunk = response.read(65536)
            if not chunk:
                break
            received += len(chunk)
    out["body_bytes"] = received
    out["download_seconds"] = time.monotonic() - started


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "Wi-Fi"
    size = int(sys.argv[2]) if len(sys.argv) > 2 else 20_000_000
    meta: dict = {}
    worker = threading.Thread(target=download, args=(size, meta))
    timer = threading.Timer(1.0, worker.start)
    timer.start()
    result = probe_capture(name, 12.0)
    worker.join(timeout=60)
    result["download"] = meta
    if meta.get("body_bytes"):
        result["download"]["body_mbps_over_window"] = meta["body_bytes"] * 8 / result.get("elapsed_seconds", 12.0) / 1_000_000
    print(json.dumps(result, indent=2, default=str))

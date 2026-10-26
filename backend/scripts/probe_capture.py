"""Check whether Scapy can capture on one interface, and compare with OS counters.

Run from backend/:  python -m scripts.probe_capture "Wi-Fi" 5
Only packet lengths and direction are counted. Payloads are not stored.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from capture.packet_rates import probe_capture  # noqa: E402

if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "Wi-Fi"
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0
    started = time.time()
    print(json.dumps(probe_capture(name, seconds), indent=2, default=str))
    print(f"elapsed {time.time() - started:.2f}s")

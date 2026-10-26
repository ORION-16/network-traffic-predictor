"""Read the running backend and the recent stored intervals. Read-only.

Run from backend/:  python -m scripts.check_live
"""

from __future__ import annotations

import json
import statistics
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from monitoring.collector import default_db_path  # noqa: E402
from monitoring.store import Store  # noqa: E402

BASE = "http://127.0.0.1:8000"


def get(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=30) as response:
        return json.loads(response.read())


if __name__ == "__main__":
    started = time.perf_counter()
    dash = get("/api/monitoring/dashboard?history_seconds=900&horizon_seconds=300")
    elapsed = time.perf_counter() - started
    alert = dash["rise_alert"]
    print("dashboard_seconds", round(elapsed, 3))
    print("collection", dash["collection"]["status"], dash["collection"]["freshness"], dash["collection"]["interface_mode"])
    print("packet_capture", dash["collection"]["packet_capture"]["status"])
    print("thresholds", dash["thresholds"]["receive"], dash["thresholds"]["transmit"], dash["thresholds"]["sources"])
    print("alert", alert["state"], alert["label"], alert["directions"])
    print("explanation", alert["explanation"])
    live = (alert.get("threshold_alert") or {}).get("live") or {}
    for side in ("receive", "transmit"):
        item = live.get(side) or {}
        print(side, {key: item.get(key) for key in ("active", "latest_mbps", "threshold_mbps", "last_alert_at", "last_recovery_at", "episodes")})
    print("alert_events", len(dash["alert_events"]), "transitions", len(dash["transitions"]))
    print("history_points", len(dash["history"]), dash["history_resolution"])
    store = Store(default_db_path())
    rows = store.history(dash["collection"]["selected_interface"], start=time.time() - 120)
    intervals = [row["interval_seconds"] for row in rows if row.get("interval_seconds") is not None]
    if intervals:
        print(
            "intervals_last_120s n", len(intervals),
            "p50", round(statistics.median(intervals), 4),
            "min", round(min(intervals), 4),
            "max", round(max(intervals), 4),
            "outside_0.5_1.5", sum(1 for value in intervals if not 0.5 <= value <= 1.5),
        )

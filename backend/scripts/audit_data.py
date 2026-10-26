"""Read-only audit of the stored observations and forecasts.

Run from backend/:  python -m scripts.audit_data
Nothing is written. Output is real stored data, not fixtures.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from monitoring.collector import default_db_path  # noqa: E402


def _quantiles(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    ordered = sorted(values)

    def q(p: float) -> float:
        return ordered[int(p * (len(ordered) - 1))]

    return {
        "n": len(ordered),
        "p50": q(0.5),
        "p90": q(0.9),
        "p99": q(0.99),
        "max": ordered[-1],
        "zeros": sum(1 for value in ordered if value == 0),
    }


def audit(path: Path) -> dict:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    report: dict = {"db_path": str(path)}
    report["by_interface_quality"] = [
        dict(row)
        for row in conn.execute(
            "SELECT interface_name, quality, COUNT(*) AS n FROM observations GROUP BY 1, 2 ORDER BY 1, 2"
        )
    ]
    report["sources"] = [
        dict(row) for row in conn.execute("SELECT source, platform, COUNT(*) AS n FROM observations GROUP BY 1, 2")
    ]
    span = conn.execute("SELECT MIN(sampled_at) AS a, MAX(sampled_at) AS b, COUNT(*) AS n FROM observations").fetchone()
    report["span_hours"] = None if span["a"] is None else (span["b"] - span["a"]) / 3600
    report["observations"] = span["n"]
    intervals = [row[0] for row in conn.execute(
        "SELECT interval_seconds FROM observations WHERE quality = 'ok' AND interval_seconds IS NOT NULL"
    )]
    report["interval_seconds"] = _quantiles(intervals)
    report["interval_outside_0.5_1.5"] = sum(1 for value in intervals if not 0.5 <= value <= 1.5)
    for field in ("rx_mbps", "tx_mbps"):
        values = [row[0] for row in conn.execute(
            f"SELECT {field} FROM observations WHERE quality = 'ok' AND {field} IS NOT NULL"
        )]
        report[field] = _quantiles(values)
    report["duplicate_timestamps"] = conn.execute(
        "SELECT COUNT(*) FROM (SELECT interface_name, sampled_at_ms FROM observations GROUP BY 1, 2 HAVING COUNT(*) > 1)"
    ).fetchone()[0]
    report["fixture_like_interfaces"] = [
        row[0]
        for row in conn.execute("SELECT DISTINCT interface_name FROM observations")
        if row[0].startswith(("eth-test", "missing", "test"))
    ]
    report["non_monotonic_rows"] = conn.execute(
        """
        SELECT COUNT(*) FROM (
            SELECT sampled_at, LAG(sampled_at) OVER (PARTITION BY interface_name ORDER BY id) AS prev
            FROM observations
        ) WHERE prev IS NOT NULL AND sampled_at < prev
        """
    ).fetchone()[0]
    report["forecasts_by_kind_status"] = [
        dict(row) for row in conn.execute("SELECT kind, status, COUNT(*) AS n FROM forecasts GROUP BY 1, 2")
    ]
    report["forecast_horizons"] = [
        dict(row) for row in conn.execute("SELECT kind, horizon_seconds, COUNT(*) AS n FROM forecasts GROUP BY 1, 2")
    ]
    report["settings"] = {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM settings")}
    report["probes"] = [dict(row) for row in conn.execute("SELECT status, COUNT(*) AS n FROM probes GROUP BY 1")]
    conn.close()
    return report


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else default_db_path()
    print(json.dumps(audit(target), indent=2, default=str))

"""SQLite storage for timestamped interface observations.

Rows are written only for readings the collector actually took. Gaps are
not backfilled. The database is local and bounded by a retention window.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

DEFAULT_CONFIG: dict = {
    "capacity_mbps": None,
    "capacity_source": "unknown",
    "direction": "per_direction",
    "warning_utilization_pct": None,
    "high_utilization_pct": None,
    "latency_congestion_ms": None,
    "loss_congestion_pct": None,
    "monitor_interface": None,
    "probe_target": None,
    "forecast_horizon_seconds": None,
    "download_threshold_mbps": None,
    "upload_threshold_mbps": None,
    "profiles": {},
    "interface_mode": "manual",
}


class Store:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=5, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def init(self) -> None:
        with self._lock, self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS observations (
                    id INTEGER PRIMARY KEY,
                    sampled_at REAL NOT NULL,
                    sampled_at_ms INTEGER NOT NULL,
                    interval_seconds REAL,
                    interface_name TEXT NOT NULL,
                    rx_bytes INTEGER,
                    tx_bytes INTEGER,
                    rx_packets INTEGER,
                    tx_packets INTEGER,
                    rx_errors INTEGER,
                    tx_errors INTEGER,
                    rx_drops INTEGER,
                    tx_drops INTEGER,
                    rx_mbps REAL,
                    tx_mbps REAL,
                    rx_pps REAL,
                    tx_pps REAL,
                    rx_error_per_s REAL,
                    tx_error_per_s REAL,
                    rx_drop_per_s REAL,
                    tx_drop_per_s REAL,
                    valid INTEGER NOT NULL,
                    quality TEXT NOT NULL,
                    source TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    UNIQUE(interface_name, sampled_at_ms)
                );
                CREATE INDEX IF NOT EXISTS idx_obs_iface_time
                    ON observations(interface_name, sampled_at);
                CREATE TABLE IF NOT EXISTS probes (
                    id INTEGER PRIMARY KEY,
                    sampled_at REAL NOT NULL,
                    target TEXT NOT NULL,
                    method TEXT NOT NULL,
                    status TEXT NOT NULL,
                    sent INTEGER,
                    received INTEGER,
                    loss_pct REAL,
                    rtt_avg_ms REAL,
                    rtt_min_ms REAL,
                    rtt_max_ms REAL,
                    jitter_ms REAL,
                    sample_count INTEGER,
                    rtt_status TEXT,
                    error TEXT,
                    note TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS forecasts (
                    id INTEGER PRIMARY KEY,
                    interface_name TEXT NOT NULL,
                    method TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    created_at_ms INTEGER NOT NULL,
                    target_at REAL NOT NULL,
                    horizon_seconds REAL NOT NULL,
                    predicted_mbps REAL NOT NULL,
                    observations_used INTEGER NOT NULL,
                    actual_mbps REAL,
                    actual_at REAL,
                    status TEXT NOT NULL,
                    UNIQUE(interface_name, method, direction, kind, created_at_ms)
                );
                CREATE INDEX IF NOT EXISTS idx_forecast_pending
                    ON forecasts(interface_name, status, target_at);
                CREATE INDEX IF NOT EXISTS idx_forecast_scored
                    ON forecasts(interface_name, direction, kind, status, method, created_at_ms);
                CREATE TABLE IF NOT EXISTS alert_events (
                    id INTEGER PRIMARY KEY,
                    interface_name TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    started_at REAL NOT NULL,
                    ended_at REAL,
                    end_reason TEXT,
                    threshold_mbps REAL,
                    trigger_mbps REAL,
                    peak_mbps REAL,
                    reopened INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_alert_events_iface
                    ON alert_events(interface_name, started_at);
                CREATE TABLE IF NOT EXISTS transitions (
                    id INTEGER PRIMARY KEY,
                    at REAL NOT NULL,
                    from_interface TEXT,
                    to_interface TEXT NOT NULL,
                    reason TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_transitions_at ON transitions(at);
                """
            )

    def get_config(self) -> dict:
        with self._lock, self.connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = 'config'").fetchone()
        config = dict(DEFAULT_CONFIG)
        if row is not None:
            try:
                stored = json.loads(row["value"])
            except json.JSONDecodeError:
                stored = {}
            if isinstance(stored, dict):
                config.update({key: stored.get(key, config[key]) for key in DEFAULT_CONFIG})
        return config

    def update_config(self, patch: dict) -> dict:
        config = self.get_config()
        for key, value in patch.items():
            if key in DEFAULT_CONFIG:
                config[key] = value
        payload = json.dumps(config)
        now = time.time()
        with self._lock, self.connect() as conn:
            conn.execute(
                """
                INSERT INTO settings(key, value, updated_at) VALUES('config', ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (payload, now),
            )
        return config

    def insert_observation(self, row: dict) -> bool:
        """Insert one reading. Duplicate interface/timestamp rows are ignored."""
        sampled_at = float(row["sampled_at"])
        sampled_at_ms = int(round(sampled_at * 1000))
        values = (
            sampled_at,
            sampled_at_ms,
            row.get("interval_seconds"),
            row["interface_name"],
            row.get("rx_bytes"),
            row.get("tx_bytes"),
            row.get("rx_packets"),
            row.get("tx_packets"),
            row.get("rx_errors"),
            row.get("tx_errors"),
            row.get("rx_drops"),
            row.get("tx_drops"),
            row.get("rx_mbps"),
            row.get("tx_mbps"),
            row.get("rx_pps"),
            row.get("tx_pps"),
            row.get("rx_error_per_s"),
            row.get("tx_error_per_s"),
            row.get("rx_drop_per_s"),
            row.get("tx_drop_per_s"),
            1 if row.get("valid") else 0,
            row.get("quality") or "unknown",
            row.get("source") or "psutil.net_io_counters",
            row.get("platform") or "",
            row.get("note") or "",
        )
        with self._lock, self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO observations (
                    sampled_at, sampled_at_ms, interval_seconds, interface_name,
                    rx_bytes, tx_bytes, rx_packets, tx_packets,
                    rx_errors, tx_errors, rx_drops, tx_drops,
                    rx_mbps, tx_mbps, rx_pps, tx_pps,
                    rx_error_per_s, tx_error_per_s, rx_drop_per_s, tx_drop_per_s,
                    valid, quality, source, platform, note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            inserted = cursor.rowcount > 0
        return inserted

    def prune(self, retention_seconds: float, now: float | None = None) -> int:
        cutoff = (now if now is not None else time.time()) - retention_seconds
        with self._lock, self.connect() as conn:
            obs = conn.execute("DELETE FROM observations WHERE sampled_at < ?", (cutoff,))
            probes = conn.execute("DELETE FROM probes WHERE sampled_at < ?", (cutoff,))
            forecasts = conn.execute("DELETE FROM forecasts WHERE created_at < ?", (cutoff,))
            alerts = conn.execute(
                "DELETE FROM alert_events WHERE started_at < ? AND end_reason IS NOT NULL", (cutoff,)
            )
            moves = conn.execute("DELETE FROM transitions WHERE at < ?", (cutoff,))
            return obs.rowcount + probes.rowcount + forecasts.rowcount + alerts.rowcount + moves.rowcount

    def latest(self, interface_name: str) -> dict | None:
        with self._lock, self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM observations
                WHERE interface_name = ?
                ORDER BY sampled_at DESC
                LIMIT 1
                """,
                (interface_name,),
            ).fetchone()
        return _observation_dict(row) if row else None

    def history(
        self,
        interface_name: str,
        *,
        start: float | None = None,
        end: float | None = None,
        limit: int = 1000,
        valid_only: bool = False,
    ) -> list[dict]:
        clauses = ["interface_name = ?"]
        params: list[object] = [interface_name]
        if start is not None:
            clauses.append("sampled_at >= ?")
            params.append(start)
        if end is not None:
            clauses.append("sampled_at <= ?")
            params.append(end)
        if valid_only:
            clauses.append("valid = 1 AND (rx_mbps IS NOT NULL OR tx_mbps IS NOT NULL)")
        params.append(int(limit))
        sql = f"""
            SELECT * FROM (
                SELECT * FROM observations
                WHERE {' AND '.join(clauses)}
                ORDER BY sampled_at DESC
                LIMIT ?
            ) ORDER BY sampled_at ASC
        """
        with self._lock, self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_observation_dict(row) for row in rows]

    def count_observations(self, interface_name: str | None = None) -> int:
        with self._lock, self.connect() as conn:
            if interface_name is None:
                row = conn.execute("SELECT COUNT(*) AS n FROM observations").fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM observations WHERE interface_name = ?",
                    (interface_name,),
                ).fetchone()
        return int(row["n"])

    def insert_probe(self, row: dict) -> None:
        with self._lock, self.connect() as conn:
            conn.execute(
                """
                INSERT INTO probes (
                    sampled_at, target, method, status, sent, received, loss_pct,
                    rtt_avg_ms, rtt_min_ms, rtt_max_ms, jitter_ms, sample_count,
                    rtt_status, error, note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.get("sampled_at", time.time()),
                    row.get("target") or "",
                    row.get("method") or "icmp_echo",
                    row.get("status") or "failed",
                    row.get("sent"),
                    row.get("received"),
                    row.get("loss_pct"),
                    row.get("rtt_avg_ms"),
                    row.get("rtt_min_ms"),
                    row.get("rtt_max_ms"),
                    row.get("jitter_ms"),
                    row.get("sample_count"),
                    row.get("rtt_status"),
                    row.get("error"),
                    row.get("note") or "",
                ),
            )

    def latest_probe(self) -> dict | None:
        with self._lock, self.connect() as conn:
            row = conn.execute("SELECT * FROM probes ORDER BY sampled_at DESC LIMIT 1").fetchone()
        if row is None:
            return None
        return {key: row[key] for key in row.keys()}

    def dataset_summary(self, interface_name: str) -> dict:
        with self._lock, self.connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN valid = 1 AND rx_mbps IS NOT NULL AND tx_mbps IS NOT NULL THEN 1 ELSE 0 END) AS valid_n,
                    MIN(sampled_at) AS first_at,
                    MAX(sampled_at) AS latest_at
                FROM observations
                WHERE interface_name = ?
                """,
                (interface_name,),
            ).fetchone()
        total = int(row["total"] or 0)
        valid_n = int(row["valid_n"] or 0)
        first_at = row["first_at"]
        latest_at = row["latest_at"]
        duration = None
        if first_at is not None and latest_at is not None:
            duration = float(latest_at) - float(first_at)
        return {
            "interface_name": interface_name,
            "observations": total,
            "valid_observations": valid_n,
            "first_at": first_at,
            "latest_at": latest_at,
            "duration_seconds": duration,
            "gaps_filled": False,
        }

    def insert_forecast(self, row: dict) -> bool:
        created_at = float(row["created_at"])
        with self._lock, self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO forecasts (
                    interface_name, method, direction, kind,
                    created_at, created_at_ms, target_at, horizon_seconds,
                    predicted_mbps, observations_used, actual_mbps, actual_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, 'pending')
                """,
                (
                    row["interface_name"],
                    row["method"],
                    row["direction"],
                    row["kind"],
                    created_at,
                    int(round(created_at * 1000)),
                    float(row["target_at"]),
                    float(row["horizon_seconds"]),
                    float(row["predicted_mbps"]),
                    int(row["observations_used"]),
                ),
            )
            return cursor.rowcount > 0

    def pending_forecasts(self, interface_name: str, now: float) -> list[dict]:
        with self._lock, self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM forecasts
                WHERE interface_name = ? AND status = 'pending' AND target_at <= ?
                ORDER BY target_at ASC
                """,
                (interface_name, now),
            ).fetchall()
        return [_row_dict(row) for row in rows]

    def nearest_valid_rate(self, interface_name: str, target_at: float, after: float, tolerance: float, field: str) -> dict | None:
        if field not in {"rx_mbps", "tx_mbps"}:
            raise ValueError("Unsupported rate field.")
        low = target_at - tolerance
        high = target_at + tolerance
        with self._lock, self.connect() as conn:
            row = conn.execute(
                f"""
                SELECT sampled_at, {field} AS mbps FROM observations
                WHERE interface_name = ?
                  AND valid = 1
                  AND {field} IS NOT NULL
                  AND sampled_at > ?
                  AND sampled_at BETWEEN ? AND ?
                ORDER BY ABS(sampled_at - ?) ASC
                LIMIT 1
                """,
                (interface_name, after, low, high, target_at),
            ).fetchone()
        if row is None:
            return None
        return {"sampled_at": row["sampled_at"], "mbps": row["mbps"]}

    def mark_forecast(self, forecast_id: int, *, status: str, actual_mbps: float | None, actual_at: float | None) -> None:
        with self._lock, self.connect() as conn:
            conn.execute(
                """
                UPDATE forecasts
                SET status = ?, actual_mbps = ?, actual_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (status, actual_mbps, actual_at, forecast_id),
            )

    def forecast_score_summary(self, interface_name: str) -> dict:
        """Aggregate saved-forecast scores in SQLite.

        A shared origin is one timestamp where persistence, the moving average,
        and exponential smoothing were all scored. The totals match a full-table
        scan without loading every forecast into Python.
        """
        methods = ("persistence", "moving_average", "exponential_smoothing")
        placeholders = ", ".join("?" for _ in methods)
        shared_sql = f"""
            SELECT created_at_ms FROM forecasts
            WHERE interface_name = ? AND direction = ? AND kind = ? AND status = 'scored'
              AND method IN ({placeholders})
            GROUP BY created_at_ms
            HAVING COUNT(DISTINCT method) = ?
        """
        metrics_sql = f"""
            WITH shared AS ({shared_sql})
            SELECT f.method AS method,
                   COUNT(*) AS n,
                   AVG(ABS(f.predicted_mbps - f.actual_mbps)) AS mae,
                   SQRT(AVG((f.predicted_mbps - f.actual_mbps) * (f.predicted_mbps - f.actual_mbps))) AS rmse,
                   AVG(f.predicted_mbps - f.actual_mbps) AS bias
            FROM forecasts f
            JOIN shared s ON s.created_at_ms = f.created_at_ms
            WHERE f.interface_name = ? AND f.direction = ? AND f.kind = ? AND f.status = 'scored'
              AND f.method IN ({placeholders})
            GROUP BY f.method
        """
        with self._lock, self.connect() as conn:
            count_rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM forecasts WHERE interface_name = ? GROUP BY status",
                (interface_name,),
            ).fetchall()
            counts = {row["status"]: int(row["n"]) for row in count_rows}
            blocks: dict[str, dict[str, dict]] = {}
            for direction in ("receive", "transmit"):
                blocks[direction] = {}
                for kind in ("one_step", "horizon"):
                    params = (
                        interface_name,
                        direction,
                        kind,
                        *methods,
                        len(methods),
                        interface_name,
                        direction,
                        kind,
                        *methods,
                    )
                    metric_rows = conn.execute(metrics_sql, params).fetchall()
                    by_method = {row["method"]: row for row in metric_rows}
                    n = int(metric_rows[0]["n"]) if metric_rows else 0
                    method_payload = {}
                    for name in methods:
                        item = by_method.get(name)
                        if item is None:
                            method_payload[name] = {"mae": None, "rmse": None, "bias": None, "n": 0}
                        else:
                            method_payload[name] = {
                                "mae": item["mae"],
                                "rmse": item["rmse"],
                                "bias": item["bias"],
                                "n": int(item["n"]),
                            }
                    blocks[direction][kind] = {"n": n, "methods": method_payload}
        return {"counts": counts, "blocks": blocks}

    def forecast_rows(self, interface_name: str) -> list[dict]:
        with self._lock, self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM forecasts
                WHERE interface_name = ?
                ORDER BY created_at ASC
                """,
                (interface_name,),
            ).fetchall()
        return [_row_dict(row) for row in rows]

    def insert_alert_event(
        self,
        *,
        interface_name: str,
        direction: str,
        kind: str,
        started_at: float,
        threshold_mbps: float | None,
        trigger_mbps: float | None,
    ) -> int:
        with self._lock, self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO alert_events(interface_name, direction, kind, started_at,
                    threshold_mbps, trigger_mbps, peak_mbps)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (interface_name, direction, kind, started_at, threshold_mbps, trigger_mbps, trigger_mbps),
            )
            return int(cursor.lastrowid)

    def update_alert_event(
        self,
        event_id: int,
        *,
        peak_mbps: float | None = None,
        ended_at: float | None = None,
        end_reason: str | None = None,
        reopened: bool = False,
    ) -> None:
        with self._lock, self.connect() as conn:
            if reopened:
                conn.execute(
                    "UPDATE alert_events SET ended_at = NULL, end_reason = NULL, reopened = reopened + 1 WHERE id = ?",
                    (event_id,),
                )
            if peak_mbps is not None:
                conn.execute(
                    "UPDATE alert_events SET peak_mbps = MAX(COALESCE(peak_mbps, 0), ?) WHERE id = ?",
                    (peak_mbps, event_id),
                )
            if end_reason is not None:
                conn.execute(
                    "UPDATE alert_events SET ended_at = ?, end_reason = ? WHERE id = ?",
                    (ended_at, end_reason, event_id),
                )

    def close_open_alert_events(self, reason: str, interface_name: str | None = None) -> int:
        """Close episodes left open. ended_at stays NULL because no recovery was observed."""
        sql = "UPDATE alert_events SET end_reason = ? WHERE end_reason IS NULL"
        params: list = [reason]
        if interface_name is not None:
            sql += " AND interface_name = ?"
            params.append(interface_name)
        with self._lock, self.connect() as conn:
            return int(conn.execute(sql, params).rowcount)

    def alert_events(self, interface_name: str, *, start: float | None = None, limit: int = 50) -> list[dict]:
        sql = "SELECT * FROM alert_events WHERE interface_name = ?"
        params: list = [interface_name]
        if start is not None:
            sql += " AND (ended_at IS NULL OR ended_at >= ? OR started_at >= ?)"
            params.extend([start, start])
        sql += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)
        with self._lock, self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_dict(row) for row in rows]

    def alert_history_summary(self, interface_name: str) -> dict:
        """Last start, last observed recovery, and episode count per direction."""
        summary: dict = {}
        with self._lock, self.connect() as conn:
            for direction in ("receive", "transmit"):
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS episodes, MAX(started_at) AS last_alert_at, MAX(ended_at) AS last_recovery_at
                    FROM alert_events
                    WHERE interface_name = ? AND direction = ? AND kind = 'threshold_exceeded'
                    """,
                    (interface_name, direction),
                ).fetchone()
                summary[direction] = {
                    "episodes": int(row["episodes"] or 0),
                    "last_alert_at": row["last_alert_at"],
                    "last_recovery_at": row["last_recovery_at"],
                }
        return summary

    def insert_transition(self, *, at: float, from_interface: str | None, to_interface: str, reason: str) -> None:
        with self._lock, self.connect() as conn:
            conn.execute(
                "INSERT INTO transitions(at, from_interface, to_interface, reason) VALUES(?, ?, ?, ?)",
                (at, from_interface, to_interface, reason),
            )

    def transitions(self, *, start: float | None = None, limit: int = 50) -> list[dict]:
        sql = "SELECT * FROM transitions"
        params: list = []
        if start is not None:
            sql += " WHERE at >= ?"
            params.append(start)
        sql += " ORDER BY at DESC LIMIT ?"
        params.append(limit)
        with self._lock, self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_dict(row) for row in rows]

    def interface_coverage(self) -> list[dict]:
        """Per-interface row counts so profiles never borrow each other's history."""
        with self._lock, self.connect() as conn:
            rows = conn.execute(
                """
                SELECT interface_name, COUNT(*) AS observations, SUM(valid) AS valid_observations,
                    MIN(sampled_at) AS first_at, MAX(sampled_at) AS latest_at
                FROM observations GROUP BY interface_name ORDER BY latest_at DESC
                """
            ).fetchall()
        return [_row_dict(row) for row in rows]


def _observation_dict(row: sqlite3.Row) -> dict:
    data = {key: row[key] for key in row.keys()}
    data["valid"] = bool(data["valid"])
    return data


def _row_dict(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in row.keys()}

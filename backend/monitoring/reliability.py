"""Measurements of sampling, storage, and invalid-counter handling.

Figures in this module are taken when the report is built. The SQLite write
probe and the retention check use a temporary database so they do not change
the collector's history. They are not a test of a saturated network link.
"""

from __future__ import annotations

import gc
import shutil
import statistics
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import psutil

from core.config import settings
from monitoring.rates import Counters, compute_rate
from monitoring.store import Store


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return ordered[index]


def sampling_report(rows: list[dict]) -> dict:
    intervals = [float(row["interval_seconds"]) for row in rows if row.get("interval_seconds") is not None]
    qualities: dict[str, int] = {}
    valid_zeros = 0
    for row in rows:
        quality = str(row.get("quality") or "unknown")
        qualities[quality] = qualities.get(quality, 0) + 1
        if quality == "ok" and row.get("rx_mbps") == 0 and row.get("tx_mbps") == 0:
            valid_zeros += 1
    invalid = sum(count for name, count in qualities.items() if name != "ok")
    return {
        "observations": len(rows),
        "interval_p50_seconds": _percentile(intervals, 0.50),
        "interval_p95_seconds": _percentile(intervals, 0.95),
        "interval_max_seconds": max(intervals) if intervals else None,
        "qualities": qualities,
        "invalid_intervals": invalid,
        "valid_zero_rates": valid_zeros,
        "note": (
            "Intervals are the monotonic elapsed times stored with each reading. "
            "Invalid qualities have null rates. A valid zero is a real counter delta of zero."
        ),
    }


def controlled_counter_cases() -> list[dict]:
    """Known counter sequences. No packets are generated."""
    base = Counters(0.0, 1_000.0, 1_000_000, 500_000, 10, 10, 0, 0, 0, 0)
    cases = [
        ("one_second", Counters(1.0, 1_001.0, 1_125_000, 500_000, 20, 10, 0, 0, 0, 0), False, 15.0),
        ("short_elapsed", Counters(0.01, 1_000.01, 1_200_000, 500_000, 30, 10, 0, 0, 0, 0), False, 15.0),
        ("long_gap", Counters(20.0, 1_020.0, 2_000_000, 500_000, 40, 10, 0, 0, 0, 0), False, 15.0),
        ("counter_reset", Counters(1.0, 1_001.0, 10, 500_000, 50, 10, 0, 0, 0, 0), False, 15.0),
        ("interface_change", Counters(1.0, 1_001.0, 9_000_000, 500_000, 60, 10, 0, 0, 0, 0), True, 15.0),
        ("missing_counter", Counters(1.0, 1_001.0, None, None, None, None, None, None, None, None), False, 15.0),
    ]
    results = []
    for name, current, changed, limit in cases:
        sample = compute_rate(base, current, interface_changed=changed, max_elapsed_seconds=limit)
        results.append(
            {
                "case": name,
                "quality": sample.quality,
                "valid": sample.valid,
                "elapsed_seconds": sample.elapsed_seconds,
                "rx_mbps": sample.rx_mbps,
                "tx_mbps": sample.tx_mbps,
            }
        )
    idle = compute_rate(base, Counters(1.0, 1_001.0, 1_000_000, 500_000, 10, 10, 0, 0, 0, 0), max_elapsed_seconds=15.0)
    results.append(
        {
            "case": "unchanged_counters",
            "quality": idle.quality,
            "valid": idle.valid,
            "elapsed_seconds": idle.elapsed_seconds,
            "rx_mbps": idle.rx_mbps,
            "tx_mbps": idle.tx_mbps,
        }
    )
    return results


def _temporary_store(name: str):
    directory = Path(tempfile.mkdtemp())
    store = Store(directory / name)
    store.init()
    return directory, store


def _remove_temporary(directory: Path, store: Store) -> None:
    del store
    gc.collect()
    shutil.rmtree(directory, ignore_errors=True)


def sqlite_write_probe(count: int = 200) -> dict:
    started = time.perf_counter()
    directory, store = _temporary_store("probe.sqlite")
    durations = []
    try:
        for index in range(count):
            before = time.perf_counter()
            store.insert_observation(
                {
                    "sampled_at": 1_000.0 + index,
                    "interval_seconds": 1.0,
                    "interface_name": "probe",
                    "rx_bytes": index,
                    "tx_bytes": index,
                    "rx_packets": None,
                    "tx_packets": None,
                    "rx_errors": None,
                    "tx_errors": None,
                    "rx_drops": None,
                    "tx_drops": None,
                    "rx_mbps": 0.1,
                    "tx_mbps": 0.1,
                    "rx_pps": None,
                    "tx_pps": None,
                    "rx_error_per_s": None,
                    "tx_error_per_s": None,
                    "rx_drop_per_s": None,
                    "tx_drop_per_s": None,
                    "valid": True,
                    "quality": "ok",
                    "source": "reliability_probe",
                    "platform": "test",
                    "note": "",
                }
            )
            durations.append((time.perf_counter() - before) * 1000)
        retained = store.count_observations("probe")
    finally:
        _remove_temporary(directory, store)
    elapsed = time.perf_counter() - started
    return {
        "rows": count,
        "rows_written": retained,
        "median_write_ms": statistics.median(durations),
        "p95_write_ms": _percentile(durations, 0.95),
        "rows_per_second": count / elapsed if elapsed else None,
        "database": "temporary",
    }


def retention_probe(retention_seconds: float = 24 * 3600) -> dict:
    now = 10_000_000.0
    directory, store = _temporary_store("retention.sqlite")
    try:
        for index, age in enumerate((retention_seconds + 10, retention_seconds - 10)):
            store.insert_observation(
                {
                    "sampled_at": now - age,
                    "interval_seconds": 1.0,
                    "interface_name": "probe",
                    "rx_bytes": index,
                    "tx_bytes": index,
                    "rx_packets": None,
                    "tx_packets": None,
                    "rx_errors": None,
                    "tx_errors": None,
                    "rx_drops": None,
                    "tx_drops": None,
                    "rx_mbps": 0.2,
                    "tx_mbps": 0.2,
                    "rx_pps": None,
                    "tx_pps": None,
                    "rx_error_per_s": None,
                    "tx_error_per_s": None,
                    "rx_drop_per_s": None,
                    "tx_drop_per_s": None,
                    "valid": True,
                    "quality": "ok",
                    "source": "reliability_probe",
                    "platform": "test",
                    "note": "",
                }
            )
        deleted = store.prune(retention_seconds, now=now)
        remaining = store.count_observations("probe")
    finally:
        _remove_temporary(directory, store)
    return {
        "retention_seconds": retention_seconds,
        "deleted_rows": deleted,
        "rows_kept": remaining,
        "expired_row_removed": deleted >= 1 and remaining == 1,
    }


def _one_row(index: int) -> dict:
    return {
        "sampled_at": 2_000.0 + index,
        "interval_seconds": 1.0,
        "interface_name": "probe",
        "rx_bytes": index,
        "tx_bytes": index,
        "rx_packets": None,
        "tx_packets": None,
        "rx_errors": None,
        "tx_errors": None,
        "rx_drops": None,
        "tx_drops": None,
        "rx_mbps": 0.1,
        "tx_mbps": 0.1,
        "rx_pps": None,
        "tx_pps": None,
        "rx_error_per_s": None,
        "tx_error_per_s": None,
        "rx_drop_per_s": None,
        "tx_drop_per_s": None,
        "valid": True,
        "quality": "ok",
        "source": "reliability_probe",
        "platform": "test",
        "note": "",
    }


def write_load(levels: tuple[tuple[str, int], ...] = (("low", 50), ("medium", 200), ("high", 800))) -> list[dict]:
    """Time real SQLite inserts. This does not generate network traffic."""
    process = psutil.Process()
    results = []
    for name, count in levels:
        directory, store = _temporary_store(f"{name}.sqlite")
        try:
            process.cpu_percent(interval=None)
            rss_before = process.memory_info().rss
            started = time.perf_counter()
            for index in range(count):
                store.insert_observation(_one_row(index))
            elapsed = time.perf_counter() - started
            cpu = process.cpu_percent(interval=None)
            rss_after = process.memory_info().rss
            written = store.count_observations("probe")
        finally:
            _remove_temporary(directory, store)
        results.append(
            {
                "level": name,
                "rows": count,
                "rows_written": written,
                "elapsed_seconds": elapsed,
                "rows_per_second": count / elapsed if elapsed else None,
                "cpu_percent": cpu,
                "rss_before_bytes": rss_before,
                "rss_after_bytes": rss_after,
                "kind": "sqlite_inserts_in_this_process",
            }
        )
    return results


def api_latency(url: str = "http://127.0.0.1:8000/api/monitoring/health", samples: int = 5) -> dict:
    """Time a live health request. A stopped backend is reported, not filled in."""
    timings = []
    error = None
    for _ in range(samples):
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                response.read()
            timings.append((time.perf_counter() - started) * 1000)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            error = str(exc)
            break
    if not timings:
        return {"status": "not_measured", "url": url, "error": error, "samples": 0}
    return {
        "status": "measured",
        "url": url,
        "samples": len(timings),
        "median_ms": statistics.median(timings),
        "max_ms": max(timings),
        "error": None,
    }


def process_sample() -> dict:
    process = psutil.Process()
    cpu = process.cpu_percent(interval=0.1)
    memory = process.memory_info()
    return {
        "cpu_percent": cpu,
        "rss_bytes": memory.rss,
        "interval_seconds": 0.1,
        "note": "CPU percent is this process over a 0.1 s sample. It is not a system-wide load test.",
    }


def build_reliability_report(store: Store, interface_name: str | None) -> dict:
    rows = store.history(interface_name, limit=5000) if interface_name else []
    return {
        "measured_at": time.time(),
        "interface": interface_name,
        "sampling": sampling_report(rows),
        "controlled_counters": controlled_counter_cases(),
        "sqlite_write": sqlite_write_probe(),
        "write_load": write_load(),
        "api_latency": api_latency(),
        "retention": retention_probe(max(60.0, settings.retention_hours * 3600)),
        "process": process_sample(),
        "limitations": (
            "This report does not generate network traffic and does not claim a result for a saturated link. "
            "Sampling numbers come from stored observations. Write, retention, and CPU numbers were measured "
            "in this process when the report was requested."
        ),
    }

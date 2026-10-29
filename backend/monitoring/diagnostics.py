"""Model and alert diagnostics computed from stored observations only."""

from __future__ import annotations

import threading
import time

from analytics.rise_alert import (
    CANDIDATE,
    evaluate_advance_warning,
    merge_advance_reports,
    warning_beats_baselines,
)
from analytics.controlled_forecasts import controlled_forecast_report
from analytics.walk_forward import evaluate_history, split_runs
from monitoring.collector import Collector
from monitoring.forecast_log import summarize_forecasts

_CACHE: dict = {"key": None, "at": 0.0, "value": None}
_CACHE_LOCK = threading.Lock()
CACHE_SECONDS = 60.0
ADVANCE_HORIZON_SECONDS = 300.0
MIN_RUN_FOR_ADVANCE = 20


def _advance(runs: list[list[dict]], field: str, threshold: float | None, sample_interval: float) -> dict | None:
    if threshold is None:
        return None
    horizon = max(1, int(round(ADVANCE_HORIZON_SECONDS / sample_interval)))
    reports = [
        evaluate_advance_warning([float(row[field]) for row in run], threshold, horizon=horizon)
        for run in runs
        if len(run) >= MIN_RUN_FOR_ADVANCE
    ]
    merged = merge_advance_reports(reports)
    merged["threshold_mbps"] = threshold
    merged["horizon_seconds"] = ADVANCE_HORIZON_SECONDS
    merged["gate_enabled"] = warning_beats_baselines(merged)
    merged["candidate"] = CANDIDATE
    lead = merged["methods"][CANDIDATE].get("mean_lead_steps")
    merged["candidate_mean_lead_seconds"] = None if lead is None else lead * sample_interval
    del merged["counts"]
    return merged


def build_diagnostics(collector: Collector, *, force: bool = False) -> dict:
    name = collector.selected_name()
    if not name:
        return {"interface": None, "status": "no_interface"}
    dataset = collector.store.dataset_summary(name)
    thresholds = collector.thresholds(name)
    key = (str(collector.store.path), name, dataset.get("observations"), thresholds["receive"], thresholds["transmit"])
    with _CACHE_LOCK:
        if not force and _CACHE["value"] is not None and _CACHE["key"][:2] == key[:2]:
            if time.monotonic() - _CACHE["at"] < CACHE_SECONDS and _CACHE["key"][3:] == key[3:]:
                return _CACHE["value"]
    rows = collector.store.history(name, limit=500_000)
    interval = collector.interval
    runs = split_runs(rows, interval)
    started = time.perf_counter()
    walk = evaluate_history(rows, sample_interval=interval)
    duration = dataset.get("duration_seconds") or 0
    valid = int(dataset.get("valid_observations") or 0)
    gaps = [
        float(row["interval_seconds"])
        for row in rows
        if row.get("interval_seconds") is not None and row.get("quality") == "ok"
    ]
    gaps.sort()
    result = {
        "interface": name,
        "status": "ok",
        "computed_at": time.time(),
        "compute_seconds": None,
        "data_quality": {
            "observations": dataset.get("observations"),
            "valid_observations": valid,
            "duration_seconds": duration,
            "valid_time_coverage": (valid * interval / duration) if duration else None,
            "interval_p50_seconds": gaps[len(gaps) // 2] if gaps else None,
            "interval_p95_seconds": gaps[int(len(gaps) * 0.95)] if gaps else None,
            "irregular_intervals": sum(1 for gap in gaps if not 0.5 * interval <= gap <= 1.5 * interval),
            "contiguous_runs": len(runs),
            "longest_run": max((len(run) for run in runs), default=0),
        },
        "walk_forward": walk,
        "controlled_forecasts": controlled_forecast_report(),
        "advance_warning": {
            "receive": _advance(runs, "rx_mbps", thresholds["receive"], interval),
            "transmit": _advance(runs, "tx_mbps", thresholds["transmit"], interval),
            "note": (
                "Scored on stored runs at the saved threshold with a five-minute horizon. "
                "An event is a crossing from below the threshold. Precision, false-positive rate, "
                "and missed-event rate come from walk-forward origins. Lead time is the mean "
                "earliest warning before a caught crossing."
            ),
        },
        "ledger": summarize_forecasts(collector.store, name),
        "thresholds": thresholds,
        "alert_history": collector.store.alert_history_summary(name),
        "scope": "These results describe stored readings from this computer's interface only.",
    }
    result["compute_seconds"] = time.perf_counter() - started
    with _CACHE_LOCK:
        _CACHE.update({"key": key, "at": time.monotonic(), "value": result})
    return result

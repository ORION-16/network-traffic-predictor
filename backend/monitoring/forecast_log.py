"""Persist forecasts when they are made, then score them on a later observation.

Rows are written only for an origin the collector has just stored. History is
not backfilled with forecasts that were never issued. A missing later sample
stays unscored or missed. It is not stored as zero traffic.
"""

from __future__ import annotations

import time

from analytics.forecasting import (
    Point,
    contiguous_run,
    exponential_smoothing_forecast,
    moving_average_forecast,
    persistence_forecast,
)
from monitoring.store import Store

METHODS = ("persistence", "moving_average", "exponential_smoothing")
MIN_SCORED = 5


def update_forecast_log(
    store: Store,
    interface_name: str,
    *,
    sample_interval: float,
    horizon_seconds: float,
    window: int = 12,
    alpha: float = 0.3,
    now: float | None = None,
) -> None:
    rows = store.history(interface_name, limit=20000, valid_only=True)
    issue_from_rows(
        store,
        interface_name,
        rows,
        sample_interval=sample_interval,
        horizon_seconds=horizon_seconds,
        window=window,
        alpha=alpha,
    )
    score_pending(
        store,
        interface_name,
        tolerance=max(sample_interval * 0.75, 0.5),
        now=now if now is not None else time.time(),
    )


def issue_from_rows(
    store: Store,
    interface_name: str,
    rows: list[dict],
    *,
    sample_interval: float,
    horizon_seconds: float,
    window: int,
    alpha: float,
) -> int:
    """Issue forecasts from the latest contiguous origin only. Returns rows inserted."""
    inserted = 0
    for direction, field in (("receive", "rx_mbps"), ("transmit", "tx_mbps")):
        points = _points(rows, field)
        run, _excluded = contiguous_run(points, sample_interval)
        if len(run) < 2:
            continue
        origin = run[-1].timestamp
        values = [point.value for point in run]
        predictions = {
            "persistence": persistence_forecast(values),
            "moving_average": moving_average_forecast(values, window),
            "exponential_smoothing": exponential_smoothing_forecast(values, alpha),
        }
        horizons = [("one_step", sample_interval)]
        if horizon_seconds > sample_interval * 1.5:
            horizons.append(("horizon", horizon_seconds))
        for method, predicted in predictions.items():
            if predicted is None:
                continue
            for kind, horizon in horizons:
                saved = store.insert_forecast(
                    {
                        "interface_name": interface_name,
                        "method": method,
                        "direction": direction,
                        "kind": kind,
                        "created_at": origin,
                        "target_at": origin + horizon,
                        "horizon_seconds": horizon,
                        "predicted_mbps": predicted,
                        "observations_used": len(run),
                    }
                )
                inserted += int(saved)
    return inserted


def score_pending(store: Store, interface_name: str, *, tolerance: float, now: float) -> None:
    for row in store.pending_forecasts(interface_name, now):
        field = "rx_mbps" if row["direction"] == "receive" else "tx_mbps"
        match = store.nearest_valid_rate(
            interface_name,
            float(row["target_at"]),
            float(row["created_at"]),
            tolerance,
            field,
        )
        if match is not None:
            store.mark_forecast(
                row["id"],
                status="scored",
                actual_mbps=float(match["mbps"]),
                actual_at=float(match["sampled_at"]),
            )
        elif now > float(row["target_at"]) + tolerance:
            store.mark_forecast(row["id"], status="missed", actual_mbps=None, actual_at=None)


def rows_for_forecast(rows: list[dict], sample_interval: float) -> list[dict]:
    """Keep the latest contiguous valid run. Older runs are not interpolated."""
    points = [
        Point(float(row["sampled_at"]), 0.0, row.get("interval_seconds"))
        for row in rows
        if row.get("quality") == "ok" and row.get("sampled_at") is not None
    ]
    run, _excluded = contiguous_run(points, sample_interval)
    if not run:
        return []
    start = run[0].timestamp
    return [
        row
        for row in rows
        if row.get("quality") == "ok" and row.get("sampled_at") is not None and float(row["sampled_at"]) >= start
    ]


def summarize_forecasts(store: Store, interface_name: str | None) -> dict:
    if not interface_name:
        return _empty("Collecting data. No interface is selected.")
    summary = store.forecast_score_summary(interface_name)
    counts = summary["counts"]
    scored = counts.get("scored", 0)
    missed = counts.get("missed", 0)
    pending = counts.get("pending", 0)
    recorded = scored + missed + pending
    report = {
        "status": "collecting" if recorded == 0 else "insufficient_history",
        "recorded": recorded,
        "scored": scored,
        "missed": missed,
        "pending": pending,
        "minimum_scored": MIN_SCORED,
        "receive": {"one_step": _empty_block(), "horizon": _empty_block()},
        "transmit": {"one_step": _empty_block(), "horizon": _empty_block()},
        "note": "Collecting data. Forecasts are saved as readings arrive and scored only against a later measurement.",
    }
    any_evaluated = False
    for direction in ("receive", "transmit"):
        for kind in ("one_step", "horizon"):
            block = summary["blocks"][direction][kind]
            n = int(block["n"])
            report[direction][kind] = {
                "status": "evaluated" if n >= MIN_SCORED else "insufficient_history",
                "n": n,
                "methods": block["methods"],
            }
            if report[direction][kind]["status"] == "evaluated":
                any_evaluated = True
    if any_evaluated:
        report["status"] = "evaluated"
        report["note"] = (
            "MAE and RMSE use saved forecasts compared with a later observation. "
            "Methods share the same origins. Missed samples are excluded, not treated as zero."
        )
    elif recorded:
        report["note"] = (
            f"Insufficient history. {recorded} forecasts are saved and {scored} have a later measurement. "
            f"A method comparison needs {MIN_SCORED} shared scored origins."
        )
    return report


def _points(rows: list[dict], field: str) -> list[Point]:
    points = []
    for row in rows:
        if row.get("quality") != "ok":
            continue
        value = row.get(field)
        if value is None:
            continue
        points.append(
            Point(
                timestamp=float(row["sampled_at"]),
                value=float(value),
                interval_seconds=row.get("interval_seconds"),
            )
        )
    return points


def _compare(rows: list[dict], direction: str, kind: str) -> dict:
    chosen = [row for row in rows if row["direction"] == direction and row["kind"] == kind and row["status"] == "scored"]
    by_origin: dict[int, dict[str, dict]] = {}
    for row in chosen:
        by_origin.setdefault(int(row["created_at_ms"]), {})[row["method"]] = row
    shared = [origin for origin, methods in by_origin.items() if all(name in methods for name in METHODS)]
    shared.sort()
    methods = {}
    for name in METHODS:
        pairs = [(by_origin[origin][name]["predicted_mbps"], by_origin[origin][name]["actual_mbps"]) for origin in shared]
        methods[name] = _metrics(pairs)
    status = "evaluated" if len(shared) >= MIN_SCORED else "insufficient_history"
    return {"status": status, "n": len(shared), "methods": methods}


def _metrics(pairs: list[tuple[float, float]]) -> dict:
    if not pairs:
        return {"mae": None, "rmse": None, "bias": None, "n": 0}
    errors = [predicted - actual for predicted, actual in pairs]
    count = len(pairs)
    mae = sum(abs(error) for error in errors) / count
    rmse = (sum(error * error for error in errors) / count) ** 0.5
    bias = sum(errors) / count
    return {"mae": mae, "rmse": rmse, "bias": bias, "n": count}


def _empty(note: str) -> dict:
    return {
        "status": "collecting",
        "recorded": 0,
        "scored": 0,
        "missed": 0,
        "pending": 0,
        "minimum_scored": MIN_SCORED,
        "receive": {"one_step": _empty_block(), "horizon": _empty_block()},
        "transmit": {"one_step": _empty_block(), "horizon": _empty_block()},
        "note": note,
    }


def _empty_block() -> dict:
    return {"status": "insufficient_history", "n": 0, "methods": {}}

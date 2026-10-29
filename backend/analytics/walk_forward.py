"""Walk-forward evaluation of simple forecasts on stored observations.

Every forecast uses observations at or before its origin. The target is the
stored sample nearest to ``origin + horizon`` inside the same contiguous run,
accepted only within a time tolerance. An origin without such a sample is
counted as unavailable. It is never scored against zero.

Runs break at gaps, baselines, resets, interface changes, and irregular
intervals, so a forecast never spans a collection outage.

Methods:

* persistence: the latest value.
* moving_average: mean of the last 12 values.
* exponential_smoothing: simple exponential smoothing, alpha 0.3.
* holt: Holt linear trend, alpha 0.3, beta 0.1, floored at 0 Mbps.

A burst target is an actual value at least 5 Mbps and at least three times the
median of the 60 values before the origin. Everything else is quiet.
"""

from __future__ import annotations

import bisect
import math
import statistics
from collections import deque

METHODS = ("persistence", "moving_average", "exponential_smoothing", "holt")
BASELINES = ("persistence", "moving_average", "exponential_smoothing")
DEFAULT_HORIZONS = (60.0, 300.0, 900.0)
MA_WINDOW = 12
SES_ALPHA = 0.3
HOLT_ALPHA = 0.3
HOLT_BETA = 0.1
MIN_HISTORY = 12
BURST_FLOOR_MBPS = 5.0
BURST_RATIO = 3.0
BURST_MEDIAN_WINDOW = 60


def max_join_seconds(sample_interval: float) -> float:
    """Same gap limit the collector uses before it stores a rate as missing."""
    return max(5 * sample_interval, 15.0)


def split_runs(rows: list[dict], sample_interval: float) -> list[list[dict]]:
    """Contiguous runs of valid rates.

    A delayed sample is kept when the collector stored it as ok. The run breaks
    at a baseline, reset, gap, or any spacing longer than the collector's gap
    limit. Nothing is interpolated.
    """
    limit = max_join_seconds(sample_interval)
    floor = 0.05
    runs: list[list[dict]] = []
    current: list[dict] = []
    previous_at: float | None = None
    for row in sorted(rows, key=lambda item: float(item["sampled_at"])):
        at = float(row["sampled_at"])
        ok = row.get("quality") == "ok" and row.get("rx_mbps") is not None and row.get("tx_mbps") is not None
        interval = row.get("interval_seconds")
        spaced = interval is not None and floor <= float(interval) <= limit
        joined = previous_at is None or floor <= at - previous_at <= limit
        if ok and spaced and joined:
            current.append(row)
        else:
            if len(current) > 1:
                runs.append(current)
            current = [row] if ok and spaced and (previous_at is None or at - previous_at >= floor) else []
        previous_at = at
    if len(current) > 1:
        runs.append(current)
    return runs


MAPE_FLOOR_MBPS = 0.05


def _metrics(pairs: list[tuple[float, float]]) -> dict:
    """pairs are (predicted, actual). MAPE is omitted when any actual is near zero."""
    if not pairs:
        return {"n": 0, "mae": None, "rmse": None, "bias": None, "mape": None, "mape_status": "pending"}
    residuals = [predicted - actual for predicted, actual in pairs]
    n = len(residuals)
    mape_ok = all(abs(actual) >= MAPE_FLOOR_MBPS for _, actual in pairs)
    mape = None
    if mape_ok:
        mape = sum(abs(predicted - actual) / abs(actual) for predicted, actual in pairs) / n * 100
    return {
        "n": n,
        "mae": sum(abs(item) for item in residuals) / n,
        "rmse": math.sqrt(sum(item * item for item in residuals) / n),
        "bias": sum(residuals) / n,
        "mape": mape,
        "mape_status": "reported" if mape_ok else "not_reported_near_zero_actuals",
    }


def _forecasts_for_run(values: list[float], steps: float) -> dict[str, list[float | None]]:
    """Forecast at every origin, using values up to and including that origin."""
    out: dict[str, list[float | None]] = {name: [] for name in METHODS}
    window: deque[float] = deque(maxlen=MA_WINDOW)
    level_ses: float | None = None
    level: float | None = None
    trend = 0.0
    for index, value in enumerate(values):
        window.append(value)
        level_ses = value if level_ses is None else SES_ALPHA * value + (1 - SES_ALPHA) * level_ses
        if level is None:
            level = value
        else:
            previous_level = level
            level = HOLT_ALPHA * value + (1 - HOLT_ALPHA) * (level + trend)
            trend = HOLT_BETA * (level - previous_level) + (1 - HOLT_BETA) * trend
        ready = index + 1 >= MIN_HISTORY
        out["persistence"].append(value if ready else None)
        out["moving_average"].append(sum(window) / len(window) if ready else None)
        out["exponential_smoothing"].append(level_ses if ready else None)
        out["holt"].append(max(0.0, level + trend * steps) if ready else None)
    return out


def evaluate_runs(
    runs: list[list[dict]],
    field: str,
    *,
    horizon_seconds: float,
    sample_interval: float,
) -> dict:
    tolerance = max(0.75 * sample_interval, 0.5)
    steps = horizon_seconds / sample_interval
    errors: dict[str, dict[str, list[tuple[float, float]]]] = {
        split: {name: [] for name in METHODS} for split in ("all", "quiet", "burst")
    }
    origins = 0
    unavailable = 0
    for run in runs:
        times = [float(row["sampled_at"]) for row in run]
        values = [float(row[field]) for row in run]
        forecasts = _forecasts_for_run(values, steps)
        for origin in range(MIN_HISTORY - 1, len(run)):
            target_time = times[origin] + horizon_seconds
            if target_time > times[-1] + tolerance:
                break
            origins += 1
            position = bisect.bisect_left(times, target_time - tolerance, lo=origin + 1)
            if position >= len(times) or abs(times[position] - target_time) > tolerance:
                unavailable += 1
                continue
            if position + 1 < len(times) and abs(times[position + 1] - target_time) < abs(times[position] - target_time):
                position += 1
            actual = values[position]
            recent = values[max(0, origin - BURST_MEDIAN_WINDOW + 1) : origin + 1]
            median = statistics.median(recent)
            split = "burst" if actual >= BURST_FLOOR_MBPS and actual >= BURST_RATIO * median else "quiet"
            for name in METHODS:
                predicted = forecasts[name][origin]
                if predicted is None:
                    continue
                pair = (predicted, actual)
                errors["all"][name].append(pair)
                errors[split][name].append(pair)
    result = {
        "horizon_seconds": horizon_seconds,
        "origins": origins,
        "unavailable_targets": unavailable,
        "target_coverage": (origins - unavailable) / origins if origins else None,
        "methods": {name: _metrics(errors["all"][name]) for name in METHODS},
        "quiet": {name: _metrics(errors["quiet"][name]) for name in METHODS},
        "burst": {name: _metrics(errors["burst"][name]) for name in METHODS},
    }
    span = max((float(run[-1]["sampled_at"]) - float(run[0]["sampled_at"]) for run in runs if len(run) > 1), default=0.0)
    result["longest_run_seconds"] = span
    scored_n = result["methods"]["persistence"]["n"]
    if scored_n:
        result["score_status"] = "evaluated"
        result["reason"] = None
    elif span < horizon_seconds:
        result["score_status"] = "insufficient_history"
        result["reason"] = (
            f"No {horizon_seconds:.0f}s score. The longest valid run is {span:.0f}s, "
            "which is shorter than this horizon. The missing score is left blank."
        )
    else:
        result["score_status"] = "insufficient_history"
        result["reason"] = (
            "A later sample did not fall close enough to the target time. "
            "That target was not scored as zero."
        )
    result["best_by_mae"] = _best(result["methods"])
    result["best_baseline"] = _best(result["methods"], BASELINES)
    result["quiet_best_baseline"] = _best(result["quiet"], BASELINES)
    result["burst_best_baseline"] = _best(result["burst"], BASELINES)
    result["holt_justified"] = holt_justified(result["methods"])
    result["mape_rule"] = f"MAPE is omitted when any actual in that split is below {MAPE_FLOOR_MBPS} Mbps."
    return result


def _best(methods: dict, names: tuple[str, ...] | None = None) -> str | None:
    chosen = names or tuple(methods)
    scored = [
        (methods[name]["mae"], name)
        for name in chosen
        if methods.get(name, {}).get("mae") is not None and methods[name].get("n")
    ]
    return min(scored)[1] if scored else None


def holt_justified(methods: dict) -> bool:
    """Holt is kept only if it beats every baseline on both MAE and RMSE."""
    holt = methods.get("holt") or {}
    if not holt.get("n") or holt.get("mae") is None:
        return False
    for name in BASELINES:
        base = methods.get(name) or {}
        if base.get("mae") is None:
            continue
        if holt["mae"] >= base["mae"] or holt["rmse"] >= base["rmse"]:
            return False
    return True


def evaluate_history(
    rows: list[dict],
    *,
    sample_interval: float,
    horizons: tuple[float, ...] = DEFAULT_HORIZONS,
) -> dict:
    runs = split_runs(rows, sample_interval)
    report: dict = {
        "runs": len(runs),
        "longest_run": max((len(run) for run in runs), default=0),
        "samples_in_runs": sum(len(run) for run in runs),
        "parameters": {
            "moving_average_window": MA_WINDOW,
            "ses_alpha": SES_ALPHA,
            "holt_alpha": HOLT_ALPHA,
            "holt_beta": HOLT_BETA,
            "min_history": MIN_HISTORY,
            "burst_rule": f"actual >= {BURST_FLOOR_MBPS:g} Mbps and >= {BURST_RATIO:g}x the {BURST_MEDIAN_WINDOW}-sample median before the origin",
        },
        "receive": {},
        "transmit": {},
        "leakage": "Each forecast uses only samples at or before its origin. Later samples are labels.",
    }
    for direction, field in (("receive", "rx_mbps"), ("transmit", "tx_mbps")):
        for horizon in horizons:
            report[direction][str(int(horizon))] = evaluate_runs(
                runs, field, horizon_seconds=horizon, sample_interval=sample_interval
            )
    return report

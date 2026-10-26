"""Statistical forecasts from real throughput observations.

Two level methods are implemented:

* Moving average of the latest ``window`` valid observations.
* Simple exponential smoothing

      F(2) = X(1)
      F(t+1) = alpha * X(t) + (1 - alpha) * F(t)    for t >= 2

  The initialization sets the first forecast equal to the first observation.
  Forecasts are scored only after the recurrence has been applied, which
  requires two observations. Both methods produce a flat level. Holding that
  level across a horizon is a property of the method, not evidence that the
  horizon was validated.

Irregular observations are not treated as equally spaced. A contiguous run
keeps successive valid samples whose wall-clock gap is within half a sample
of the configured interval. Older runs, gaps, and missing rates are excluded
instead of being interpolated or replaced with zero.

Evaluation is walk-forward and one-step. Each origin uses only observations
at or before that origin. Training-set error is not reported as test error.
MAPE is omitted when any actual value in the scored set is near zero.
Empirical 95% residual quantiles are returned only when at least 30 one-step
residuals exist, and they are not stretched across longer horizons.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

MIN_INTERVAL_RESIDUALS = 30
NEAR_ZERO_MBPS = 0.05


@dataclass(frozen=True)
class Point:
    timestamp: float
    value: float
    interval_seconds: float | None = None


def moving_average_forecast(values: list[float], window: int) -> float | None:
    if window < 2 or len(values) < window:
        return None
    sample = values[-window:]
    return sum(sample) / window


def exponential_smoothing_forecast(values: list[float], alpha: float) -> float | None:
    """Return the forecast of the next point. None when the recurrence cannot run."""
    if not 0 < alpha <= 1:
        raise ValueError("alpha must be in the interval (0, 1].")
    if len(values) < 2:
        return None
    forecast = values[0]
    for value in values[1:]:
        forecast = alpha * value + (1 - alpha) * forecast
    return forecast


def persistence_forecast(values: list[float]) -> float | None:
    if not values:
        return None
    return values[-1]


def describe_recent_rise(values: list[float], *, lookback: int = 12) -> dict:
    """Say whether the latest sample is already far above the preceding level.

    The latest sample is an input, so a true result means the rise has started.
    It is not a prediction that the rise was coming, and it is not a five-minute forecast.
    """
    if len(values) < lookback + 1:
        return {
            "status": "insufficient_history",
            "rising": False,
            "latest_mbps": values[-1] if values else None,
            "prior_median_mbps": None,
            "lookback": lookback,
            "note": "Not enough preceding samples to compare the latest rate with its recent level.",
        }
    latest = values[-1]
    prior = sorted(values[-(lookback + 1):-1])
    median = prior[len(prior) // 2]
    baseline_source = values[max(0, len(values) - 60):-1]
    baseline = sorted(baseline_source)[len(baseline_source) // 2]
    onset = latest >= 5 and (latest - median) >= 5 and (median <= 0.5 or latest >= median * 3)
    # Still elevated after the short window has filled with the burst itself.
    still_above_baseline = latest >= 8 and baseline <= latest / 3
    rising = onset or still_above_baseline
    return {
        "status": "rise_in_progress" if rising else "no_rise",
        "rising": rising,
        "latest_mbps": latest,
        "prior_median_mbps": min(median, baseline),
        "lookback": lookback,
        "note": (
            "The latest sample is already well above the preceding median. "
            "This is not a forecast of the rise, and it does not change the five-minute level."
            if rising
            else "The latest sample is not far above the preceding median."
        ),
    }


def contiguous_run(points: list[Point], sample_interval: float) -> tuple[list[Point], int]:
    """Return the latest equally spaced run and how many valid points were excluded."""
    if sample_interval <= 0:
        return [], len(points)
    ordered = sorted(points, key=lambda point: point.timestamp)
    if not ordered:
        return [], 0
    low = sample_interval * 0.5
    high = sample_interval * 1.5
    runs: list[list[Point]] = [[ordered[0]]]
    for point in ordered[1:]:
        gap = point.timestamp - runs[-1][-1].timestamp
        own_interval_ok = point.interval_seconds is None or low <= point.interval_seconds <= high
        if low <= gap <= high and own_interval_ok:
            runs[-1].append(point)
        else:
            runs.append([point])
    latest = runs[-1]
    excluded = len(ordered) - len(latest)
    return latest, excluded


def _metrics(pairs: list[tuple[float, float]]) -> dict | None:
    if not pairs:
        return None
    errors = [forecast - actual for forecast, actual in pairs]
    absolute = [abs(error) for error in errors]
    count = len(pairs)
    mae = sum(absolute) / count
    rmse = math.sqrt(sum(error * error for error in errors) / count)
    bias = sum(errors) / count
    actuals = [actual for _, actual in pairs]
    mape_ok = all(abs(actual) >= NEAR_ZERO_MBPS for actual in actuals)
    mape = None
    if mape_ok:
        mape = sum(abs(forecast - actual) / abs(actual) for forecast, actual in pairs) / count * 100
    return {
        "mae": mae,
        "rmse": rmse,
        "bias": bias,
        "mape": mape,
        "mape_status": "reported" if mape_ok else "not_reported_near_zero_actuals",
        "n": count,
    }


def _percentile(sorted_values: list[float], fraction: float) -> float:
    if not sorted_values:
        raise ValueError("empty")
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def empirical_interval(residuals: list[float]) -> dict | None:
    """Central 95% of one-step residuals. None below the minimum sample count."""
    if len(residuals) < MIN_INTERVAL_RESIDUALS:
        return None
    ordered = sorted(residuals)
    return {
        "method": "empirical_one_step_residual_quantiles",
        "level": 0.95,
        "residual_low": _percentile(ordered, 0.025),
        "residual_high": _percentile(ordered, 0.975),
        "n": len(ordered),
        "applies_to": "one_step_only",
        "assumptions": (
            "The interval adds the central 95% of historical one-step walk-forward residuals "
            "(actual minus forecast) to the current one-step point forecast. It assumes future "
            "one-step errors resemble those residuals. It is not widened for longer horizons and "
            "it is not a formal model confidence interval."
        ),
    }


def _walk_forward(values: list[float], method: str, window: int, alpha: float) -> list[tuple[int, float, float]]:
    """Return (index, forecast, actual) for each one-step origin that method can score."""
    scored: list[tuple[int, float, float]] = []
    if method == "persistence":
        for index in range(1, len(values)):
            scored.append((index, values[index - 1], values[index]))
        return scored
    if method == "moving_average":
        if len(values) < window + 1 or window < 2:
            return []
        rolling = sum(values[:window])
        for index in range(window, len(values)):
            scored.append((index, rolling / window, values[index]))
            rolling += values[index] - values[index - window]
        return scored
    if method == "exponential_smoothing":
        if len(values) < 3:
            return []
        forecast = values[0]
        forecast = alpha * values[1] + (1 - alpha) * forecast
        for index in range(2, len(values)):
            scored.append((index, forecast, values[index]))
            forecast = alpha * values[index] + (1 - alpha) * forecast
        return scored
    raise ValueError(f"Unknown method {method}")


def evaluate_series(
    points: list[Point],
    *,
    window: int,
    alpha: float,
    horizon_steps: int,
) -> dict:
    """Walk-forward one-step scores. Multi-step horizon scores stay pending until enough future points exist."""
    values = [point.value for point in points]
    origins = {
        "persistence": _walk_forward(values, "persistence", window, alpha),
        "moving_average": _walk_forward(values, "moving_average", window, alpha),
        "exponential_smoothing": _walk_forward(values, "exponential_smoothing", window, alpha),
    }
    start_index = max(window, 2)
    paired_indexes = set(range(start_index, len(values)))
    for rows in origins.values():
        paired_indexes &= {index for index, _, _ in rows}
    ordered_indexes = sorted(paired_indexes)

    def _paired(rows: list[tuple[int, float, float]]) -> list[tuple[float, float]]:
        lookup = {index: (forecast, actual) for index, forecast, actual in rows}
        return [lookup[index] for index in ordered_indexes]

    methods = {}
    for name, rows in origins.items():
        metrics = _metrics(_paired(rows))
        methods[name] = metrics or {
            "mae": None,
            "rmse": None,
            "bias": None,
            "mape": None,
            "mape_status": "pending",
            "n": 0,
        }

    comparable = [name for name, metrics in methods.items() if metrics["n"] > 0 and metrics["rmse"] is not None]
    lowest = None
    if len(comparable) == len(methods) and comparable:
        lowest = min(comparable, key=lambda name: methods[name]["rmse"])

    intervals = {}
    for name, rows in origins.items():
        lookup = {index: (forecast, actual) for index, forecast, actual in rows}
        residuals = [lookup[index][1] - lookup[index][0] for index in ordered_indexes if index in lookup]
        intervals[name] = empirical_interval(residuals)
    interval = intervals.get("exponential_smoothing")
    period = None
    if ordered_indexes:
        period = {
            "start": points[ordered_indexes[0]].timestamp,
            "end": points[ordered_indexes[-1]].timestamp,
        }

    horizon_status = "pending"
    horizon_n = 0
    if horizon_steps <= 1 and ordered_indexes:
        horizon_status = "evaluated_as_one_step"
        horizon_n = len(ordered_indexes)
    elif horizon_steps > 1:
        # An h-step score exists only when the actual h steps ahead is already observed
        # and the forecast at the origin did not use those future points. We do not
        # substitute the one-step residual for that score.
        available = 0
        for index in ordered_indexes:
            if index + horizon_steps - 1 < len(values):
                available += 1
        horizon_n = available
        horizon_status = "pending" if available < 5 else "available_not_fit"
        # The level methods are flat, so an h-step point forecast equals the one-step
        # forecast. Scoring it still requires the future actual. Compute it directly
        # from the same origin forecast when enough actuals exist. This does not leak:
        # the forecast stored at `index` was produced from values before `index`.
        if available >= 5:
            horizon_pairs: dict[str, list[tuple[float, float]]] = {name: [] for name in origins}
            lookups = {
                name: {item[0]: item[1] for item in rows} for name, rows in origins.items()
            }
            for index in ordered_indexes:
                future_index = index + horizon_steps - 1
                if future_index >= len(values):
                    continue
                for name in origins:
                    if index not in lookups[name]:
                        continue
                    horizon_pairs[name].append((lookups[name][index], values[future_index]))
            for name, pairs in horizon_pairs.items():
                metrics = _metrics(pairs)
                if metrics:
                    methods[name]["horizon"] = metrics
            horizon_status = (
                "evaluated" if any(methods[name].get("horizon") for name in methods) else "pending"
            )

    status = "evaluated" if ordered_indexes else "pending"
    minimum = max(window, 2) + 1
    return {
        "status": status,
        "split": "walk_forward_one_step",
        "training_metrics_reported": False,
        "leakage": "Each scored forecast is a function of observations strictly before the actual.",
        "minimum_points": minimum,
        "points_in_run": len(points),
        "paired_origins": len(ordered_indexes),
        "period": period,
        "methods": methods,
        "comparison": {
            "lowest_rmse": lowest,
            "note": (
                "Methods are compared on the shared set of origins where persistence, "
                "the moving average, and exponential smoothing can all forecast."
                if lowest
                else "A method comparison is pending until every method has out-of-sample origins."
            ),
        },
        "one_step_intervals": intervals,
        "one_step_interval": interval,
        "interval_status": "available" if any(item for item in intervals.values()) else "pending",
        "interval_minimum_residuals": MIN_INTERVAL_RESIDUALS,
        "horizon_steps": horizon_steps,
        "horizon_evaluation": horizon_status,
        "horizon_pairs_available": horizon_n,
        "mape_rule": f"MAPE is omitted when any actual throughput in the scored set is below {NEAR_ZERO_MBPS} Mbps.",
    }


def forecast_direction(
    points: list[Point],
    *,
    method: str,
    window: int,
    alpha: float,
    sample_interval: float,
    horizon_seconds: float,
) -> dict:
    run, excluded = contiguous_run(points, sample_interval)
    values = [point.value for point in run]
    minimum = window if method == "moving_average" else 2
    steps = max(1, int(round(horizon_seconds / sample_interval)))
    base = {
        "method": method,
        "window": window if method == "moving_average" else None,
        "alpha": alpha if method == "exponential_smoothing" else None,
        "sample_interval_seconds": sample_interval,
        "horizon_seconds": steps * sample_interval,
        "steps": steps,
        "minimum_observations": minimum,
        "observations_used": len(run),
        "observations_excluded_as_gaps": excluded,
        "flat": True,
        "sufficient": False,
        "point_mbps": None,
        "origin_timestamp": run[-1].timestamp if run else None,
        "series": [],
        "evaluation": evaluate_series(run, window=window, alpha=alpha, horizon_steps=steps),
        "note": (
            "The forecast is a level held flat across the horizon. It is an estimate, not a guarantee. "
            "Missing samples were not interpolated. A sudden jump is not predicted before it appears."
        ),
        "recent_rise": describe_recent_rise(values),
    }
    if len(run) < minimum:
        base["status"] = "insufficient_data"
        base["note"] = (
            f"Need at least {minimum} equally spaced valid observations in the latest run. "
            f"The latest run has {len(run)}. No forecast was issued."
        )
        return base

    if method == "moving_average":
        point = moving_average_forecast(values, window)
    elif method == "exponential_smoothing":
        point = exponential_smoothing_forecast(values, alpha)
    else:
        raise ValueError("method must be moving_average or exponential_smoothing")

    origin = run[-1].timestamp
    base.update(
        {
            "status": "ok",
            "sufficient": True,
            "point_mbps": point,
            "series": [
                {"timestamp": origin + sample_interval, "mbps": point, "kind": "forecast"},
                {"timestamp": origin + steps * sample_interval, "mbps": point, "kind": "forecast"},
            ],
            "last_observation_at": origin,
        }
    )
    interval = (base["evaluation"].get("one_step_intervals") or {}).get(method)
    if interval and steps == 1:
        base["interval"] = {
            **interval,
            "low_mbps": point + interval["residual_low"],
            "high_mbps": point + interval["residual_high"],
        }
    else:
        base["interval"] = None
        if steps > 1:
            base["interval_note"] = (
                "A multi-step prediction interval is not shown. One-step residual quantiles are not relabeled as a horizon interval."
            )
    return base

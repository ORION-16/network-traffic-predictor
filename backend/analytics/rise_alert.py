"""Current rise alert and the gate for a five-minute threshold warning.

A rise flag uses only samples already observed. It means traffic is high
relative to the recent median, not that the rise was predicted.

The five-minute flat forecast is a separate level. An advance warning, that
the next five minutes will cross a saved threshold, is enabled only when a
walk-forward comparison beats persistence, a moving average, and exponential
smoothing. Otherwise the dashboard says the evidence is insufficient.
"""

from __future__ import annotations

from analytics.forecasting import (
    describe_recent_rise,
    exponential_smoothing_forecast,
    moving_average_forecast,
)

ADVANCE_MESSAGE = "Insufficient evidence for reliable advance warning"
CANDIDATE = "recent_slope"
BASELINES = ("never", "persistence", "moving_average", "exponential_smoothing")
MIN_EVENTS = 5
MIN_PRECISION = 0.5


def _applies(direction: str, side: str) -> bool:
    if direction == "receive_only":
        return side == "receive"
    if direction == "transmit_only":
        return side == "transmit"
    return True


def _applies_rise(direction: str, side: str, thresholds: dict | None) -> bool:
    if thresholds is not None:
        return True
    return _applies(direction, side)


def _slope_forecast(values: list[float], horizon: int) -> float | None:
    """Project the latest point with the change across the last 12 observations."""
    if len(values) < 12 or horizon < 1:
        return None
    slope = (values[-1] - values[-12]) / 11
    return values[-1] + slope * horizon


def _predict(method: str, values: list[float], threshold: float, horizon: int) -> bool:
    """Whether this method warns of a future crossing. The current point is included."""
    if method == "never":
        return False
    latest = values[-1]
    if method == "persistence":
        return latest >= threshold
    if method == "moving_average":
        level = moving_average_forecast(values, 12)
        return level is not None and level >= threshold
    if method == "exponential_smoothing":
        level = exponential_smoothing_forecast(values, 0.3)
        return level is not None and level >= threshold
    if method == "recent_slope":
        if latest >= threshold:
            return False
        projected = _slope_forecast(values, horizon)
        return projected is not None and projected >= threshold
    raise ValueError(f"Unknown method {method}")


def evaluate_advance_warning(
    values: list[float],
    threshold: float,
    *,
    horizon: int = 300,
    min_history: int = 12,
) -> dict:
    """Score advance warnings on one series. Future samples are labels only.

    An origin is eligible when the current sample is still under the threshold
    and a full horizon of later samples exists. Persistence can warn only once
    the current sample is already over the threshold, so it does not count as
    an advance warning on these origins.
    """
    if threshold <= 0:
        raise ValueError("threshold must be positive")
    if horizon < 1:
        raise ValueError("horizon must be at least 1")
    methods = ("never", "persistence", "moving_average", "exponential_smoothing", CANDIDATE)
    counts = {
        name: {"tp": 0, "fp": 0, "tn": 0, "fn": 0, "event_hits": 0, "event_misses": 0, "lead_sum": 0, "lead_n": 0}
        for name in methods
    }
    events = [
        index
        for index in range(1, len(values))
        if values[index] >= threshold and values[index - 1] < threshold
    ]
    eligible_events = []
    predictions: dict[str, dict[int, bool]] = {name: {} for name in methods}

    for origin in range(min_history - 1, len(values) - horizon):
        if values[origin] >= threshold:
            continue
        future = values[origin + 1 : origin + 1 + horizon]
        crossed = any(point >= threshold for point in future)
        history = values[: origin + 1]
        for name in methods:
            warned = _predict(name, history, threshold, horizon) and values[origin] < threshold
            predictions[name][origin] = warned
            bucket = counts[name]
            if warned and crossed:
                bucket["tp"] += 1
            elif warned and not crossed:
                bucket["fp"] += 1
            elif not warned and crossed:
                bucket["fn"] += 1
            else:
                bucket["tn"] += 1

    for event in events:
        window = range(max(min_history - 1, event - horizon), event)
        scored = [origin for origin in window if origin in predictions["never"]]
        if not scored:
            continue
        eligible_events.append(event)
        for name in methods:
            warned_at = [origin for origin in scored if predictions[name].get(origin)]
            if warned_at:
                counts[name]["event_hits"] += 1
                counts[name]["lead_sum"] += event - min(warned_at)
                counts[name]["lead_n"] += 1
            else:
                counts[name]["event_misses"] += 1

    def _rate(numerator: int, denominator: int) -> float | None:
        if denominator == 0:
            return None
        return numerator / denominator

    method_report = {}
    for name, bucket in counts.items():
        predicted = bucket["tp"] + bucket["fp"]
        quiet = bucket["fp"] + bucket["tn"]
        actual = bucket["tp"] + bucket["fn"]
        event_total = bucket["event_hits"] + bucket["event_misses"]
        method_report[name] = {
            "precision": _rate(bucket["tp"], predicted),
            "false_positive_rate": _rate(bucket["fp"], quiet),
            "missed_origin_rate": _rate(bucket["fn"], actual),
            "event_recall": _rate(bucket["event_hits"], event_total),
            "missed_event_rate": _rate(bucket["event_misses"], event_total),
            "origins": predicted + bucket["tn"] + bucket["fn"],
            "warnings": predicted,
            "event_hits": bucket["event_hits"],
            "event_misses": bucket["event_misses"],
            "mean_lead_steps": _rate(bucket["lead_sum"], bucket["lead_n"]),
        }
    return {
        "threshold_mbps": threshold,
        "horizon_steps": horizon,
        "points": len(values),
        "events": len(eligible_events),
        "methods": method_report,
        "counts": counts,
        "leakage": "Each warning uses observations at or before the origin. Later samples are the label only.",
    }


def merge_advance_reports(reports: list[dict]) -> dict:
    """Sum walk-forward counts from separate contiguous runs."""
    usable = [report for report in reports if report.get("counts")]
    if not usable:
        return evaluate_advance_warning([], 1.0, horizon=1)
    methods = usable[0]["counts"]
    totals = {
        name: {key: 0 for key in methods[name]}
        for name in methods
    }
    for report in usable:
        for name, bucket in report["counts"].items():
            for key, value in bucket.items():
                totals[name][key] += int(value)
    merged = evaluate_advance_warning([], 1.0, horizon=usable[0]["horizon_steps"])
    merged["counts"] = totals
    merged["events"] = sum(int(report["events"]) for report in usable)
    merged["points"] = sum(int(report["points"]) for report in usable)
    merged["threshold_mbps"] = usable[0]["threshold_mbps"]
    merged["horizon_steps"] = usable[0]["horizon_steps"]

    def _rate(numerator: int, denominator: int) -> float | None:
        if denominator == 0:
            return None
        return numerator / denominator

    for name, bucket in totals.items():
        predicted = bucket["tp"] + bucket["fp"]
        quiet = bucket["fp"] + bucket["tn"]
        actual = bucket["tp"] + bucket["fn"]
        event_total = bucket["event_hits"] + bucket["event_misses"]
        merged["methods"][name] = {
            "precision": _rate(bucket["tp"], predicted),
            "false_positive_rate": _rate(bucket["fp"], quiet),
            "missed_origin_rate": _rate(bucket["fn"], actual),
            "event_recall": _rate(bucket["event_hits"], event_total),
            "missed_event_rate": _rate(bucket["event_misses"], event_total),
            "origins": predicted + bucket["tn"] + bucket["fn"],
            "warnings": predicted,
            "event_hits": bucket["event_hits"],
            "event_misses": bucket["event_misses"],
            "mean_lead_steps": _rate(bucket.get("lead_sum", 0), bucket.get("lead_n", 0)),
        }
    return merged


def warning_beats_baselines(report: dict) -> bool:
    """True only when the slope rule beats every simple baseline.

    It must warn before more threshold crossings than each baseline, keep a
    false-alarm rate no higher than each baseline, and keep precision at or
    above one half. Fewer than five scored crossings is not enough evidence.
    """
    if int(report.get("events") or 0) < MIN_EVENTS:
        return False
    candidate = report["methods"][CANDIDATE]
    recall = candidate.get("event_recall")
    precision = candidate.get("precision")
    false_positive = candidate.get("false_positive_rate")
    if recall is None or recall <= 0 or precision is None or precision < MIN_PRECISION:
        return False
    if false_positive is None:
        return False
    for name in BASELINES:
        baseline = report["methods"][name]
        base_recall = baseline.get("event_recall") or 0
        base_false_positive = baseline.get("false_positive_rate") or 0
        if recall <= base_recall or false_positive > base_false_positive:
            return False
    return True


def advance_warning_block(report: dict | None = None, *, predicts: bool = False) -> dict:
    """The live gate. A missing report is not treated as a successful model."""
    enabled = bool(report) and warning_beats_baselines(report)
    if enabled:
        return {
            "enabled": True,
            "status": "enabled",
            "predicts": predicts,
            "message": "A checked rule beat the baselines on recorded crossings. It still does not name an exact start time.",
        }
    return {
        "enabled": False,
        "status": "insufficient_evidence",
        "predicts": False,
        "message": ADVANCE_MESSAGE,
    }


MIN_HISTORY_POINTS = 12
STATE_LABELS = {
    "unavailable": "Collector unavailable or stale",
    "threshold_exceeded": "Threshold exceeded",
    "traffic_rising": "Traffic rising",
    "high_predicted_risk": "Predicted threshold risk",
    "insufficient_history": "Insufficient history",
    "normal": "Normal",
}
_SIDE_WORDS = {"receive": "download", "transmit": "upload"}


def _sides_text(sides: list[str]) -> str:
    return " and ".join(_SIDE_WORDS[side] for side in sides)


def build_rise_alert(
    *,
    fresh: bool,
    quality: str | None,
    sampled_at: float | None,
    direction: str,
    receive_rise: dict | None,
    transmit_rise: dict | None,
    capacity_mbps: float | None,
    capacity_source: str | None,
    advance_report: dict | None = None,
    advance_predicts: bool = False,
    threshold_alert: dict | None = None,
    thresholds: dict | None = None,
    history_points: int | None = None,
    freshness: str | None = None,
) -> dict:
    """One alert state for the panel, with the reason and the sample time it rests on.

    Priority: unavailable, threshold exceeded, traffic rising, predicted risk,
    insufficient history, normal. A rate at or above a saved threshold is never
    reported as normal.
    """
    advance = advance_warning_block(advance_report, predicts=advance_predicts)
    measured = fresh and quality == "ok"
    if thresholds is not None:
        side_thresholds = {"receive": thresholds.get("receive"), "transmit": thresholds.get("transmit")}
    else:
        configured_legacy = capacity_mbps is not None and capacity_mbps > 0 and capacity_source == "user"
        side_thresholds = {
            side: capacity_mbps if configured_legacy and _applies(direction, side) else None
            for side in ("receive", "transmit")
        }
    watched = {side: side_thresholds[side] is not None for side in side_thresholds}
    any_threshold = any(watched.values())
    receive = receive_rise if (watched["receive"] or not any_threshold) and _applies_rise(direction, "receive", thresholds) else None
    transmit = transmit_rise if (watched["transmit"] or not any_threshold) and _applies_rise(direction, "transmit", thresholds) else None
    rising_sides = []
    if receive and receive.get("rising"):
        rising_sides.append("receive")
    if transmit and transmit.get("rising"):
        rising_sides.append("transmit")
    rising = bool(rising_sides) and measured

    live = (threshold_alert or {}).get("live") or {}
    exceeded_sides = [side for side in ("receive", "transmit") if (live.get(side) or {}).get("active")]

    if not measured:
        state = "unavailable"
        directions: list[str] = []
        if freshness == "stale":
            explanation = "The newest stored reading is too old. The collector may be stopped or the interface may be down."
        elif quality and quality != "ok":
            explanation = f"The newest reading is marked {quality}. It is not used as a rate, and no alert is inferred from it."
        else:
            explanation = "No current rate is available yet."
    elif exceeded_sides:
        state = "threshold_exceeded"
        directions = exceeded_sides
        parts = []
        for side in exceeded_sides:
            item = live[side]
            latest = item.get("latest_mbps")
            latest_text = "unknown" if latest is None else f"{latest:.2f} Mbps"
            parts.append(
                f"{_SIDE_WORDS[side].capitalize()} is at {latest_text} against your {item['threshold_mbps']:g} Mbps threshold"
            )
        explanation = (
            "; ".join(parts)
            + ". It recovers after 3 valid readings below 90% of the threshold."
        )
    elif rising:
        state = "traffic_rising"
        directions = rising_sides
        explanation = (
            f"{_sides_text(rising_sides).capitalize()} is well above its recent median. "
            "This was detected after it started, not predicted."
        )
    elif advance["enabled"] and advance["predicts"]:
        state = "high_predicted_risk"
        directions = []
        explanation = advance["message"]
    elif history_points is not None and history_points < MIN_HISTORY_POINTS:
        state = "insufficient_history"
        directions = []
        explanation = (
            f"Only {history_points} contiguous valid readings so far on this interface. "
            f"Rise detection needs {MIN_HISTORY_POINTS}. Threshold checks still run on each reading."
        )
    else:
        state = "normal"
        directions = []
        if any_threshold:
            explanation = "Current rates are below your saved thresholds and not rising sharply."
        else:
            explanation = "No threshold is saved. Only sharp rises are checked."
    configured = capacity_mbps is not None and capacity_mbps > 0 and capacity_source == "user"
    configured = configured or any_threshold
    return {
        "state": state,
        "label": STATE_LABELS[state],
        "explanation": explanation,
        "rising": rising,
        "directions": directions,
        "rising_directions": rising_sides if rising else [],
        "exceeded_directions": exceeded_sides if measured else [],
        "thresholds_mbps": side_thresholds,
        "threshold_alert": threshold_alert,
        "sampled_at": sampled_at,
        "receive": receive,
        "transmit": transmit,
        "advance": advance,
        "capacity_mbps": capacity_mbps if configured else None,
        "capacity_is_user_threshold": configured,
        "capacity_note": (
            "The saved capacity is a threshold you entered, not a measured internet capacity."
            if configured
            else "No threshold is saved. Adapter link speed is not used as capacity."
        ),
        "flat_forecast_note": (
            "The dashed five-minute line remains a flat level. "
            "It does not predict when an unknown download will start."
        ),
    }


def rise_from_values(values: list[float]) -> dict:
    """Public wrapper so tests call the same rule as the forecast payload."""
    return describe_recent_rise(values)

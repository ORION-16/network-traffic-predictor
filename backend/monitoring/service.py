"""Build API payloads from stored readings and the statistical modules."""

from __future__ import annotations

import math
import time

from analytics.assessment import assess, direction_explanation, utilization_block
from analytics.forecasting import Point, forecast_direction
from analytics.rise_alert import build_rise_alert
from analytics.thresholds import effective_thresholds
from monitoring.collector import Collector
from monitoring.forecast_log import summarize_forecasts
from monitoring.interfaces import discover_interfaces

_FORECAST_CACHE: dict[str, object] = {"key": None, "at": 0.0, "value": None}
_COVERAGE_CACHE: dict[str, tuple[float, list[dict]]] = {}


def freshness_for(row: dict | None, interval: float, now: float, collector_status: str) -> str:
    if collector_status == "interface_unavailable":
        return "stale" if row else "no_samples"
    if row is None:
        return "no_samples"
    if row.get("quality") == "baseline":
        return "baseline"
    age = now - float(row["sampled_at"])
    if age > max(3 * interval, 5):
        return "stale"
    return "fresh"


def _points(rows: list[dict], field: str) -> list[Point]:
    points: list[Point] = []
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


def build_forecast(
    rows: list[dict],
    *,
    method: str,
    window: int,
    alpha: float,
    sample_interval: float,
    horizon_seconds: float,
) -> dict:
    receive = forecast_direction(
        _points(rows, "rx_mbps"),
        method=method,
        window=window,
        alpha=alpha,
        sample_interval=sample_interval,
        horizon_seconds=horizon_seconds,
    )
    transmit = forecast_direction(
        _points(rows, "tx_mbps"),
        method=method,
        window=window,
        alpha=alpha,
        sample_interval=sample_interval,
        horizon_seconds=horizon_seconds,
    )
    sufficient = bool(receive["sufficient"] or transmit["sufficient"])
    return {
        "method": method,
        "parameters": {
            "window": window if method == "moving_average" else None,
            "alpha": alpha if method == "exponential_smoothing" else None,
            "horizon_seconds": horizon_seconds,
            "sample_interval_seconds": sample_interval,
        },
        "sufficient": sufficient,
        "status": "ok" if sufficient else "insufficient_data",
        "receive": receive,
        "transmit": transmit,
        "label": "forecast",
        "reconstruction": (
            "Model state is rebuilt from persisted valid observations. "
            "A restart does not invent the samples needed for a forecast."
        ),
    }


def interface_payload(name: str | None) -> dict | None:
    if not name:
        return None
    for record in discover_interfaces():
        if record.name == name:
            payload = record.as_dict()
            payload["speed_note"] = (
                "reported_link_speed_mbps and os_link_speed_text come from the operating system. "
                "They are not bottleneck capacity and are not used in utilization."
            )
            return payload
    return {
        "name": name,
        "is_up": False,
        "kind": "unknown",
        "is_default_route": False,
        "reported_link_speed_mbps": None,
        "link_speed_status": "unknown",
        "speed_note": "The selected interface is not currently present.",
    }


MAX_CHART_POINTS = 900


def packet_capture_status() -> dict:
    from capture.state import capture_state

    status = capture_state.status
    return {
        "status": status.name.lower() if hasattr(status, "name") else str(status),
        "is_capturing": capture_state.is_capturing,
        "error": capture_state.error,
        "role": "Optional diagnostic. Stored throughput always comes from OS counters.",
    }


def downsample_history(rows: list[dict], max_points: int, window_seconds: float | None = None) -> tuple[list[dict], dict]:
    """Reduce long windows to clock-aligned buckets, keeping each bucket's peak.

    A bucket with no valid reading stays invalid, so gaps are not filled.
    Short windows are returned unchanged. Aligned buckets keep earlier points
    identical between polls, so the chart can append instead of redrawing.
    """
    if len(rows) <= max_points or not rows:
        interval = rows[-1].get("interval_seconds") if rows else None
        return rows, {"downsampled": False, "bucket_seconds": interval, "aggregate": None}
    span = window_seconds or (float(rows[-1]["sampled_at"]) - float(rows[0]["sampled_at"]))
    width = max(1.0, float(math.ceil(span / max_points)))
    buckets: dict[int, list[dict]] = {}
    for row in rows:
        buckets.setdefault(int(float(row["sampled_at"]) // width), []).append(row)
    out = []
    for index in sorted(buckets):
        items = buckets[index]
        valid = [item for item in items if item.get("quality") == "ok"]

        def peak(field: str) -> float | None:
            values = [item[field] for item in valid if item.get(field) is not None]
            return max(values) if values else None

        out.append(
            {
                "sampled_at": index * width,
                "interval_seconds": width,
                "quality": "ok" if valid else items[-1].get("quality"),
                "rx_mbps": peak("rx_mbps"),
                "tx_mbps": peak("tx_mbps"),
            }
        )
    return out, {"downsampled": True, "bucket_seconds": width, "aggregate": "max"}


def profile_summary(collector: Collector, selected: str | None) -> dict:
    """Profiles are keyed by interface name. Each keeps its own rows, forecasts, and alerts."""
    config = collector.store.get_config()
    saved = config.get("profiles") if isinstance(config.get("profiles"), dict) else {}
    key = str(collector.store.path)
    cached = _COVERAGE_CACHE.get(key)
    if cached is not None and time.monotonic() - cached[0] < 30:
        coverage = cached[1]
    else:
        coverage = collector.store.interface_coverage()
        _COVERAGE_CACHE[key] = (time.monotonic(), coverage)
    names = {row["interface_name"] for row in coverage} | set(saved)
    items = []
    by_name = {row["interface_name"]: row for row in coverage}
    for profile_name in sorted(names, key=lambda item: (item != selected, item.lower())):
        row = by_name.get(profile_name, {})
        items.append(
            {
                "name": profile_name,
                "selected": profile_name == selected,
                "observations": int(row.get("observations") or 0),
                "valid_observations": int(row.get("valid_observations") or 0),
                "first_at": row.get("first_at"),
                "latest_at": row.get("latest_at"),
                "thresholds": effective_thresholds(config, profile_name),
                "has_own_thresholds": bool(saved.get(profile_name)),
            }
        )
    return {
        "mode": config.get("interface_mode") or "manual",
        "selected": selected,
        "items": items,
        "note": (
            "A profile is one interface on this computer. Histories, forecasts, and alerts are never mixed "
            "between profiles. Different Wi-Fi networks joined through the same adapter share one profile; "
            "an address change on that adapter is marked as a transition and re-baselined."
        ),
    }


def build_dashboard(
    collector: Collector,
    *,
    method: str = "exponential_smoothing",
    window: int = 12,
    alpha: float = 0.3,
    horizon_seconds: float = 60,
    history_seconds: float = 300,
) -> dict:
    now = time.time()
    name = collector.selected_name()
    config = collector.config()
    health = collector.health()
    current = collector.store.latest(name) if name else None
    freshness = freshness_for(current, collector.interval, now, health["status"])
    history = []
    resolution = {"downsampled": False, "bucket_seconds": collector.interval, "aggregate": None}
    model_rows: list[dict] = []
    if name:
        raw = [
            {
                "sampled_at": row.get("sampled_at"),
                "interval_seconds": row.get("interval_seconds"),
                "quality": row.get("quality"),
                "rx_mbps": row.get("rx_mbps"),
                "tx_mbps": row.get("tx_mbps"),
            }
            for row in collector.store.history(
                name,
                start=now - history_seconds,
                end=now + 1,
                limit=min(100_000, int(history_seconds / max(collector.interval, 0.2)) + 100),
            )
        ]
        history, resolution = downsample_history(raw, MAX_CHART_POINTS, history_seconds)
        model_rows = collector.forecast_rows_for_model(name)

    cache_key = (
        str(collector.store.path),
        name,
        len(model_rows),
        model_rows[-1]["sampled_at"] if model_rows else None,
        method,
        window,
        alpha,
        horizon_seconds,
    )
    cached = _FORECAST_CACHE
    if cached["key"] == cache_key and now - float(cached["at"]) < 5:
        forecast = cached["value"]
    else:
        forecast = build_forecast(
            model_rows,
            method=method,
            window=window,
            alpha=alpha,
            sample_interval=collector.interval,
            horizon_seconds=horizon_seconds,
        )
        cached["key"] = cache_key
        cached["at"] = now
        cached["value"] = forecast

    thresholds = effective_thresholds(config, name)
    alert_snapshot = collector.alert_snapshot()
    capacity = config.get("capacity_mbps")
    source = config.get("capacity_source") or "unknown"
    if capacity is None:
        source = "unknown"
    direction = config.get("direction") or "per_direction"
    rx_history = [point.value for point in _points(model_rows, "rx_mbps")]
    tx_history = [point.value for point in _points(model_rows, "tx_mbps")]
    forecast_rx = forecast["receive"]["point_mbps"] if forecast["receive"]["sufficient"] else None
    forecast_tx = forecast["transmit"]["point_mbps"] if forecast["transmit"]["sufficient"] else None
    assessment = assess(
        current=current,
        forecast_rx=forecast_rx,
        forecast_tx=forecast_tx,
        forecast_sufficient=bool(forecast["sufficient"]),
        capacity_mbps=capacity,
        capacity_source=source,
        direction=direction,
        warning_utilization_pct=config.get("warning_utilization_pct"),
        high_utilization_pct=config.get("high_utilization_pct"),
        freshness=freshness,
        rx_history=rx_history,
        tx_history=tx_history,
        probe=collector.latest_probe(),
        latency_threshold_ms=config.get("latency_congestion_ms"),
        loss_threshold_pct=config.get("loss_congestion_pct"),
        previous_signature=collector.alert_signature(),
    )
    collector.set_alert_signature(assessment["signature"])

    return {
        "scope": "local_machine_interface",
        "scope_note": health["scope_note"],
        "platform": health["platform"],
        "collected_at": now,
        "units": {
            "throughput": "Mbps_decimal",
            "formula": "Mbps = byte_delta * 8 / elapsed_seconds / 1000000",
            "packet_rate": "packets_per_second",
            "utilization": "percent_of_configured_capacity",
        },
        "interface": interface_payload(name),
        "collection": {
            **health,
            "freshness": freshness,
            "selected_interface": name,
            "interface_mode": config.get("interface_mode") or "manual",
            "packet_capture": packet_capture_status(),
        },
        "current": current,
        "history": history,
        "history_resolution": resolution,
        "dataset": collector.store.dataset_summary(name) if name else {
            "observations": 0,
            "valid_observations": 0,
            "first_at": None,
            "latest_at": None,
            "duration_seconds": None,
            "gaps_filled": False,
        },
        "forecast_ledger": summarize_forecasts(collector.store, name),
        "capacity": {
            "capacity_mbps": capacity,
            "source": source,
            "status": "configured" if capacity is not None and source == "user" else "unknown",
            "direction": direction,
            "direction_explanation": direction_explanation(direction),
            "warning_utilization_pct": config.get("warning_utilization_pct"),
            "high_utilization_pct": config.get("high_utilization_pct"),
            "latency_congestion_ms": config.get("latency_congestion_ms"),
            "loss_congestion_pct": config.get("loss_congestion_pct"),
            "utilization": utilization_block(current, capacity if source == "user" else None, direction),
        },
        "forecast": forecast,
        "thresholds": thresholds,
        "rise_alert": build_rise_alert(
            fresh=freshness == "fresh",
            quality=None if current is None else current.get("quality"),
            sampled_at=None if current is None else current.get("sampled_at"),
            direction=direction,
            receive_rise=forecast["receive"].get("recent_rise"),
            transmit_rise=forecast["transmit"].get("recent_rise"),
            capacity_mbps=capacity,
            capacity_source=source,
            threshold_alert=alert_snapshot,
            thresholds=thresholds,
            history_points=len(model_rows),
            freshness=freshness,
        ),
        "alert_events": collector.store.alert_events(name, limit=20) if name else [],
        "transitions": collector.store.transitions(start=now - history_seconds, limit=20),
        "profiles": profile_summary(collector, name),
        "evaluation": {
            "receive": forecast["receive"]["evaluation"],
            "transmit": forecast["transmit"]["evaluation"],
            "note": "Metrics are walk-forward out-of-sample scores. They are pending when the latest contiguous run is too short.",
        },
        "assessment": assessment,
        "probe": collector.latest_probe(),
        "counter_note": (
            "Byte, packet, error, and drop totals are cumulative OS counters. "
            "A reported zero is the value the OS returned. A missing counter is null, not zero. "
            "Throughput is the delta between readings divided by monotonic elapsed time."
        ),
    }

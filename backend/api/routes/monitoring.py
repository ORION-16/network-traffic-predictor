"""Monitoring, capacity, forecast, and congestion endpoints.

These routes expose interface counters and statistics computed from them.
They do not accept shell commands or packet payloads.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

from monitoring.collector import monitoring_collector
from monitoring.interfaces import discover_interfaces
from monitoring.service import build_dashboard

router = APIRouter(tags=["monitoring"])


class InterfaceSelection(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    mode: Literal["manual", "auto"] = "manual"

    @model_validator(mode="after")
    def needs_name(self) -> "InterfaceSelection":
        if self.mode == "manual" and not self.name:
            raise ValueError("name is required unless mode is auto.")
        return self


class DirectionThresholds(BaseModel):
    download_threshold_mbps: float | None = Field(default=None, gt=0, le=1_000_000)
    upload_threshold_mbps: float | None = Field(default=None, gt=0, le=1_000_000)


class HorizonBody(BaseModel):
    horizon_seconds: float = Field(ge=1, le=3600)


class CapacityBody(BaseModel):
    capacity_mbps: float = Field(gt=0, le=1_000_000)
    direction: Literal["per_direction", "receive_only", "transmit_only"] = "per_direction"
    warning_utilization_pct: float | None = Field(default=None, gt=0, le=100)
    high_utilization_pct: float | None = Field(default=None, gt=0, le=100)

    @model_validator(mode="after")
    def thresholds(self) -> "CapacityBody":
        warning = self.warning_utilization_pct
        high = self.high_utilization_pct
        if (warning is None) != (high is None):
            raise ValueError("Set both utilization thresholds or neither.")
        if warning is not None and high is not None and high <= warning:
            raise ValueError("high_utilization_pct must be greater than warning_utilization_pct.")
        return self


class AlertRulesBody(BaseModel):
    alert_clear_ratio: float | None = Field(default=None, gt=0, lt=1)
    alert_clear_samples: int | None = Field(default=None, ge=1, le=30)
    alert_cooldown_seconds: float | None = Field(default=None, ge=0, le=3600)
    baseline_anomaly_enabled: bool | None = None
    baseline_multiplier: float | None = Field(default=None, gt=1, le=100)
    baseline_floor_mbps: float | None = Field(default=None, gt=0, le=1_000_000)
    baseline_margin_mbps: float | None = Field(default=None, ge=0, le=1_000_000)


class ThresholdBody(BaseModel):
    download_threshold_mbps: float | None = Field(default=None, gt=0, le=1_000_000)
    upload_threshold_mbps: float | None = Field(default=None, gt=0, le=1_000_000)
    warning_utilization_pct: float | None = Field(default=None, gt=0, le=100)
    high_utilization_pct: float | None = Field(default=None, gt=0, le=100)
    latency_congestion_ms: float | None = Field(default=None, gt=0, le=60_000)
    loss_congestion_pct: float | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def pairs(self) -> "ThresholdBody":
        warning_set = "warning_utilization_pct" in self.model_fields_set
        high_set = "high_utilization_pct" in self.model_fields_set
        if warning_set or high_set:
            if (self.warning_utilization_pct is None) != (self.high_utilization_pct is None):
                raise ValueError("Utilization thresholds must be set or cleared together.")
            if (
                self.warning_utilization_pct is not None
                and self.high_utilization_pct is not None
                and self.high_utilization_pct <= self.warning_utilization_pct
            ):
                raise ValueError("high_utilization_pct must be greater than warning_utilization_pct.")
        return self


def _clean_interface(name: str) -> str:
    cleaned = name.strip()
    if not cleaned or any(ord(char) < 32 for char in cleaned):
        raise HTTPException(status_code=400, detail="Invalid interface name.")
    return cleaned


def _dashboard(
    method: str,
    window: int,
    alpha: float,
    horizon_seconds: float,
    history_seconds: float,
) -> dict:
    if method not in {"moving_average", "exponential_smoothing"}:
        raise HTTPException(status_code=400, detail="method must be moving_average or exponential_smoothing.")
    try:
        return build_dashboard(
            monitoring_collector,
            method=method,
            window=window,
            alpha=alpha,
            horizon_seconds=horizon_seconds,
            history_seconds=history_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/monitoring/interfaces")
async def monitoring_interfaces() -> dict:
    records = [record.as_dict() for record in discover_interfaces()]
    selected = monitoring_collector.selected_name()
    return {
        "interfaces": records,
        "selected": selected,
        "selection_rule": "The default selection is the up, non-loopback interface that owns the host default IPv4 route.",
        "scope_note": "Listing interfaces on this computer does not inventory the LAN.",
    }


@router.put("/api/monitoring/interface")
async def select_interface(body: InterfaceSelection) -> dict:
    try:
        if body.mode == "auto":
            record = monitoring_collector.set_auto_interface()
        else:
            record = monitoring_collector.set_interface(_clean_interface(body.name or ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"interface": record}


@router.get("/api/monitoring/current")
async def current_measurement() -> dict:
    payload = _dashboard("exponential_smoothing", 12, 0.3, 60, 1)
    return {
        "collection": payload["collection"],
        "interface": payload["interface"],
        "current": payload["current"],
        "units": payload["units"],
        "scope_note": payload["scope_note"],
    }


@router.get("/api/monitoring/history")
async def history(
    seconds: float = Query(default=300, gt=0, le=604800),
    limit: int = Query(default=1000, gt=0, le=5000),
) -> dict:
    name = monitoring_collector.selected_name()
    if not name:
        return {"interface": None, "observations": [], "note": "No interface is selected."}
    import time

    now = time.time()
    rows = monitoring_collector.store.history(name, start=now - seconds, end=now + 1, limit=limit)
    return {
        "interface": name,
        "observations": rows,
        "count": len(rows),
        "note": "Only stored readings are returned. Gaps are not synthesized.",
    }


@router.put("/api/monitoring/horizon")
async def put_horizon(body: HorizonBody) -> dict:
    """Remember the horizon the collector should store. The chart uses the same value."""
    return monitoring_collector.update_config({"forecast_horizon_seconds": body.horizon_seconds})


@router.get("/api/monitoring/health")
async def monitoring_health() -> dict:
    from monitoring.service import packet_capture_status

    health = monitoring_collector.health()
    health["selected_interface"] = monitoring_collector.selected_name()
    health["interface_mode"] = monitoring_collector.config().get("interface_mode") or "manual"
    health["packet_capture"] = packet_capture_status()
    return health


@router.get("/api/monitoring/dashboard")
async def dashboard(
    method: Literal["moving_average", "exponential_smoothing"] = "exponential_smoothing",
    window: int = Query(default=12, ge=2, le=500),
    alpha: float = Query(default=0.3, gt=0, le=1),
    horizon_seconds: float = Query(default=60, ge=1, le=3600),
    history_seconds: float = Query(default=300, gt=0, le=86400),
) -> dict:
    return _dashboard(method, window, alpha, horizon_seconds, history_seconds)


@router.post("/api/monitoring/probe")
async def probe_now() -> dict:
    """Run one bounded probe to the configured target. The target is not taken from the request body."""
    return monitoring_collector.probe_now()


@router.get("/api/capacity")
async def get_capacity() -> dict:
    payload = _dashboard("exponential_smoothing", 12, 0.3, 60, 1)
    return payload["capacity"] | {"interface": payload["interface"]}


@router.put("/api/capacity")
async def put_capacity(body: CapacityBody) -> dict:
    patch: dict = {
        "capacity_mbps": body.capacity_mbps,
        "direction": body.direction,
        "capacity_source": "user",
    }
    if "warning_utilization_pct" in body.model_fields_set:
        patch["warning_utilization_pct"] = body.warning_utilization_pct
        patch["high_utilization_pct"] = body.high_utilization_pct
    monitoring_collector.update_config(patch)
    return monitoring_collector.config()


@router.delete("/api/capacity")
async def delete_capacity() -> dict:
    monitoring_collector.update_config({"capacity_mbps": None, "capacity_source": "unknown"})
    return monitoring_collector.config()


@router.put("/api/thresholds")
async def put_thresholds(body: ThresholdBody) -> dict:
    patch = {}
    fields = body.model_fields_set
    for key in ("download_threshold_mbps", "upload_threshold_mbps"):
        if key in fields:
            patch[key] = getattr(body, key)
    if "warning_utilization_pct" in fields:
        patch["warning_utilization_pct"] = body.warning_utilization_pct
        patch["high_utilization_pct"] = body.high_utilization_pct
    if "latency_congestion_ms" in fields:
        patch["latency_congestion_ms"] = body.latency_congestion_ms
    if "loss_congestion_pct" in fields:
        patch["loss_congestion_pct"] = body.loss_congestion_pct
    if not patch:
        raise HTTPException(status_code=400, detail="No threshold fields were provided.")
    config = monitoring_collector.update_config(patch)
    return config | {"effective": monitoring_collector.thresholds()}


@router.get("/api/thresholds")
async def get_thresholds() -> dict:
    """The thresholds the chart and the alert use for the selected profile."""
    return monitoring_collector.thresholds()


@router.get("/api/profiles")
async def get_profiles() -> dict:
    from monitoring.service import profile_summary

    return profile_summary(monitoring_collector, monitoring_collector.selected_name())


@router.put("/api/profiles/{name}/thresholds")
async def put_profile_thresholds(name: str, body: DirectionThresholds) -> dict:
    """Thresholds for one interface profile. Unset fields fall back to the global values."""
    cleaned = _clean_interface(name)
    config = monitoring_collector.config()
    profiles = dict(config.get("profiles") or {})
    entry = dict(profiles.get(cleaned) or {})
    for key in ("download_threshold_mbps", "upload_threshold_mbps"):
        if key in body.model_fields_set:
            value = getattr(body, key)
            if value is None:
                entry.pop(key, None)
            else:
                entry[key] = value
    if entry:
        profiles[cleaned] = entry
    else:
        profiles.pop(cleaned, None)
    monitoring_collector.update_config({"profiles": profiles})
    return monitoring_collector.thresholds(cleaned)


@router.delete("/api/profiles/{name}/thresholds")
async def delete_profile_thresholds(name: str) -> dict:
    cleaned = _clean_interface(name)
    profiles = dict(monitoring_collector.config().get("profiles") or {})
    profiles.pop(cleaned, None)
    monitoring_collector.update_config({"profiles": profiles})
    return monitoring_collector.thresholds(cleaned)


@router.get("/api/diagnostics")
async def diagnostics(refresh: bool = False) -> dict:
    from starlette.concurrency import run_in_threadpool

    from monitoring.diagnostics import build_diagnostics

    return await run_in_threadpool(build_diagnostics, monitoring_collector, force=refresh)


def _alert_rules() -> dict:
    config = monitoring_collector.config()
    samples = int(config.get("alert_clear_samples") or 3)
    ratio = float(config.get("alert_clear_ratio") or 0.9)
    cooldown = float(config.get("alert_cooldown_seconds") or 30)
    return {
        "enter": "A valid rate at or above the saved threshold starts one episode.",
        "recover": f"{samples} valid readings in a row below {ratio:.0%} of the threshold.",
        "clear_ratio": ratio,
        "clear_samples": samples,
        "cooldown_seconds": cooldown,
        "missing_data": "Missing or invalid readings neither start nor end an alert.",
        "baseline_anomaly_enabled": bool(config.get("baseline_anomaly_enabled")),
        "baseline_multiplier": config.get("baseline_multiplier"),
        "baseline_floor_mbps": config.get("baseline_floor_mbps"),
        "baseline_margin_mbps": config.get("baseline_margin_mbps"),
        "attack_claim": "Unusual traffic is not a confirmed cyberattack.",
    }


@router.put("/api/alert-rules")
async def put_alert_rules(body: AlertRulesBody) -> dict:
    patch = {key: getattr(body, key) for key in body.model_fields_set}
    if not patch:
        raise HTTPException(status_code=400, detail="No alert rule fields were provided.")
    monitoring_collector.update_config(patch)
    return _alert_rules()


@router.get("/api/alerts")
async def get_alerts(limit: int = Query(default=50, gt=0, le=500)) -> dict:
    name = monitoring_collector.selected_name()
    return {
        "interface": name,
        "live": monitoring_collector.alert_snapshot(),
        "events": monitoring_collector.store.alert_events(name, limit=limit) if name else [],
        "transitions": monitoring_collector.store.transitions(limit=limit),
        "rules": _alert_rules(),
    }


@router.get("/api/reliability")
async def reliability() -> dict:
    from starlette.concurrency import run_in_threadpool

    from monitoring.reliability import build_reliability_report

    return await run_in_threadpool(
        build_reliability_report,
        monitoring_collector.store,
        monitoring_collector.selected_name(),
    )


@router.get("/api/forecast")
async def forecast(
    method: Literal["moving_average", "exponential_smoothing"] = "exponential_smoothing",
    window: int = Query(default=12, ge=2, le=500),
    alpha: float = Query(default=0.3, gt=0, le=1),
    horizon_seconds: float = Query(default=60, ge=1, le=3600),
) -> dict:
    payload = _dashboard(method, window, alpha, horizon_seconds, 300)
    return payload["forecast"] | {
        "freshness": payload["collection"]["freshness"],
        "interface": payload["collection"]["selected_interface"],
    }


@router.get("/api/forecast/evaluation")
async def forecast_evaluation(
    method: Literal["moving_average", "exponential_smoothing"] = "exponential_smoothing",
    window: int = Query(default=12, ge=2, le=500),
    alpha: float = Query(default=0.3, gt=0, le=1),
    horizon_seconds: float = Query(default=60, ge=1, le=3600),
) -> dict:
    payload = _dashboard(method, window, alpha, horizon_seconds, 300)
    return payload["evaluation"] | {"method": method}


@router.get("/api/congestion")
async def congestion() -> dict:
    payload = _dashboard("exponential_smoothing", 12, 0.3, 60, 300)
    return {
        "assessment": payload["assessment"],
        "probe": payload["probe"],
        "capacity": payload["capacity"],
        "freshness": payload["collection"]["freshness"],
    }

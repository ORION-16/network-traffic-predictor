"""Utilization, alerts, and the distinction between congestion and a traffic spike.

Utilization uses a user-configured capacity only:

    utilization_percent = measured_mbps / configured_capacity_mbps * 100

NIC link speed is never substituted for that capacity. A forecast above
capacity is a predicted demand breach, not proof the link is congested.
A robust outlier in throughput is a statistical spike, not congestion evidence.
"""

from __future__ import annotations

import math

SPIKE_MIN_POINTS = 20
SPIKE_MODIFIED_Z = 3.5


def utilization_percent(throughput_mbps: float | None, capacity_mbps: float | None) -> float | None:
    if throughput_mbps is None or capacity_mbps is None or capacity_mbps <= 0:
        return None
    if throughput_mbps < 0:
        return None
    return throughput_mbps / capacity_mbps * 100


def remaining_mbps(throughput_mbps: float | None, capacity_mbps: float | None) -> float | None:
    if throughput_mbps is None or capacity_mbps is None or capacity_mbps <= 0:
        return None
    return max(0.0, capacity_mbps - throughput_mbps)


def excess_mbps(throughput_mbps: float | None, capacity_mbps: float | None) -> float | None:
    if throughput_mbps is None or capacity_mbps is None or capacity_mbps <= 0:
        return None
    return max(0.0, throughput_mbps - capacity_mbps)


def direction_explanation(direction: str) -> str:
    if direction == "receive_only":
        return "The configured capacity applies to receive throughput only. Transmit utilization is not assessed."
    if direction == "transmit_only":
        return "The configured capacity applies to transmit throughput only. Receive utilization is not assessed."
    return (
        "The configured capacity applies independently to receive and to transmit. "
        "This matches a full-duplex reading of the number the user entered. It is not inferred from the NIC."
    )


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def statistical_spike(values: list[float]) -> dict:
    """Modified z-score against the median absolute deviation.

    A spike means the latest point is unusual relative to recent throughput.
    It is not a congestion finding.
    """
    if len(values) < SPIKE_MIN_POINTS:
        return {
            "status": "insufficient_history",
            "spiked": False,
            "modified_z": None,
            "minimum_points": SPIKE_MIN_POINTS,
            "basis": "measurement",
            "note": "A statistical spike is not assessed until enough valid throughput observations exist.",
        }
    median = _median(values)
    deviations = [abs(value - median) for value in values]
    mad = _median(deviations)
    if mad == 0:
        return {
            "status": "no_variation",
            "spiked": False,
            "modified_z": None,
            "minimum_points": SPIKE_MIN_POINTS,
            "basis": "measurement",
            "note": "The median absolute deviation is zero, so there is no scale for an outlier threshold. This is not a congestion finding.",
        }
    modified_z = 0.6745 * (values[-1] - median) / mad
    spiked = abs(modified_z) > SPIKE_MODIFIED_Z
    return {
        "status": "ok",
        "spiked": spiked,
        "modified_z": modified_z,
        "threshold": SPIKE_MODIFIED_Z,
        "median_mbps": median,
        "latest_mbps": values[-1],
        "basis": "measurement",
        "note": (
            "Modified z-score uses the median and median absolute deviation of recent valid throughput. "
            "A large score is a statistical spike. It is not congestion evidence and it does not show queueing, loss, or a capacity breach."
        ),
    }


def _applies(direction: str, side: str) -> bool:
    if direction == "receive_only":
        return side == "receive"
    if direction == "transmit_only":
        return side == "transmit"
    return True


def assess(
    *,
    current: dict | None,
    forecast_rx: float | None,
    forecast_tx: float | None,
    forecast_sufficient: bool,
    capacity_mbps: float | None,
    capacity_source: str,
    direction: str,
    warning_utilization_pct: float | None,
    high_utilization_pct: float | None,
    freshness: str,
    rx_history: list[float],
    tx_history: list[float],
    probe: dict | None,
    latency_threshold_ms: float | None,
    loss_threshold_pct: float | None,
    previous_signature: str | None,
) -> dict:
    warnings: list[dict] = []

    def add(code: str, severity: str, basis: str, reason: str, **extra: object) -> None:
        warnings.append({"code": code, "severity": severity, "basis": basis, "reason": reason, **extra})

    rates_ready = bool(
        current
        and current.get("quality") == "ok"
        and freshness == "fresh"
    )
    if not rates_ready:
        if freshness == "stale":
            add(
                "stale_data",
                "warning",
                "measurement",
                "The latest stored reading is older than the freshness window. Rates are not treated as live.",
            )
        elif current and current.get("quality") == "baseline":
            add(
                "insufficient_data",
                "info",
                "measurement",
                "The collector has a baseline counter reading and is waiting for the next sample before it can report a rate.",
            )
        else:
            add(
                "insufficient_data",
                "info",
                "measurement",
                "A valid current throughput reading is not available, so utilization and capacity risk are not assessed.",
            )

    if capacity_mbps is None or capacity_source != "user":
        add(
            "unknown_capacity",
            "info",
            "configuration",
            "No user-configured bottleneck capacity is stored. NIC-reported link speed is not used as capacity, so utilization is not calculated.",
        )
    elif rates_ready:
        sides = []
        if _applies(direction, "receive"):
            sides.append(("receive", current.get("rx_mbps"), forecast_rx))
        if _applies(direction, "transmit"):
            sides.append(("transmit", current.get("tx_mbps"), forecast_tx))
        breach = False
        high = False
        elevated = False
        for side, measured, forecast in sides:
            util = utilization_percent(measured, capacity_mbps)
            if forecast_sufficient and forecast is not None and forecast > capacity_mbps:
                breach = True
                add(
                    "predicted_capacity_breach",
                    "warning",
                    "forecast",
                    (
                        f"The {side} level forecast is {forecast:.3f} Mbps, above the configured "
                        f"{capacity_mbps:.3f} Mbps capacity. Forecast demand is not the same as delivered throughput."
                    ),
                    direction=side,
                )
            if util is None or high_utilization_pct is None or warning_utilization_pct is None:
                continue
            if util >= high_utilization_pct:
                high = True
                add(
                    "high_utilization",
                    "warning",
                    "measurement",
                    (
                        f"{side.capitalize()} utilization is {util:.1f}% of the configured capacity, "
                        f"at or above the high threshold of {high_utilization_pct:.1f}%."
                    ),
                    direction=side,
                )
            elif util >= warning_utilization_pct:
                elevated = True
                add(
                    "elevated_utilization",
                    "info",
                    "measurement",
                    (
                        f"{side.capitalize()} utilization is {util:.1f}% of the configured capacity, "
                        f"at or above the warning threshold of {warning_utilization_pct:.1f}%."
                    ),
                    direction=side,
                )
        if warning_utilization_pct is None or high_utilization_pct is None:
            add(
                "thresholds_unset",
                "info",
                "configuration",
                "Capacity is configured, but utilization warning thresholds are not. Utilization is shown without a normal or high label.",
            )
        elif not breach and not high and not elevated:
            add(
                "normal",
                "info",
                "measurement",
                "Measured throughput on the assessed direction is below the configured warning threshold, and the level forecast does not exceed configured capacity.",
            )

    congestion = _congestion(probe, latency_threshold_ms, loss_threshold_pct)
    if congestion["status"] == "evidence":
        add(
            "congestion_evidence",
            "warning",
            "measurement",
            congestion["reason"],
        )
    elif congestion["status"] == "thresholds_unset":
        add(
            "congestion_thresholds_unset",
            "info",
            "configuration",
            "Latency or loss measurements may be present, but congestion thresholds are not configured, so no congestion verdict is made.",
        )

    rx_spike = statistical_spike(rx_history)
    tx_spike = statistical_spike(tx_history)
    if rx_spike.get("spiked") or tx_spike.get("spiked"):
        add(
            "statistical_spike",
            "info",
            "measurement",
            "Recent throughput is unusual relative to its own median and median absolute deviation. This is not congestion evidence.",
        )

    signature = "|".join(sorted(item["code"] + ":" + str(item.get("direction", "")) for item in warnings))
    return {
        "warnings": warnings,
        "condition_changed": signature != previous_signature,
        "signature": signature,
        "congestion": congestion,
        "spikes": {"receive": rx_spike, "transmit": tx_spike},
        "capacity_source": capacity_source if capacity_mbps is not None else "unknown",
    }


def _congestion(probe: dict | None, latency_threshold_ms: float | None, loss_threshold_pct: float | None) -> dict:
    if latency_threshold_ms is None and loss_threshold_pct is None:
        return {
            "status": "thresholds_unset",
            "reason": "Congestion thresholds are not configured.",
            "basis": "configuration",
        }
    if not probe or probe.get("status") not in {"ok", "unreachable"}:
        return {
            "status": "probe_unavailable",
            "reason": "A usable latency or loss probe is not available.",
            "basis": "measurement",
        }
    reasons = []
    if loss_threshold_pct is not None and probe.get("loss_pct") is not None and probe["loss_pct"] >= loss_threshold_pct:
        reasons.append(
            f"ICMP loss on this probe is {probe['loss_pct']:.1f}%, at or above the configured threshold of {loss_threshold_pct:.1f}%."
        )
    if (
        latency_threshold_ms is not None
        and probe.get("rtt_avg_ms") is not None
        and probe["rtt_avg_ms"] >= latency_threshold_ms
    ):
        reasons.append(
            f"Mean ICMP RTT is {probe['rtt_avg_ms']:.2f} ms, at or above the configured threshold of {latency_threshold_ms:.2f} ms."
        )
    if not reasons:
        return {
            "status": "no_evidence",
            "reason": "The latest probe did not cross a configured latency or loss threshold.",
            "basis": "measurement",
        }
    return {
        "status": "evidence",
        "reason": " ".join(reasons) + " This is probe evidence, not a traffic-volume spike.",
        "basis": "measurement",
    }


def utilization_block(current: dict | None, capacity_mbps: float | None, direction: str) -> dict:
    rx = current.get("rx_mbps") if current else None
    tx = current.get("tx_mbps") if current else None
    receive_assessed = _applies(direction, "receive") and capacity_mbps is not None
    transmit_assessed = _applies(direction, "transmit") and capacity_mbps is not None
    return {
        "receive_percent": utilization_percent(rx, capacity_mbps) if receive_assessed else None,
        "transmit_percent": utilization_percent(tx, capacity_mbps) if transmit_assessed else None,
        "receive_remaining_mbps": remaining_mbps(rx, capacity_mbps) if receive_assessed else None,
        "transmit_remaining_mbps": remaining_mbps(tx, capacity_mbps) if transmit_assessed else None,
        "receive_excess_mbps": excess_mbps(rx, capacity_mbps) if receive_assessed else None,
        "transmit_excess_mbps": excess_mbps(tx, capacity_mbps) if transmit_assessed else None,
        "receive_assessed": receive_assessed,
        "transmit_assessed": transmit_assessed,
        "formula": "utilization_percent = measured_mbps / configured_capacity_mbps * 100",
    }


def finite_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number

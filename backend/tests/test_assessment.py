"""Capacity utilization, alerts, and spike labeling."""

from analytics.assessment import assess, statistical_spike, utilization_percent


def test_utilization_formula():
    assert utilization_percent(30, 100) == 30
    assert utilization_percent(85, 100) == 85
    assert utilization_percent(130, 100) == 130


def test_utilization_without_capacity_or_throughput():
    assert utilization_percent(30, None) is None
    assert utilization_percent(None, 100) is None
    assert utilization_percent(10, 0) is None


def test_unknown_capacity_does_not_invent_a_verdict():
    result = assess(
        current={"quality": "ok", "rx_mbps": 85, "tx_mbps": 1},
        forecast_rx=90,
        forecast_tx=1,
        forecast_sufficient=True,
        capacity_mbps=None,
        capacity_source="unknown",
        direction="per_direction",
        warning_utilization_pct=70,
        high_utilization_pct=85,
        freshness="fresh",
        rx_history=[1, 2, 3],
        tx_history=[1, 1, 1],
        probe=None,
        latency_threshold_ms=None,
        loss_threshold_pct=None,
        previous_signature=None,
    )
    codes = {item["code"] for item in result["warnings"]}
    assert "unknown_capacity" in codes
    assert "high_utilization" not in codes
    assert "predicted_capacity_breach" not in codes


def test_high_utilization_and_predicted_breach_are_distinct():
    result = assess(
        current={"quality": "ok", "rx_mbps": 85, "tx_mbps": 10},
        forecast_rx=130,
        forecast_tx=10,
        forecast_sufficient=True,
        capacity_mbps=100,
        capacity_source="user",
        direction="per_direction",
        warning_utilization_pct=70,
        high_utilization_pct=85,
        freshness="fresh",
        rx_history=[],
        tx_history=[],
        probe={"status": "ok", "loss_pct": 0, "rtt_avg_ms": 12},
        latency_threshold_ms=None,
        loss_threshold_pct=None,
        previous_signature=None,
    )
    codes = {item["code"] for item in result["warnings"]}
    assert "high_utilization" in codes
    assert "predicted_capacity_breach" in codes
    breach = next(item for item in result["warnings"] if item["code"] == "predicted_capacity_breach")
    assert breach["basis"] == "forecast"
    high = next(item for item in result["warnings"] if item["code"] == "high_utilization")
    assert high["basis"] == "measurement"


def test_unchanged_condition_is_marked():
    kwargs = dict(
        current={"quality": "ok", "rx_mbps": 10, "tx_mbps": 10},
        forecast_rx=10,
        forecast_tx=10,
        forecast_sufficient=True,
        capacity_mbps=100,
        capacity_source="user",
        direction="per_direction",
        warning_utilization_pct=70,
        high_utilization_pct=85,
        freshness="fresh",
        rx_history=[],
        tx_history=[],
        probe=None,
        latency_threshold_ms=None,
        loss_threshold_pct=None,
    )
    first = assess(previous_signature=None, **kwargs)
    second = assess(previous_signature=first["signature"], **kwargs)
    assert first["condition_changed"] is True
    assert second["condition_changed"] is False
    assert second["warnings"]


def test_congestion_requires_a_threshold():
    result = assess(
        current={"quality": "ok", "rx_mbps": 1, "tx_mbps": 1},
        forecast_rx=None,
        forecast_tx=None,
        forecast_sufficient=False,
        capacity_mbps=100,
        capacity_source="user",
        direction="per_direction",
        warning_utilization_pct=70,
        high_utilization_pct=85,
        freshness="fresh",
        rx_history=[],
        tx_history=[],
        probe={"status": "ok", "loss_pct": 50, "rtt_avg_ms": 400},
        latency_threshold_ms=None,
        loss_threshold_pct=None,
        previous_signature=None,
    )
    codes = {item["code"] for item in result["warnings"]}
    assert "congestion_evidence" not in codes
    assert "congestion_thresholds_unset" in codes


def test_loss_threshold_is_probe_evidence():
    result = assess(
        current={"quality": "ok", "rx_mbps": 1, "tx_mbps": 1},
        forecast_rx=1,
        forecast_tx=1,
        forecast_sufficient=True,
        capacity_mbps=100,
        capacity_source="user",
        direction="per_direction",
        warning_utilization_pct=70,
        high_utilization_pct=85,
        freshness="fresh",
        rx_history=[],
        tx_history=[],
        probe={"status": "ok", "loss_pct": 20, "rtt_avg_ms": 15},
        latency_threshold_ms=100,
        loss_threshold_pct=5,
        previous_signature=None,
    )
    evidence = next(item for item in result["warnings"] if item["code"] == "congestion_evidence")
    assert evidence["basis"] == "measurement"
    assert "ICMP loss" in evidence["reason"]


def test_spike_is_not_reported_as_congestion_and_needs_history():
    short = statistical_spike([1, 2, 3])
    assert short["status"] == "insufficient_history"
    assert short["spiked"] is False
    values = [10, 11, 9, 10.5, 9.5, 10.2, 9.8, 11.2, 10.1, 9.7] * 2 + [80]
    spike = statistical_spike(values)
    assert spike["spiked"] is True
    assert "not" in spike["note"] and "congestion" in spike["note"]


def test_nic_speed_is_not_a_capacity_source():
    result = assess(
        current={"quality": "ok", "rx_mbps": 50, "tx_mbps": 1},
        forecast_rx=50,
        forecast_tx=1,
        forecast_sufficient=True,
        capacity_mbps=1201,
        capacity_source="reported_link_speed",
        direction="per_direction",
        warning_utilization_pct=70,
        high_utilization_pct=85,
        freshness="fresh",
        rx_history=[],
        tx_history=[],
        probe=None,
        latency_threshold_ms=None,
        loss_threshold_pct=None,
        previous_signature=None,
    )
    assert "unknown_capacity" in {item["code"] for item in result["warnings"]}

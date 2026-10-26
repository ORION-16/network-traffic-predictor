"""Measurements from this computer's selected interface.

Nothing in this module fabricates counters, latency, or accuracy. If a probe
or a forecast cannot be produced, the test records that state.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from pathlib import Path

from analytics.forecasting import Point, forecast_direction
from monitoring.collector import Collector, read_counters
from monitoring.interfaces import discover_interfaces, preferred_interface_name
from monitoring.probe import run_probe
from monitoring.rates import bytes_to_mbps, compute_rate
from monitoring.service import build_dashboard
from monitoring.store import Store


def _ordinary_fetch() -> str:
    try:
        with urllib.request.urlopen("https://example.com", timeout=5) as response:
            response.read(256)
        return "completed"
    except Exception as exc:
        return f"{type(exc).__name__}"


def test_real_interface_collection_forecast_and_probe(tmp_path, capsys):
    records = discover_interfaces()
    preferred = preferred_interface_name(records)
    assert preferred, "No up non-loopback interface owns the default IPv4 route."
    selected = next(record for record in records if record.name == preferred)
    assert selected.is_loopback is False

    before = read_counters(preferred)
    assert before is not None
    fetch_status = _ordinary_fetch()
    time.sleep(1.2)
    after = read_counters(preferred)
    assert after is not None
    assert after.rx_bytes >= before.rx_bytes
    assert after.tx_bytes >= before.tx_bytes
    delta = compute_rate(before, after, max_elapsed_seconds=15)
    assert delta.quality == "ok"
    assert delta.rx_mbps == bytes_to_mbps(after.rx_bytes - before.rx_bytes, delta.elapsed_seconds)
    assert delta.tx_mbps == bytes_to_mbps(after.tx_bytes - before.tx_bytes, delta.elapsed_seconds)

    probe_holder: dict = {}

    def _probe() -> None:
        probe_holder["result"] = run_probe("1.1.1.1", 3)

    probe_thread = threading.Thread(target=_probe)
    probe_thread.start()

    store = Store(tmp_path / "real.sqlite")
    collector = Collector(store, interval=1.0)
    started = time.time()
    collector.start()
    try:
        time.sleep(22)
    finally:
        collector.stop()
        probe_thread.join(timeout=20)
    stopped = time.time()

    rows = store.history(preferred, start=started - 1, end=stopped + 1, limit=5000)
    assert rows, "The collector stored no readings."
    assert all(row["source"] == "psutil.net_io_counters" for row in rows)
    assert all(row["interface_name"] == preferred for row in rows)
    ok_rows = [row for row in rows if row["quality"] == "ok"]
    for previous, row in zip(rows, rows[1:]):
        if row["quality"] != "ok" or row["interval_seconds"] is None:
            continue
        if previous["rx_bytes"] is None or row["rx_bytes"] is None:
            continue
        if row["rx_bytes"] < previous["rx_bytes"]:
            assert row["quality"] == "counter_reset"
            continue
        expected = bytes_to_mbps(row["rx_bytes"] - previous["rx_bytes"], row["interval_seconds"])
        assert row["rx_mbps"] == expected

    points = [
        Point(row["sampled_at"], row["rx_mbps"], row["interval_seconds"])
        for row in ok_rows
        if row["rx_mbps"] is not None
    ]
    forecast = forecast_direction(
        points,
        method="exponential_smoothing",
        window=12,
        alpha=0.3,
        sample_interval=1.0,
        horizon_seconds=60,
    )
    dashboard = build_dashboard(collector, method="exponential_smoothing", window=12, alpha=0.3, horizon_seconds=60)
    assert dashboard["capacity"]["source"] == "unknown"
    assert any(item["code"] == "unknown_capacity" for item in dashboard["assessment"]["warnings"])
    assert dashboard["scope"] == "local_machine_interface"

    probe = probe_holder.get("result", {})
    if probe.get("status") == "ok":
        assert probe.get("rtt_avg_ms") is not None or probe.get("rtt_status") == "below_1ms"
        assert probe.get("loss_pct") is not None
    elif probe.get("status") == "unreachable":
        assert probe.get("rtt_avg_ms") is None
    else:
        assert probe.get("status") in {"failed", "unsupported", "parse_failed", "disabled"}
        assert probe.get("loss_pct") is None or probe.get("status") == "failed"

    summary = {
        "started_at": started,
        "stopped_at": stopped,
        "platform": selected.kind and dashboard["platform"],
        "interface": preferred,
        "kind": selected.kind,
        "kind_source": selected.kind_source,
        "medium": selected.medium,
        "is_default_route": selected.is_default_route,
        "reported_link_speed_mbps": selected.reported_link_speed_mbps,
        "link_speed_status": selected.link_speed_status,
        "os_link_speed_text": selected.os_link_speed_text,
        "reported_duplex": selected.reported_duplex,
        "fetch": fetch_status,
        "manual_elapsed_seconds": delta.elapsed_seconds,
        "manual_rx_mbps": delta.rx_mbps,
        "manual_tx_mbps": delta.tx_mbps,
        "manual_rx_byte_delta": None if after.rx_bytes is None or before.rx_bytes is None else after.rx_bytes - before.rx_bytes,
        "manual_tx_byte_delta": None if after.tx_bytes is None or before.tx_bytes is None else after.tx_bytes - before.tx_bytes,
        "manual_rx_packets_delta": None
        if after.rx_packets is None or before.rx_packets is None
        else after.rx_packets - before.rx_packets,
        "stored_rows": len(rows),
        "valid_rate_rows": len(ok_rows),
        "forecast_status": forecast["status"],
        "forecast_observations": forecast["observations_used"],
        "forecast_point_rx_mbps": forecast["point_mbps"],
        "evaluation_status": forecast["evaluation"]["status"],
        "evaluation_origins": forecast["evaluation"]["paired_origins"],
        "evaluation_methods": forecast["evaluation"]["methods"],
        "interval_status": forecast["evaluation"]["interval_status"],
        "horizon_evaluation": forecast["evaluation"]["horizon_evaluation"],
        "probe_status": probe.get("status"),
        "probe_target": probe.get("target"),
        "probe_sent": probe.get("sent"),
        "probe_received": probe.get("received"),
        "probe_loss_pct": probe.get("loss_pct"),
        "probe_rtt_avg_ms": probe.get("rtt_avg_ms"),
        "probe_jitter_ms": probe.get("jitter_ms"),
        "probe_error": probe.get("error"),
        "capacity_source": dashboard["capacity"]["source"],
    }
    text = "REAL_NETWORK_RESULT " + json.dumps(summary, default=str)
    print(text)
    result_path = Path(__file__).resolve().parents[1] / "data" / "last-real-network-result.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    captured = capsys.readouterr()
    assert "REAL_NETWORK_RESULT" in captured.out

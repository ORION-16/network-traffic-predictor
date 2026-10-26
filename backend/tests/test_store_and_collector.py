"""Storage, collector restart, and stale or missing interface behavior."""

from __future__ import annotations

import time

from monitoring.collector import Collector, read_counters
from monitoring.interfaces import classify_interface, discover_interfaces, parse_link_speed_text, preferred_interface_name
from monitoring.rates import Counters
from monitoring.store import Store


def test_store_round_trip_duplicate_and_retention(tmp_path):
    store = Store(tmp_path / "obs.sqlite")
    store.init()
    row = {
        "sampled_at": 1_000.0,
        "interval_seconds": 1.0,
        "interface_name": "eth-test",
        "rx_bytes": 10,
        "tx_bytes": 20,
        "rx_mbps": 1.5,
        "tx_mbps": 0.5,
        "valid": True,
        "quality": "ok",
        "source": "psutil.net_io_counters",
        "platform": "test",
        "note": "",
    }
    assert store.insert_observation(row) is True
    assert store.insert_observation(row) is False
    assert store.count_observations("eth-test") == 1
    old = dict(row, sampled_at=10.0)
    assert store.insert_observation(old) is True
    removed = store.prune(retention_seconds=50, now=1_000.0)
    assert removed == 1
    assert store.count_observations("eth-test") == 1
    history = store.history("eth-test", start=0, end=2_000)
    assert len(history) == 1
    assert history[0]["rx_mbps"] == 1.5


def test_config_survives_reopen(tmp_path):
    path = tmp_path / "obs.sqlite"
    store = Store(path)
    store.init()
    store.update_config({"capacity_mbps": 100, "capacity_source": "user", "monitor_interface": "Wi-Fi"})
    again = Store(path)
    again.init()
    config = again.get_config()
    assert config["capacity_mbps"] == 100
    assert config["capacity_source"] == "user"
    assert config["monitor_interface"] == "Wi-Fi"


def test_classify_windows_metadata_and_heuristics():
    kind, source, medium = classify_interface(
        "Wi-Fi",
        "MediaTek Wi-Fi 6E",
        virtual=False,
        hardware=True,
        media_type="Native 802.11",
    )
    assert kind == "physical"
    assert source == "windows_adapter"
    assert medium == "wifi"

    kind, _, _ = classify_interface(
        "Ethernet 2",
        "VirtualBox Host-Only Ethernet Adapter",
        virtual=True,
        hardware=False,
        media_type="802.3",
    )
    assert kind == "virtual"

    kind, _, medium = classify_interface("Loopback Pseudo-Interface 1", "")
    assert kind == "loopback"
    assert medium == "loopback"

    kind, source, _ = classify_interface("utun0", "")
    assert kind == "vpn"
    assert source == "name_heuristic"


def test_link_speed_text_parser_does_not_treat_zero_as_capacity():
    assert parse_link_speed_text("1.2 Gbps") == 1200
    assert parse_link_speed_text("0 bps") is None
    assert parse_link_speed_text("") is None


def test_collector_restart_keeps_history_and_resets_rate(tmp_path, monkeypatch):
    store = Store(tmp_path / "obs.sqlite")
    store.init()
    samples = [
        Counters(1, 100, 1000, 1000, 10, 10, 0, 0, 0, 0),
        Counters(2, 101, 126_000, 1000, 20, 10, 0, 0, 0, 0),
    ]

    def fake_read(name: str):
        assert name == "eth-test"
        return samples.pop(0)

    monkeypatch.setattr("monitoring.collector.read_counters", fake_read)
    monkeypatch.setattr(
        "monitoring.collector.discover_interfaces",
        lambda: [],
    )
    collector = Collector(store, interval=1.0)
    store.update_config({"monitor_interface": "eth-test"})
    first = collector.sample_once()
    second = collector.sample_once()
    assert first["quality"] == "baseline"
    assert first["rx_mbps"] is None
    assert second["quality"] == "ok"
    assert second["rx_mbps"] == (125_000 * 8) / 1 / 1_000_000

    restarted = Collector(store, interval=1.0)
    samples.append(Counters(5, 200, 2_000_000, 1000, 30, 10, 0, 0, 0, 0))
    baseline = restarted.sample_once()
    assert baseline["quality"] == "baseline"
    assert baseline["rx_mbps"] is None
    assert store.count_observations("eth-test") == 3


def test_two_valid_samples_record_a_forecast(tmp_path, monkeypatch):
    store = Store(tmp_path / "obs.sqlite")
    store.init()
    samples = [
        Counters(1, 100, 1000, 1000, 10, 10, 0, 0, 0, 0),
        Counters(2, 101, 126_000, 1000, 20, 10, 0, 0, 0, 0),
        Counters(3, 102, 251_000, 1000, 30, 10, 0, 0, 0, 0),
    ]
    monkeypatch.setattr("monitoring.collector.read_counters", lambda name: samples.pop(0))
    monkeypatch.setattr("monitoring.collector.discover_interfaces", lambda: [])
    collector = Collector(store, interval=1.0)
    store.update_config({"monitor_interface": "eth-test"})
    assert collector.sample_once()["quality"] == "baseline"
    assert collector.sample_once()["quality"] == "ok"
    assert collector.sample_once()["quality"] == "ok"
    saved = store.forecast_rows("eth-test")
    assert saved
    assert {row["method"] for row in saved} >= {"persistence", "exponential_smoothing"}


def test_missing_interface_does_not_store_zero(tmp_path, monkeypatch):
    store = Store(tmp_path / "obs.sqlite")
    store.init()
    store.update_config({"monitor_interface": "missing0"})
    monkeypatch.setattr("monitoring.collector.read_counters", lambda name: None)
    monkeypatch.setattr("monitoring.collector.discover_interfaces", lambda: [])
    collector = Collector(store, interval=1.0)
    assert collector.sample_once() is None
    assert collector.status == "interface_unavailable"
    assert store.count_observations("missing0") == 0


def test_live_discovery_prefers_default_route_over_loopback():
    records = discover_interfaces()
    assert records
    preferred = preferred_interface_name(records)
    assert preferred
    selected = next(record for record in records if record.name == preferred)
    assert selected.is_loopback is False
    assert selected.is_default_route is True
    assert selected.kind != "loopback"
    counters = read_counters(preferred)
    assert counters is not None
    assert counters.rx_bytes is not None
    assert counters.tx_bytes is not None
    # A counter value of zero is only acceptable when the OS actually returned zero.
    assert isinstance(counters.rx_bytes, int)
    _ = time.time()

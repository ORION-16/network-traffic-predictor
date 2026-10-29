"""Baseline anomalies, episode restart, invalid counters, and measured probes.

The series and counter sequences are fixtures. The SQLite and retention timings
come from this process.
"""

from __future__ import annotations

import sqlite3

from analytics.baseline_anomaly import BaselineAnomalyTracker, BaselineConfig
from analytics.threshold_alert import RecoveryRules
from analytics.walk_forward import evaluate_runs, split_runs
from monitoring.collector import Collector
from monitoring.rates import Counters
from monitoring.reliability import build_reliability_report, controlled_counter_cases
from monitoring.store import Store


def _rows(values, *, start=1_000.0):
    return [
        {
            "sampled_at": start + index,
            "interval_seconds": 1.0,
            "quality": "ok",
            "rx_mbps": value,
            "tx_mbps": 0.2,
        }
        for index, value in enumerate(values)
    ]


def test_mape_is_reported_for_a_burst_and_withheld_near_zero():
    quiet = evaluate_runs(split_runs(_rows([0.01] * 80), 1.0), "rx_mbps", horizon_seconds=1, sample_interval=1.0)
    assert quiet["methods"]["persistence"]["mape_status"] == "not_reported_near_zero_actuals"
    assert quiet["methods"]["persistence"]["mape"] is None
    stable = evaluate_runs(split_runs(_rows([1.0] * 80), 1.0), "rx_mbps", horizon_seconds=1, sample_interval=1.0)
    assert stable["methods"]["persistence"]["mape_status"] == "reported"
    bursty = [0.4] * 80 + [40.0] * 20
    report = evaluate_runs(split_runs(_rows(bursty), 1.0), "rx_mbps", horizon_seconds=1, sample_interval=1.0)
    assert report["burst"]["persistence"]["n"] > 0
    assert report["burst"]["persistence"]["mape_status"] == "reported"
    assert report["quiet_best_baseline"] in {"persistence", "moving_average", "exponential_smoothing"}
    assert report["burst_best_baseline"] in {"persistence", "moving_average", "exponential_smoothing"}


def _baseline(values, *, enabled=True):
    tracker = BaselineAnomalyTracker()
    rules = RecoveryRules()
    config = BaselineConfig(enabled=enabled)
    changes = []
    for index, value in enumerate(values):
        changes.extend(
            tracker.update(
                sampled_at=float(index),
                valid=value is not None,
                values={"receive": value, "transmit": 1.0},
                config=config,
                rules=rules,
            )
        )
    return tracker, changes


def test_normal_traffic_is_not_a_baseline_anomaly():
    tracker, changes = _baseline([2.0, 3.0, 4.0, 5.0] * 10)
    assert [item.kind for item in changes if item.kind == "started"] == []
    assert tracker.snapshot(RecoveryRules())["receive"]["active"] is False


def test_a_sustained_spike_is_one_episode_and_a_short_one_recovers():
    tracker, changes = _baseline([3.0] * 12 + [40.0] * 60)
    starts = [item for item in changes if item.kind == "started"]
    assert len(starts) == 1
    assert starts[0].side == "receive"
    assert tracker.sides["receive"].active is True
    assert tracker.sides["receive"].baseline_mbps == 3.0
    assert tracker.sides["receive"].episodes == 1

    short, short_changes = _baseline([3.0] * 12 + [40.0, 2.0, 2.0, 2.0])
    assert [item.kind for item in short_changes][0] == "started"
    assert short_changes[-1].kind == "recovered"
    assert short.sides["receive"].active is False


def test_missing_samples_do_not_end_a_baseline_episode():
    tracker = BaselineAnomalyTracker()
    config = BaselineConfig(enabled=True)
    rules = RecoveryRules()
    values = [3.0] * 12 + [40.0, None, None, 40.0]
    changes = []
    for index, value in enumerate(values):
        changes.extend(
            tracker.update(
                sampled_at=float(index),
                valid=value is not None,
                values={"receive": value, "transmit": 1.0},
                config=config,
                rules=rules,
            )
        )
    assert [item.kind for item in changes] == ["started"]
    assert tracker.sides["receive"].active is True


def test_repeated_crossings_reuse_an_episode_inside_the_cooldown():
    values = [3.0] * 12 + [40.0, 2.0, 2.0, 2.0, 40.0]
    _, changes = _baseline(values)
    assert [item.kind for item in changes if item.side == "receive" and item.kind in {"started", "reopened", "recovered"}] == [
        "started",
        "recovered",
        "reopened",
    ]


def test_restart_continues_the_open_threshold_episode(tmp_path, monkeypatch):
    store = Store(tmp_path / "obs.sqlite")
    store.init()
    store.update_config({"monitor_interface": "eth-test", "download_threshold_mbps": 1.0})
    samples = [
        Counters(1, 100, 1_000, 1_000, 1, 1, 0, 0, 0, 0),
        Counters(2, 101, 126_000, 1_000, 2, 1, 0, 0, 0, 0),
    ]
    monkeypatch.setattr("monitoring.collector.read_counters", lambda name: samples.pop(0))
    monkeypatch.setattr("monitoring.collector.discover_interfaces", lambda: [])
    collector = Collector(store, interval=1.0)
    assert collector.sample_once()["quality"] == "baseline"
    assert collector.sample_once()["rx_mbps"] == 1.0
    events = store.alert_events("eth-test")
    assert len(events) == 1
    assert events[0]["end_reason"] is None

    restarted = Collector(store, interval=1.0)
    samples.append(Counters(3, 102, 251_000, 1_000, 3, 1, 0, 0, 0, 0))
    assert restarted.sample_once()["quality"] == "baseline"
    # The new process has no previous counters, so this reading is a baseline and must not open another episode.
    assert len(store.alert_events("eth-test")) == 1

    samples.append(Counters(4, 103, 376_000, 1_000, 4, 1, 0, 0, 0, 0))
    again = restarted.sample_once()
    assert again["rx_mbps"] == 1.0
    events = store.alert_events("eth-test")
    assert len(events) == 1
    assert events[0]["duration_seconds"] >= 0
    assert events[0]["attack_claim"] == "not_confirmed"


def test_sqlite_write_failure_does_not_store_a_zero(tmp_path, monkeypatch):
    store = Store(tmp_path / "obs.sqlite")
    store.init()
    store.update_config({"monitor_interface": "eth-test"})
    monkeypatch.setattr("monitoring.collector.discover_interfaces", lambda: [])
    monkeypatch.setattr(
        "monitoring.collector.read_counters",
        lambda name: Counters(1, 100, 1_000, 1_000, 1, 1, 0, 0, 0, 0),
    )
    real_insert = store.insert_observation

    def fail_once(row):
        fail_once.calls += 1
        if fail_once.calls == 1:
            raise sqlite3.OperationalError("disk full")
        return real_insert(row)

    fail_once.calls = 0
    monkeypatch.setattr(store, "insert_observation", fail_once)
    collector = Collector(store, interval=1.0)
    assert collector.sample_once() is None
    assert collector.status == "error"
    assert "zero-traffic" in (collector.health()["error"] or "")
    assert store.count_observations("eth-test") == 0
    saved = collector.sample_once()
    assert saved["quality"] == "baseline"
    assert saved["rx_mbps"] is None
    assert store.count_observations("eth-test") == 1


def test_controlled_cases_do_not_turn_invalid_counters_into_rates():
    cases = {item["case"]: item for item in controlled_counter_cases()}
    assert cases["one_second"]["quality"] == "ok"
    assert cases["one_second"]["rx_mbps"] == 1.0
    assert cases["unchanged_counters"]["rx_mbps"] == 0.0
    for name in ("short_elapsed", "long_gap", "counter_reset", "interface_change", "missing_counter"):
        assert cases[name]["rx_mbps"] is None
        assert cases[name]["valid"] is False


def test_reliability_report_measures_a_temporary_database(tmp_path):
    store = Store(tmp_path / "live.sqlite")
    store.init()
    report = build_reliability_report(store, None)
    assert report["sqlite_write"]["rows_written"] == 200
    assert report["sqlite_write"]["median_write_ms"] >= 0
    assert report["retention"]["expired_row_removed"] is True
    assert report["retention"]["rows_kept"] == 1
    assert report["process"]["rss_bytes"] > 0
    assert "saturated" in report["limitations"]

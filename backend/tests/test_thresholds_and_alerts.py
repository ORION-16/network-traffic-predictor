"""Thresholds, the threshold alert state machine, and their API.

All series here are deterministic fixtures, not live measurements.
"""

from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient

from analytics.rise_alert import build_rise_alert
from analytics.threshold_alert import CLEAR_SAMPLES, COOLDOWN_SECONDS, ThresholdAlertTracker
from analytics.thresholds import compare, effective_thresholds, validate_threshold
from monitoring.collector import Collector
from monitoring.rates import Counters
from monitoring.store import DEFAULT_CONFIG, Store


def _config(**overrides) -> dict:
    config = dict(DEFAULT_CONFIG)
    config.update(overrides)
    return config


def test_legacy_capacity_maps_to_each_direction_by_mode():
    both = effective_thresholds(_config(capacity_mbps=1.0, capacity_source="user"), "Wi-Fi")
    assert both["receive"] == 1.0 and both["transmit"] == 1.0
    assert both["sources"] == {"receive": "capacity", "transmit": "capacity"}
    down = effective_thresholds(
        _config(capacity_mbps=5.0, capacity_source="user", direction="receive_only"), "Wi-Fi"
    )
    assert down["receive"] == 5.0 and down["transmit"] is None
    unknown = effective_thresholds(_config(capacity_mbps=5.0, capacity_source="unknown"), "Wi-Fi")
    assert unknown["configured"] is False


def test_separate_and_per_profile_thresholds_take_priority():
    config = _config(
        capacity_mbps=1.0,
        capacity_source="user",
        download_threshold_mbps=20.0,
        upload_threshold_mbps=4.0,
        profiles={"Ethernet": {"download_threshold_mbps": 80.0}},
    )
    wifi = effective_thresholds(config, "Wi-Fi")
    assert (wifi["receive"], wifi["transmit"]) == (20.0, 4.0)
    assert wifi["sources"] == {"receive": "global", "transmit": "global"}
    wired = effective_thresholds(config, "Ethernet")
    assert (wired["receive"], wired["transmit"]) == (80.0, 4.0)
    assert wired["sources"]["receive"] == "profile"


@pytest.mark.parametrize("bad", [0, -1, math.nan, math.inf, "fast", True, 2_000_000])
def test_invalid_threshold_values_are_rejected(bad):
    with pytest.raises(ValueError):
        validate_threshold(bad)
    resolved = effective_thresholds(_config(download_threshold_mbps=bad), "Wi-Fi")
    assert resolved["receive"] is None


def test_compare_below_equal_above():
    assert compare(0.99, 1.0) == "below"
    assert compare(1.0, 1.0) == "equal"
    assert compare(1.01, 1.0) == "above"
    assert compare(None, 1.0) == "missing"
    assert compare(3.0, None) == "no_threshold"


def _feed(tracker: ThresholdAlertTracker, values: list[float | None], *, start: float = 0.0, threshold: float = 1.0):
    changes = []
    for index, value in enumerate(values):
        changes.extend(
            tracker.update(
                sampled_at=start + index,
                valid=value is not None,
                values={"receive": value, "transmit": 0.1},
                thresholds={"receive": threshold, "transmit": threshold},
            )
        )
    return changes


def test_below_threshold_never_alerts():
    tracker = ThresholdAlertTracker()
    assert _feed(tracker, [0.2, 0.5, 0.99, 0.999]) == []
    assert tracker.snapshot()["receive"]["active"] is False


def test_equal_and_above_threshold_alert_and_name_the_direction():
    tracker = ThresholdAlertTracker()
    changes = _feed(tracker, [0.2, 1.0])
    assert [(item.side, item.kind) for item in changes] == [("receive", "started")]
    snap = tracker.snapshot()
    assert snap["receive"]["active"] is True
    assert snap["receive"]["label"] == "download"
    assert snap["transmit"]["active"] is False


def test_recovery_needs_consecutive_readings_below_ninety_percent():
    tracker = ThresholdAlertTracker()
    _feed(tracker, [2.0])
    hover = _feed(tracker, [0.95, 0.95, 0.95, 0.95], start=1)
    assert all(item.kind != "recovered" for item in hover)
    assert tracker.snapshot()["receive"]["active"] is True
    interrupted = _feed(tracker, [0.5, 0.5, 0.95], start=7)
    assert all(item.kind != "recovered" for item in interrupted)
    assert tracker.snapshot()["receive"]["recovery_progress"] == f"0/{CLEAR_SAMPLES}"
    done = _feed(tracker, [0.5] * CLEAR_SAMPLES, start=10)
    assert [item.kind for item in done] == ["recovered"]
    snap = tracker.snapshot()["receive"]
    assert snap["active"] is False
    assert snap["last_recovery_at"] == 10 + CLEAR_SAMPLES - 1
    assert snap["last_alert_at"] == 0


def test_missing_readings_neither_start_nor_end_an_alert():
    tracker = ThresholdAlertTracker()
    assert _feed(tracker, [None, None]) == []
    _feed(tracker, [3.0], start=2)
    held = _feed(tracker, [None] * 10, start=3)
    assert held == []
    assert tracker.snapshot()["receive"]["active"] is True
    assert tracker.snapshot()["receive"]["latest_mbps"] is None


def test_reentry_inside_cooldown_is_the_same_episode():
    tracker = ThresholdAlertTracker()
    _feed(tracker, [2.0, 0.1, 0.1, 0.1])
    assert tracker.snapshot()["receive"]["episodes"] == 1
    again = _feed(tracker, [2.0], start=10)
    assert [item.kind for item in again] == ["reopened"]
    assert tracker.snapshot()["receive"]["episodes"] == 1
    _feed(tracker, [0.1, 0.1, 0.1], start=11)
    later = _feed(tracker, [2.0], start=13 + COOLDOWN_SECONDS + 1)
    assert [item.kind for item in later] == ["started"]
    assert tracker.snapshot()["receive"]["episodes"] == 2


def test_removing_the_threshold_clears_without_a_recovery():
    tracker = ThresholdAlertTracker()
    _feed(tracker, [5.0])
    changes = tracker.update(sampled_at=1, valid=True, values={"receive": 5.0, "transmit": 0.1}, thresholds={})
    assert [item.kind for item in changes] == ["cleared"]
    assert tracker.snapshot()["receive"]["last_recovery_at"] is None


def _alert(live: dict | None, *, history_points: int = 60, fresh: bool = True, quality: str = "ok", freshness: str = "fresh"):
    quiet = {"rising": False}
    return build_rise_alert(
        fresh=fresh,
        quality=quality,
        sampled_at=100.0,
        direction="per_direction",
        receive_rise=quiet,
        transmit_rise=quiet,
        capacity_mbps=1.0,
        capacity_source="user",
        threshold_alert={"live": live} if live is not None else None,
        thresholds={"receive": 1.0, "transmit": 1.0},
        history_points=history_points,
        freshness=freshness,
    )


def test_above_threshold_is_never_reported_as_normal():
    tracker = ThresholdAlertTracker()
    _feed(tracker, [0.2, 4.2])
    alert = _alert(tracker.snapshot())
    assert alert["state"] == "threshold_exceeded"
    assert alert["directions"] == ["receive"]
    assert "Download is at 4.20 Mbps" in alert["explanation"]
    assert alert["sampled_at"] == 100.0


def test_short_history_and_stale_data_states():
    assert _alert(ThresholdAlertTracker().snapshot(), history_points=4)["state"] == "insufficient_history"
    stale = _alert(None, fresh=False, freshness="stale")
    assert stale["state"] == "unavailable"
    assert "too old" in stale["explanation"]
    gap = _alert(None, quality="gap", fresh=True, freshness="fresh")
    assert gap["state"] == "unavailable"
    assert _alert(ThresholdAlertTracker().snapshot())["state"] == "normal"


def test_collector_records_one_episode_and_isolates_profiles(tmp_path, monkeypatch):
    store = Store(tmp_path / "obs.sqlite")
    store.init()
    store.update_config(
        {"monitor_interface": "eth-test", "download_threshold_mbps": 1.0, "upload_threshold_mbps": 50.0}
    )
    # rx deltas in bytes per 1 s: 2 Mbps, 2 Mbps, 0.1 Mbps x3.
    rx = [0, 250_000, 500_000, 512_500, 525_000, 537_500]
    samples = [Counters(index + 1, 100 + index, value, 1000, 0, 0, 0, 0, 0, 0) for index, value in enumerate(rx)]
    monkeypatch.setattr("monitoring.collector.read_counters", lambda name: samples.pop(0))
    monkeypatch.setattr("monitoring.collector.discover_interfaces", lambda: [])
    collector = Collector(store, interval=1.0)
    for _ in range(len(rx)):
        collector.sample_once()
    events = store.alert_events("eth-test")
    assert len(events) == 1
    event = events[0]
    assert event["direction"] == "receive"
    assert event["threshold_mbps"] == 1.0
    assert event["end_reason"] == "recovered"
    assert event["peak_mbps"] == pytest.approx(2.0)
    assert store.alert_events("other-nic") == []
    assert collector.alert_snapshot()["live"]["transmit"]["active"] is False


def test_threshold_api_validates_and_matches_the_alert():
    with TestClient(__import__("app.main", fromlist=["app"]).app) as client:
        assert client.put("/api/thresholds", json={"download_threshold_mbps": 0}).status_code == 422
        assert client.put("/api/thresholds", json={"upload_threshold_mbps": -2}).status_code == 422
        assert client.put("/api/thresholds", json={"download_threshold_mbps": "x"}).status_code == 422
        saved = client.put("/api/thresholds", json={"download_threshold_mbps": 12.5, "upload_threshold_mbps": 3})
        assert saved.status_code == 200
        effective = saved.json()["effective"]
        assert (effective["receive"], effective["transmit"]) == (12.5, 3.0)
        payload = client.get("/api/monitoring/dashboard").json()
        assert payload["thresholds"]["receive"] == 12.5
        assert payload["rise_alert"]["thresholds_mbps"] == {"receive": 12.5, "transmit": 3.0}
        name = payload["collection"]["selected_interface"]
        if name:
            profile = client.put(f"/api/profiles/{name}/thresholds", json={"download_threshold_mbps": 40})
            assert profile.status_code == 200
            assert profile.json()["receive"] == 40
            assert client.get("/api/thresholds").json()["receive"] == 40
            assert client.delete(f"/api/profiles/{name}/thresholds").json()["receive"] == 12.5
        cleared = client.put("/api/thresholds", json={"download_threshold_mbps": None, "upload_threshold_mbps": None})
        assert cleared.status_code == 200
        assert client.get("/api/alerts").status_code == 200
        assert client.get("/api/profiles").json()["note"].startswith("A profile is one interface")

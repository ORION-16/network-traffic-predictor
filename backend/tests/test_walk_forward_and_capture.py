"""Walk-forward horizons, sampling schedule, and packet capture with mocks.

Series and packets here are deterministic fixtures, not live measurements.
"""

from __future__ import annotations

import threading
import time

import pytest

from analytics.walk_forward import evaluate_history, evaluate_runs, holt_justified, split_runs
from capture import packet_rates
from capture.packet_rates import PacketRateMeter, probe_capture
from monitoring.collector import next_deadline


def _rows(values: list[float], *, start: float = 1_000.0, interval: float = 1.0, quality: str = "ok") -> list[dict]:
    return [
        {
            "sampled_at": start + index * interval,
            "interval_seconds": interval,
            "quality": quality,
            "rx_mbps": value,
            "tx_mbps": 0.1,
        }
        for index, value in enumerate(values)
    ]


def test_a_delayed_valid_sample_stays_in_the_run_and_a_long_gap_does_not():
    rows = []
    clock = 1_000.0
    for index in range(420):
        gap = 6.0 if index in {40, 80, 120} else 1.0
        clock += gap
        rows.append(
            {
                "sampled_at": clock,
                "interval_seconds": gap,
                "quality": "ok",
                "rx_mbps": 1.0,
                "tx_mbps": 0.2,
            }
        )
    rows.append({"sampled_at": clock + 35, "interval_seconds": 35, "quality": "gap", "rx_mbps": None, "tx_mbps": None})
    rows.extend(_rows([1.0] * 30, start=clock + 36))
    runs = split_runs(rows, 1.0)
    assert len(runs) == 2
    scored = evaluate_runs(runs[:1], "rx_mbps", horizon_seconds=300, sample_interval=1.0)
    assert scored["methods"]["persistence"]["n"] > 0
    assert scored["score_status"] == "evaluated"
    short = evaluate_runs(runs[:1], "rx_mbps", horizon_seconds=900, sample_interval=1.0)
    assert short["methods"]["persistence"]["n"] == 0
    assert short["methods"]["persistence"]["mae"] is None
    assert short["score_status"] == "insufficient_history"
    assert "left blank" in short["reason"]


def test_runs_split_at_gaps_and_invalid_rows():
    rows = _rows([0.2] * 30) + _rows([0.2] * 30, start=1_100.0)
    rows.insert(10, {"sampled_at": 1_010.5, "interval_seconds": None, "quality": "baseline", "rx_mbps": None, "tx_mbps": None})
    runs = split_runs(rows, 1.0)
    # The baseline at 1010.5 ends the first run after 1010 and the next run starts at 1011.
    assert [len(run) for run in runs] == [11, 19, 30]


def test_sixty_second_horizon_scores_only_targets_inside_the_run():
    rows = _rows([float(index % 5) for index in range(100)])
    report = evaluate_runs(split_runs(rows, 1.0), "rx_mbps", horizon_seconds=60, sample_interval=1.0)
    assert report["origins"] == 100 - 60 - 11
    assert report["unavailable_targets"] == 0
    assert report["methods"]["persistence"]["n"] == report["origins"]
    short = evaluate_runs(split_runs(_rows([1.0] * 40), 1.0), "rx_mbps", horizon_seconds=60, sample_interval=1.0)
    assert short["origins"] == 0
    assert short["methods"]["persistence"]["mae"] is None


def test_future_values_do_not_change_past_forecasts():
    base = [0.2 + 0.01 * (index % 3) for index in range(80)]
    altered = base[:50] + [30.0] * 30
    one = evaluate_runs(split_runs(_rows(base), 1.0), "rx_mbps", horizon_seconds=1, sample_interval=1.0)
    two = evaluate_runs(split_runs(_rows(altered), 1.0), "rx_mbps", horizon_seconds=1, sample_interval=1.0)
    # Origins before index 49 predict the same values; only their labels after 49 differ.
    assert one["methods"]["persistence"]["n"] == two["methods"]["persistence"]["n"]
    assert two["methods"]["persistence"]["mae"] > one["methods"]["persistence"]["mae"]


def test_holt_is_kept_only_when_it_beats_the_baselines():
    trend = _rows([0.1 * index for index in range(200)])
    trend_report = evaluate_history(trend, sample_interval=1.0, horizons=(60.0,))
    assert trend_report["receive"]["60"]["holt_justified"] is True
    noise = _rows([0.2 if index % 7 else 5.0 for index in range(400)])
    noise_report = evaluate_history(noise, sample_interval=1.0, horizons=(60.0,))
    assert noise_report["receive"]["60"]["holt_justified"] is False
    assert holt_justified({"holt": {"n": 0}}) is False


def test_burst_targets_are_split_from_quiet_targets():
    values = [0.2] * 70 + [20.0] * 10 + [0.2] * 30
    report = evaluate_runs(split_runs(_rows(values), 1.0), "rx_mbps", horizon_seconds=5, sample_interval=1.0)
    assert report["burst"]["persistence"]["n"] >= 5
    assert report["quiet"]["persistence"]["n"] > report["burst"]["persistence"]["n"]
    assert report["burst"]["persistence"]["bias"] < 0


def test_long_chart_windows_keep_peaks_and_do_not_fill_gaps():
    from monitoring.service import downsample_history

    rows = _rows([0.2] * 3600, start=36_000.0)
    rows[1800]["rx_mbps"] = 42.0
    for row in rows[2000:2100]:
        row["quality"] = "gap"
        row["rx_mbps"] = None
    out, meta = downsample_history(rows, 900, 3600)
    assert meta == {"downsampled": True, "bucket_seconds": 4.0, "aggregate": "max"}
    assert len(out) <= 901
    assert max(item["rx_mbps"] or 0 for item in out) == 42.0
    gap_buckets = [item for item in out if 38_000 <= item["sampled_at"] < 38_100]
    assert gap_buckets and all(item["quality"] == "gap" and item["rx_mbps"] is None for item in gap_buckets)
    short, short_meta = downsample_history(rows[:300], 900, 300)
    assert short == rows[:300] and short_meta["downsampled"] is False


def test_schedule_does_not_drift_with_work_time():
    deadline = 0.0
    now = 0.0
    for _ in range(100):
        now += 0.3  # work time inside each sample
        deadline = next_deadline(deadline, now, 1.0)
        now = deadline
    assert deadline == pytest.approx(100.0)


def test_schedule_skips_missed_slots_instead_of_bursting():
    assert next_deadline(10.0, 13.4, 1.0) == pytest.approx(14.0)
    assert next_deadline(10.0, 10.2, 1.0) == pytest.approx(11.0)


def test_packet_direction_uses_local_addresses_and_group_frames():
    meter = PacketRateMeter("nic", ips={"10.0.0.5", "fe80::1"}, macs={"aa:bb:cc:dd:ee:ff"})
    assert meter.classify("10.0.0.5", "8.8.8.8", None, None) == "tx"
    assert meter.classify("8.8.8.8", "10.0.0.5", None, None) == "rx"
    assert meter.classify(None, None, "aa:bb:cc:dd:ee:ff", "11:22:33:44:55:66") == "tx"
    assert meter.classify("10.0.0.9", "224.0.0.251", "12:34:56:78:9a:bc", "01:00:5e:00:00:fb") == "rx"
    assert meter.classify("10.0.0.9", "10.0.0.255", None, "ff:ff:ff:ff:ff:ff") == "rx"
    assert meter.classify("10.0.0.9", "10.0.0.7", "12:34:56:78:9a:bc", "02:00:00:00:00:01") == "other"
    meter.add("rx", 1500)
    meter.add("tx", 60)
    meter.add("other", 99)
    snap = meter.snapshot()
    assert (snap.rx_bytes, snap.tx_bytes, snap.other_bytes) == (1500, 60, 99)


def test_probe_reports_permission_errors_honestly(monkeypatch):
    monkeypatch.setattr(packet_rates, "capture_availability", lambda name: {"available": True, "reason": "ok"})
    monkeypatch.setattr(packet_rates, "resolve_scapy_interface", lambda name: name)
    monkeypatch.setattr(packet_rates, "local_addresses", lambda name: (set(), set()))

    def denied(**kwargs):
        raise PermissionError("access denied")

    monkeypatch.setattr("scapy.all.sniff", denied)
    result = probe_capture("nic", 1.0)
    assert result["status"] == "permission_denied"
    assert "packet" not in result


def test_probe_unavailable_without_driver(monkeypatch):
    monkeypatch.setattr(
        packet_rates,
        "capture_availability",
        lambda name: {"available": False, "reason": "Npcap was not found."},
    )
    result = probe_capture("nic", 1.0)
    assert result["status"] == "unavailable"
    assert result["error"] == "Npcap was not found."


def test_sniffer_starts_and_stops_on_a_quiet_interface(monkeypatch):
    from capture import sniffer
    from capture.state import CaptureStatus, capture_state

    calls = {"n": 0}

    def quiet_sniff(**kwargs):
        calls["n"] += 1
        kwargs["started_callback"]()
        time.sleep(min(0.05, kwargs.get("timeout") or 0.05))

    monkeypatch.setattr("scapy.all.sniff", quiet_sniff)
    monkeypatch.setattr("capture.packet_rates.resolve_scapy_interface", lambda name: name)
    sniffer.start_capture("nic")
    for _ in range(40):
        if capture_state.status == CaptureStatus.RUNNING:
            break
        time.sleep(0.05)
    assert capture_state.status == CaptureStatus.RUNNING
    started = time.monotonic()
    sniffer.stop_capture()
    assert time.monotonic() - started < 2.0
    assert capture_state.status == CaptureStatus.IDLE
    assert capture_state.is_capturing is False
    assert calls["n"] >= 1
    assert not any(thread.name == "sniffer-nic" and thread.is_alive() for thread in threading.enumerate())


def test_sniffer_permission_error_marks_error_not_running(monkeypatch):
    from capture import sniffer
    from capture.state import CaptureStatus, capture_state

    def denied(**kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr("scapy.all.sniff", denied)
    monkeypatch.setattr("capture.packet_rates.resolve_scapy_interface", lambda name: name)
    sniffer.start_capture("nic")
    for _ in range(40):
        if capture_state.status == CaptureStatus.ERROR:
            break
        time.sleep(0.05)
    assert capture_state.status == CaptureStatus.ERROR
    assert "Permission denied" in (capture_state.error or "")
    sniffer.stop_capture()

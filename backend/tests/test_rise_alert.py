"""Rise alerts and the five-minute advance-warning gate."""

from analytics.forecasting import describe_recent_rise
from analytics.rise_alert import (
    ADVANCE_MESSAGE,
    build_rise_alert,
    evaluate_advance_warning,
    warning_beats_baselines,
)
from tests.test_forecast_timing import RECORDED_RX


def _quiet(count: int = 40, level: float = 0.2) -> list[float]:
    return [level + (0.01 if index % 2 == 0 else -0.01) for index in range(count)]


def _winning_report() -> dict:
    def row(recall: float, false_positive: float, precision: float | None) -> dict:
        return {
            "event_recall": recall,
            "false_positive_rate": false_positive,
            "precision": precision,
        }

    return {
        "events": 5,
        "methods": {
            "recent_slope": row(0.8, 0.0, 1.0),
            "never": row(0.0, 0.0, None),
            "persistence": row(0.0, 0.0, None),
            "moving_average": row(0.0, 0.0, None),
            "exponential_smoothing": row(0.0, 0.0, None),
        },
    }


def test_quiet_traffic_is_not_a_burst():
    assert describe_recent_rise(_quiet())["rising"] is False


def test_recorded_burst_is_a_rise_only_after_it_appears():
    onset = RECORDED_RX.index(10.3307)
    assert describe_recent_rise(RECORDED_RX[:onset])["rising"] is False
    assert describe_recent_rise(RECORDED_RX[: onset + 1])["rising"] is True


def test_small_blip_is_not_labeled_a_burst():
    values = _quiet(20) + [1.8]
    assert describe_recent_rise(values)["rising"] is False


def test_missing_sample_does_not_become_a_rise_or_a_prediction():
    rise = describe_recent_rise(RECORDED_RX)
    alert = build_rise_alert(
        fresh=True,
        quality="gap",
        sampled_at=100.0,
        direction="per_direction",
        receive_rise=rise,
        transmit_rise=describe_recent_rise(_quiet()),
        capacity_mbps=10,
        capacity_source="user",
    )
    assert alert["state"] == "unavailable"
    assert alert["rising"] is False
    assert alert["advance"]["enabled"] is False
    assert alert["advance"]["message"] == ADVANCE_MESSAGE


def test_upload_only_ignores_a_download_burst():
    alert = build_rise_alert(
        fresh=True,
        quality="ok",
        sampled_at=100.0,
        direction="transmit_only",
        receive_rise=describe_recent_rise(RECORDED_RX),
        transmit_rise=describe_recent_rise(_quiet()),
        capacity_mbps=10,
        capacity_source="user",
    )
    assert alert["state"] == "normal"
    assert alert["directions"] == []


def test_download_burst_is_traffic_rising_and_not_an_advance_warning():
    during_burst = RECORDED_RX[: RECORDED_RX.index(30.39) + 1]
    alert = build_rise_alert(
        fresh=True,
        quality="ok",
        sampled_at=100.0,
        direction="receive_only",
        receive_rise=describe_recent_rise(during_burst),
        transmit_rise=None,
        capacity_mbps=10,
        capacity_source="user",
    )
    assert alert["state"] == "traffic_rising"
    assert alert["directions"] == ["receive"]
    assert alert["advance"]["predicts"] is False
    assert alert["capacity_is_user_threshold"] is True
    assert "not a measured internet capacity" in alert["capacity_note"]


def test_high_predicted_risk_stays_off_without_a_winning_walk_forward():
    alert = build_rise_alert(
        fresh=True,
        quality="ok",
        sampled_at=100.0,
        direction="per_direction",
        receive_rise=describe_recent_rise(_quiet()),
        transmit_rise=describe_recent_rise(_quiet()),
        capacity_mbps=8,
        capacity_source="user",
        advance_predicts=True,
    )
    assert alert["state"] == "normal"
    assert alert["advance"]["message"] == ADVANCE_MESSAGE


def test_high_predicted_risk_requires_the_gate_and_a_current_prediction():
    alert = build_rise_alert(
        fresh=True,
        quality="ok",
        sampled_at=100.0,
        direction="per_direction",
        receive_rise=describe_recent_rise(_quiet()),
        transmit_rise=describe_recent_rise(_quiet()),
        capacity_mbps=8,
        capacity_source="user",
        advance_report=_winning_report(),
        advance_predicts=True,
    )
    assert warning_beats_baselines(_winning_report()) is True
    assert alert["state"] == "high_predicted_risk"
    assert "exact start time" in alert["advance"]["message"]


def test_recorded_burst_does_not_beat_baselines_before_the_crossing():
    report = evaluate_advance_warning(RECORDED_RX, 8.0, horizon=15)
    assert report["events"] == 4
    assert report["leakage"].startswith("Each warning uses observations")
    slope = report["methods"]["recent_slope"]
    # Later re-crossings can be projected once the burst is already in the window.
    # The first quiet-to-burst crossing is still missed, and there is no quiet
    # origin with a full horizon, so the false-alarm rate is not established.
    assert slope["event_hits"] == 3
    assert slope["event_misses"] == 1
    assert slope["false_positive_rate"] is None
    for name in ("never", "persistence", "moving_average", "exponential_smoothing"):
        assert report["methods"][name]["event_hits"] == 0
    assert warning_beats_baselines(report) is False


def test_quiet_series_has_no_threshold_events_to_enable_a_warning():
    report = evaluate_advance_warning(_quiet(80), 8.0, horizon=10)
    assert report["events"] == 0
    assert report["methods"]["recent_slope"]["warnings"] == 0
    assert report["methods"]["recent_slope"]["false_positive_rate"] == 0
    assert warning_beats_baselines(report) is False


def test_false_alarm_on_a_rise_that_never_crosses_the_threshold():
    values = _quiet(30) + [2.5, 3.5, 4.5, 4.0] + _quiet(20)
    report = evaluate_advance_warning(values, 8.0, horizon=10)
    assert report["events"] == 0
    slope = report["methods"]["recent_slope"]
    assert slope["warnings"] >= 1
    assert slope["false_positive_rate"] > 0
    assert slope["event_hits"] == 0
    assert warning_beats_baselines(report) is False

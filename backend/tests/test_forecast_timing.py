"""Forecast timing and a recorded Wi-Fi burst.

The Mbps sequence below is copied from observations.sqlite for the Wi-Fi
interface on 2026-10-22, 12:05:30–12:06:20 local time. It is not a generated
speed test.
"""

from analytics.forecasting import (
    Point,
    describe_recent_rise,
    exponential_smoothing_forecast,
    forecast_direction,
)

# Recorded download Mbps, one sample apart, quality ok.
RECORDED_RX = [
    0.1332, 0.1394, 0.1296, 0.0408, 0.0877, 0.0276, 0.0361, 0.0252, 0.1363, 0.356,
    0.054, 0.4512, 0.3657, 0.205, 0.1258, 1.516, 10.3307, 5.5228, 3.6238, 2.6967,
    1.9898, 2.3095, 3.2439, 3.7485, 8.9964, 9.3994, 6.4094, 12.7142, 9.5607, 3.0808,
    4.8462, 4.0489, 7.1924, 14.8063, 18.19, 17.4632, 16.906, 24.2949, 28.5228, 27.8071,
    30.39, 30.0228, 27.3792, 2.5767, 0.1722, 0.1863,
]


def _points(values: list[float], start: float = 1_000.0) -> list[Point]:
    return [Point(start + index, value, 1.0) for index, value in enumerate(values)]


def test_forecast_line_starts_after_the_latest_observation():
    points = _points([1.0, 1.2, 0.8, 1.1])
    result = forecast_direction(
        points,
        method="exponential_smoothing",
        window=12,
        alpha=0.3,
        sample_interval=1.0,
        horizon_seconds=300,
    )
    origin = points[-1].timestamp
    assert result["origin_timestamp"] == origin
    assert result["series"][0]["timestamp"] == origin + 1
    assert result["series"][1]["timestamp"] == origin + 300
    assert result["series"][0]["kind"] == "forecast"
    assert result["series"][0]["mbps"] == result["point_mbps"]
    assert result["point_mbps"] < 5
    later = forecast_direction(
        points + [Point(origin + 1, 40.0, 1.0)],
        method="exponential_smoothing",
        window=12,
        alpha=0.3,
        sample_interval=1.0,
        horizon_seconds=300,
    )
    assert later["point_mbps"] != result["point_mbps"]
    assert result["point_mbps"] < 5


def test_recorded_burst_was_not_predicted_before_it_started():
    onset = RECORDED_RX.index(10.3307)
    before = exponential_smoothing_forecast(RECORDED_RX[:onset], 0.3)
    assert before is not None
    assert before < 2
    assert before < 0.5 * RECORDED_RX[onset]
    peak_index = RECORDED_RX.index(30.39)
    during = forecast_direction(
        _points(RECORDED_RX[: peak_index + 1]),
        method="exponential_smoothing",
        window=12,
        alpha=0.3,
        sample_interval=1.0,
        horizon_seconds=300,
    )
    assert during["origin_timestamp"] == 1_000.0 + peak_index
    assert during["series"][0]["timestamp"] > during["origin_timestamp"]
    # Smoothing has caught some of the rise, and it is still below the peak.
    assert 5 < during["point_mbps"] < 30.39
    rise = describe_recent_rise(RECORDED_RX[: peak_index + 1])
    assert rise["rising"] is True
    assert rise["status"] == "rise_in_progress"
    quiet = describe_recent_rise(RECORDED_RX[:onset])
    assert quiet["rising"] is False

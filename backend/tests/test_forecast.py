"""Forecast math, walk-forward evaluation, and leakage checks."""

import pytest

from analytics.forecasting import (
    Point,
    contiguous_run,
    evaluate_series,
    exponential_smoothing_forecast,
    forecast_direction,
    moving_average_forecast,
    persistence_forecast,
)


def test_moving_average_window():
    assert moving_average_forecast([1, 2, 3, 4], 2) == pytest.approx(3.5)
    assert moving_average_forecast([1, 2], 3) is None


def test_exponential_smoothing_recurrence():
    # F2 = X1 = 10; F3 = 0.5*20 + 0.5*10 = 15; F4 = 0.5*30 + 0.5*15 = 22.5
    assert exponential_smoothing_forecast([10, 20, 30], 0.5) == pytest.approx(22.5)
    assert exponential_smoothing_forecast([10], 0.5) is None


def test_exponential_smoothing_rejects_bad_alpha():
    with pytest.raises(ValueError):
        exponential_smoothing_forecast([1, 2], 0)
    with pytest.raises(ValueError):
        exponential_smoothing_forecast([1, 2], 1.1)


def test_persistence_is_the_latest_observation():
    assert persistence_forecast([4, 9]) == 9
    assert persistence_forecast([]) is None


def test_gaps_are_not_treated_as_equal_spacing():
    points = [
        Point(0, 1, 1),
        Point(1, 2, 1),
        Point(2, 3, 1),
        Point(30, 9, 1),
        Point(31, 8, 1),
    ]
    run, excluded = contiguous_run(points, 1.0)
    assert [point.value for point in run] == [9, 8]
    assert excluded == 3


def test_missing_samples_are_not_zero_filled():
    forecast = forecast_direction(
        [Point(0, 5, 1)],
        method="exponential_smoothing",
        window=3,
        alpha=0.3,
        sample_interval=1,
        horizon_seconds=60,
    )
    assert forecast["status"] == "insufficient_data"
    assert forecast["point_mbps"] is None
    assert forecast["series"] == []


def test_walk_forward_does_not_use_the_future():
    points = [Point(float(index), value, 1.0) for index, value in enumerate([1, 2, 3, 100])]
    evaluation = evaluate_series(points, window=2, alpha=0.5, horizon_steps=1)
    # Origins that can see 100 would forecast it badly if the future leaked in.
    # The moving-average error uses mean(2, 3)=2.5 against 100, plus mean(1, 2)=1.5 against 3.
    assert evaluation["status"] == "evaluated"
    assert evaluation["training_metrics_reported"] is False
    assert evaluation["methods"]["moving_average"]["mae"] == pytest.approx(49.5)


def test_evaluation_metrics_match_hand_calculation():
    values = [10, 10, 10, 20]
    points = [Point(float(index), value, 1.0) for index, value in enumerate(values)]
    evaluation = evaluate_series(points, window=2, alpha=0.5, horizon_steps=1)
    # Shared origins start at index 2. Persistence predicts 10 then 10.
    # MA window 2 predicts 10 then 10. SES after two points:
    # F for index 2 = 0.5*10 + 0.5*10 = 10, actual 10
    # then F for index 3 = 0.5*10 + 0.5*10 = 10, actual 20
    persistence = evaluation["methods"]["persistence"]
    assert persistence["n"] == 2
    assert persistence["mae"] == pytest.approx(5)
    assert persistence["bias"] == pytest.approx(-5)
    assert evaluation["methods"]["moving_average"]["mae"] == pytest.approx(5)
    assert evaluation["methods"]["persistence"]["mape_status"] == "reported"


def test_mape_is_withheld_near_zero():
    points = [Point(float(index), value, 1.0) for index, value in enumerate([0, 0, 0, 0.01, 0.02])]
    evaluation = evaluate_series(points, window=2, alpha=0.4, horizon_steps=1)
    assert evaluation["methods"]["persistence"]["mape"] is None
    assert evaluation["methods"]["persistence"]["mape_status"] == "not_reported_near_zero_actuals"


def test_interval_is_pending_without_enough_residuals():
    points = [Point(float(index), float(index + 1), 1.0) for index in range(10)]
    evaluation = evaluate_series(points, window=3, alpha=0.3, horizon_steps=1)
    assert evaluation["interval_status"] == "pending"
    assert evaluation["one_step_intervals"]["moving_average"] is None


def test_short_horizon_evaluation_is_pending():
    points = [Point(float(index), 5.0, 1.0) for index in range(20)]
    forecast = forecast_direction(
        points,
        method="moving_average",
        window=4,
        alpha=0.3,
        sample_interval=1,
        horizon_seconds=60,
    )
    assert forecast["sufficient"] is True
    assert forecast["flat"] is True
    assert forecast["point_mbps"] == pytest.approx(5)
    assert forecast["interval"] is None
    assert forecast["evaluation"]["horizon_evaluation"] == "pending"


def test_level_forecast_series_is_labeled_forecast():
    points = [Point(float(index), 4.0, 1.0) for index in range(6)]
    forecast = forecast_direction(
        points,
        method="exponential_smoothing",
        window=4,
        alpha=0.2,
        sample_interval=1,
        horizon_seconds=5,
    )
    assert forecast["series"][0]["kind"] == "forecast"
    assert forecast["series"][0]["timestamp"] == pytest.approx(6)
    assert forecast["series"][-1]["mbps"] == pytest.approx(forecast["point_mbps"])

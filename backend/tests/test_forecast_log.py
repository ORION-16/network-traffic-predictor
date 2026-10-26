"""Saved forecasts are scored only against a later observation."""

from monitoring.forecast_log import issue_from_rows, rows_for_forecast, score_pending, summarize_forecasts
from monitoring.store import Store


def _row(stamp: float, rx: float, tx: float) -> dict:
    return {
        "sampled_at": stamp,
        "interval_seconds": 1.0,
        "interface_name": "eth-test",
        "rx_mbps": rx,
        "tx_mbps": tx,
        "valid": True,
        "quality": "ok",
    }


def test_forecast_is_saved_then_scored_without_using_the_future(tmp_path):
    store = Store(tmp_path / "obs.sqlite")
    store.init()
    rows = [_row(1000 + offset, float(offset), float(offset) / 2) for offset in range(12)]
    for row in rows:
        assert store.insert_observation(row)

    issued = issue_from_rows(
        store,
        "eth-test",
        rows,
        sample_interval=1.0,
        horizon_seconds=5.0,
        window=12,
        alpha=0.3,
    )
    assert issued > 0
    pending = store.pending_forecasts("eth-test", now=1012)
    assert pending
    created = pending[0]["created_at"]
    assert created == 1011
    assert all(row["actual_mbps"] is None for row in pending)

    future = _row(1012, 50.0, 25.0)
    store.insert_observation(future)
    score_pending(store, "eth-test", tolerance=0.75, now=1012)
    scored = [row for row in store.forecast_rows("eth-test") if row["kind"] == "one_step" and row["status"] == "scored"]
    assert scored
    assert all(row["actual_at"] > row["created_at"] for row in scored)
    assert all(row["predicted_mbps"] != 50 or row["method"] == "persistence" for row in scored if row["direction"] == "receive")
    persistence = next(row for row in scored if row["method"] == "persistence" and row["direction"] == "receive")
    assert persistence["predicted_mbps"] == 11
    assert persistence["actual_mbps"] == 50

    report = summarize_forecasts(store, "eth-test")
    assert report["scored"] >= 1
    assert report["status"] == "insufficient_history"


def test_missing_target_is_not_scored_as_zero(tmp_path):
    store = Store(tmp_path / "obs.sqlite")
    store.init()
    rows = [_row(1000 + offset, 1.0, 1.0) for offset in range(4)]
    for row in rows:
        store.insert_observation(row)
    issue_from_rows(
        store,
        "eth-test",
        rows,
        sample_interval=1.0,
        horizon_seconds=30.0,
        window=12,
        alpha=0.3,
    )
    score_pending(store, "eth-test", tolerance=0.75, now=1100)
    rows_after = store.forecast_rows("eth-test")
    assert rows_after
    assert all(row["status"] == "missed" for row in rows_after)
    assert all(row["actual_mbps"] is None for row in rows_after)
    summary = store.dataset_summary("eth-test")
    assert summary["valid_observations"] == 4
    assert summary["gaps_filled"] is False


def test_duplicate_forecast_for_the_same_origin_is_ignored(tmp_path):
    store = Store(tmp_path / "obs.sqlite")
    store.init()
    rows = [_row(1000 + offset, 2.0, 1.0) for offset in range(3)]
    first = issue_from_rows(store, "eth-test", rows, sample_interval=1.0, horizon_seconds=10, window=12, alpha=0.3)
    second = issue_from_rows(store, "eth-test", rows, sample_interval=1.0, horizon_seconds=10, window=12, alpha=0.3)
    assert first > 0
    assert second == 0


def test_rows_for_forecast_keep_only_the_latest_contiguous_run():
    rows = [_row(1000, 1, 1), _row(1001, 1, 1), _row(1030, 5, 1), _row(1031, 6, 1)]
    kept = rows_for_forecast(rows, 1.0)
    assert [row["sampled_at"] for row in kept] == [1030, 1031]


def test_score_summary_ignores_origins_that_are_missing_a_method(tmp_path):
    store = Store(tmp_path / "obs.sqlite")
    store.init()

    def save(created: float, method: str, predicted: float) -> None:
        assert store.insert_forecast(
            {
                "interface_name": "eth-test",
                "method": method,
                "direction": "receive",
                "kind": "one_step",
                "created_at": created,
                "target_at": created + 1,
                "horizon_seconds": 1,
                "predicted_mbps": predicted,
                "observations_used": 2,
            }
        )

    for offset in range(5):
        created = 2000 + offset
        save(created, "persistence", 10)
        save(created, "moving_average", 4)
        save(created, "exponential_smoothing", 1)
    save(3000, "persistence", 99)

    actuals = {"persistence": 8.0, "moving_average": 6.0, "exponential_smoothing": 1.0}
    for row in store.forecast_rows("eth-test"):
        actual = 0.0 if row["created_at"] == 3000 else actuals[row["method"]]
        store.mark_forecast(row["id"], status="scored", actual_mbps=actual, actual_at=row["created_at"] + 1)

    report = summarize_forecasts(store, "eth-test")
    block = report["receive"]["one_step"]
    assert report["status"] == "evaluated"
    assert block["n"] == 5
    assert block["methods"]["persistence"]["mae"] == 2
    assert block["methods"]["moving_average"]["mae"] == 2
    assert block["methods"]["exponential_smoothing"]["mae"] == 0
    assert block["methods"]["persistence"]["n"] == 5
    assert report["receive"]["horizon"]["n"] == 0

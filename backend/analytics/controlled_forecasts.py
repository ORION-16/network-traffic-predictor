"""Fixed series used to compare forecast methods.

The stable and burst series are constructed so the sample size is known.
The recorded series is the Wi-Fi download from 2026-10-22 12:05:30–12:06:20.
None of these numbers is a live measurement from the current dashboard.
"""

from __future__ import annotations

from analytics.walk_forward import evaluate_runs

# Recorded download Mbps, one second apart, quality ok. Peak 30.39.
RECORDED_RX = [
    0.1332, 0.1394, 0.1296, 0.0408, 0.0877, 0.0276, 0.0361, 0.0252, 0.1363, 0.356,
    0.054, 0.4512, 0.3657, 0.205, 0.1258, 1.516, 10.3307, 5.5228, 3.6238, 2.6967,
    1.9898, 2.3095, 3.2439, 3.7485, 8.9964, 9.3994, 6.4094, 12.7142, 9.5607, 3.0808,
    4.8462, 4.0489, 7.1924, 14.8063, 18.19, 17.4632, 16.906, 24.2949, 28.5228, 27.8071,
    30.39, 30.0228, 27.3792, 2.5767, 0.1722, 0.1863,
]


def _rows(values: list[float], *, start: float = 1_000.0) -> list[dict]:
    return [
        {
            "sampled_at": start + index,
            "interval_seconds": 1.0,
            "quality": "ok",
            "rx_mbps": value,
            "tx_mbps": value,
        }
        for index, value in enumerate(values)
    ]


def _summary(report: dict) -> dict:
    methods = {}
    for name in ("persistence", "moving_average", "exponential_smoothing"):
        metrics = report["methods"][name]
        quiet = report["quiet"][name]
        burst = report["burst"][name]
        methods[name] = {
            "n": metrics["n"],
            "mae": metrics["mae"],
            "rmse": metrics["rmse"],
            "mape": metrics["mape"],
            "mape_status": metrics["mape_status"],
            "quiet_n": quiet["n"],
            "quiet_mae": quiet["mae"],
            "burst_n": burst["n"],
            "burst_mae": burst["mae"],
        }
    return {
        "samples": report["origins"] and None,
        "horizon_seconds": report["horizon_seconds"],
        "score_status": report["score_status"],
        "reason": report["reason"],
        "best_baseline": report["best_baseline"],
        "quiet_best_baseline": report["quiet_best_baseline"],
        "burst_best_baseline": report["burst_best_baseline"],
        "methods": methods,
    }


def controlled_forecast_report() -> dict:
    stable_values = [1.0] * 180
    burst_values = [1.0] * 100 + [40.0] * 40 + [1.0] * 40
    cases = [
        ("stable", "Constructed constant 1 Mbps. Not live traffic.", stable_values, 60.0),
        ("burst", "Constructed quiet period, then 40 Mbps, then quiet. Not live traffic.", burst_values, 60.0),
        (
            "recorded_burst",
            "Recorded Wi-Fi download, 2026-10-22 12:05:30–12:06:20, 46 samples, peak 30.39 Mbps.",
            RECORDED_RX,
            10.0,
        ),
    ]
    results = []
    for name, source, values, horizon in cases:
        report = evaluate_runs([_rows(values)], "rx_mbps", horizon_seconds=horizon, sample_interval=1.0)
        item = _summary(report)
        item["name"] = name
        item["source"] = source
        item["samples"] = len(values)
        results.append(item)
    return {
        "note": "These rows are fixed series for method comparison. They are not the live forecast and they are not an advance-warning claim.",
        "cases": results,
    }

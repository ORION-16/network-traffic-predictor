# Verification — 26 October 2026

Measured on this Windows 11 machine. No network load was generated. Counter cases below are fixed byte sequences passed through the same rate function the collector uses.

## Tests

- Backend: `python -m pytest -q` — 133 passed, 1 existing Starlette multipart warning.
- Frontend: `node --test src/lib/monitoringView.test.js` — 17 passed.
- Production build: Vite 6.4.4, 41 modules, built in 33.53 s. The Plotly chunk is about 5.1 MB; the build warns and completes.

## What the five requirements do

1. Adapter changes, counter resets, missing counters, intervals under 0.05 s, and gaps over 15 s are stored with a null rate. A later reading starts from the new counters. The chart leaves those intervals blank and marks them in amber. A disconnected interface stores no row.
2. Persistence, a 12-point moving average, and exponential smoothing (alpha 0.3) are scored on the same origins. MAE and RMSE are always shown. MAPE is omitted when any actual in that score is below 0.05 Mbps. Quiet and burst splits name the lowest-MAE baseline. Holt is scored and is not drawn unless it wins on both MAE and RMSE. Advance warning stays off unless its separate gate passes.
3. Download and upload thresholds are user-entered. The optional baseline anomaly, off by default, compares the latest rate with the median of up to 60 earlier samples and freezes that median for the episode. The episode table shows type, rate, threshold or baseline, start, and duration. The copy says this is not a confirmed attack.
4. One threshold episode stays open while the rate remains high, including across a backend restart. Recovery is configurable and defaults to 3 valid readings below 90% of the threshold. A return within the cooldown (default 30 s) reopens the same episode. A failed SQLite write stores nothing.
5. `GET /api/reliability` and `python -m scripts.reliability_report` measure the items below. They do not saturate the link.

## Measured reliability report

Taken from `python -m scripts.reliability_report` at `measured_at` 1793031565, interface Wi-Fi, latest 2,788 stored readings:

| Measurement | Result |
| --- | --- |
| Interval median | 1.002 s |
| Interval p95 | 1.051 s |
| Longest stored interval | 23.281 s, recorded as a gap, not as zero traffic |
| Invalid intervals in that window | 2 (1 baseline, 1 gap) |
| Valid zero rates | 0 |
| Temporary SQLite, 200 inserts | median 14.96 ms, p95 23.06 ms, 55.8 rows/s |
| 24-hour retention probe | 1 expired row deleted, 1 newer row kept |
| This process | 0.0% CPU over 0.1 s, 29.7 MB RSS |

The collector writes about one row per second, so a 15 ms write is not what limits sampling. The 23 s gap is a real pause that was stored as `gap`. This run did not put the NIC under a generated high load, so it does not report a saturated-link result. The fixed counter check produced 1.000 Mbps from 125,000 bytes in 1.000 s, 0.000 Mbps when the counters did not change, and null rates for a short interval, a 20 s gap, a decreasing counter, an interface change, and missing counters.

## Follow-up audit — 26 October 2026, later the same day

### Forecast sample sizes

Stored Wi-Fi readings were scored again after valid samples delayed by a few seconds were kept in the same run. A gap beyond 15 seconds still starts a new run. Nothing was interpolated.

On the database at that check: 1,050 rows, 2 runs, longest run 673 seconds.

| Horizon | Persistence n | Persistence MAE | Result |
| --- | --- | --- | --- |
| 1 min | 871 | 4.221 Mbps | scored |
| 5 min | 424 | 3.679 Mbps | scored |
| 15 min | none | blank | longest run is 673 s, shorter than 900 s |

The 15-minute cell stays blank. It is not filled with the 1-minute or 5-minute error.

### Threshold values

The saved download and upload thresholds are 10 Mbps. An older capacity value of 1 Mbps is still stored. The chart, the alert, and the forecast comparison now use 10 Mbps. The page says the 1 Mbps value is not the alert line. Neither number was changed in the database.

### Measured load and API time

`python -m scripts.reliability_report` at `measured_at` 1793033265. These inserts were written to temporary databases. No network load was generated.

| Check | Result |
| --- | --- |
| Health API, 5 requests | median 5.38 ms, maximum 112.69 ms |
| SQLite, 50 rows | 54.9 rows/s, CPU 10.3%, RSS 40.3 MB after |
| SQLite, 200 rows | 67.1 rows/s, CPU 16.8%, RSS 45.2 MB after |
| SQLite, 800 rows | 67.0 rows/s, CPU 17.3%, RSS 50.1 MB after |
| Sampling, 1,112 stored readings | median interval 1.000 s, p95 1.053 s, longest 35.009 s stored as a gap |

The write rate stays near 67 rows/s from 200 to 800 rows, so the per-row transaction is the limit in this process. One health request was much slower than the median; that maximum is reported rather than dropped.

### Tests after this audit

- Backend: `python -m pytest -q` — 134 passed, 1 existing Starlette multipart warning, 63.01 s.
- Frontend: `node --test src/lib/monitoringView.test.js` — 18 passed.
- Production build: Vite 6.4.4, 41 modules, built in 34.76 s. The Plotly chunk remains about 5.1 MB and the build warns.

## Limitations

- No generated traffic test at high packet rates was run. The low, medium, and high figures are SQLite insert counts in this process.
- A 15-minute forecast score stays blank until a valid run is longer than 15 minutes. The longest stored run at the check above was 673 seconds.
- The 0.1 s CPU sample is this Python process while idle, not the dashboard under load.
- Baseline anomaly and the five-minute advance warning are not enabled by the stored evidence. The advance-warning gate is unchanged and still requires a separate passing walk-forward result.
- macOS and Linux were not tested.

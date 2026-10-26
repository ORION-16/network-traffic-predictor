# Network Traffic Predictor

A dashboard for traffic on **one interface of this computer**.

1. **Overview** — collector health, data source, interface, profile, live download and upload, alert state, packet-capture state.
2. **Live network traffic** — decimal Mbps from OS counter deltas, with your saved thresholds, threshold-crossing markers, interface-change markers, and a 5 min / 15 min / 1 hour window. Gaps stay blank.
3. **Traffic alert** — Normal, Traffic rising, Threshold exceeded, Predicted threshold risk, Insufficient history, or Collector unavailable or stale. Each state has a reason and a timestamp, and each direction shows its last alert and last recovery.
4. **Traffic forecast** — exponential smoothing drawn as a flat dashed level, compared with persistence and a moving average, for 1, 5, or 15 minutes.
5. **Interface and thresholds** — automatic or manual interface, separate download and upload thresholds, optionally for one interface only.
6. **Diagnostics** — walk-forward MAE and RMSE by horizon and method with n, quiet and burst splits, advance-warning precision, recall, false-positive rate, missed events, lead time, data coverage, and a 5-second packet-capture comparison.

The graph does not include the rest of the network or the router. A speed-test result is the rate of that transfer while it runs, so the chart is near zero when nothing is transferring. The dashboard never predicts when an unknown download will start.

Checked on Windows 11 with Npcap installed. macOS and Linux were not tested.

## Run

```powershell
cd backend
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. Collection starts with the backend and keeps writing SQLite rows while the browser is closed. Settings are in `backend/.env.example`. The defaults are 1-second samples, 24-hour retention at `backend/data/observations.sqlite`, and an ICMP probe to `1.1.1.1`. Leave `DEMO_MODE` set to `false`.

## Throughput definitions

```
Mbps = (byte_delta × 8) / elapsed_seconds / 1_000_000
```

- **Source.** Stored throughput always comes from `psutil.net_io_counters` for the selected interface. Download is `bytes_recv` and upload is `bytes_sent`. These counters include all frames the OS counts on that adapter, including protocol overhead.
- **Interval.** The elapsed time is monotonic time between two readings. The sampler runs on a fixed one-second grid, so the time spent on each sample does not add drift. A slot that overruns is skipped rather than sampled twice.
- **Missing values.** The first reading after a start, an interface change, or a network-address change is a baseline with no rate. A gap longer than max(5 intervals, 15 s), a counter reset, or a missing counter is stored with no rate, never as zero. A stored zero means the counter did not change.
- **Latest versus average.** "Download" and "Upload" in the overview are the latest one-second rate. The forecast is a smoothed level. Windows longer than 900 points are reduced to clock-aligned buckets that keep each bucket's highest reading, and the chart says so.

## Packet capture (optional)

Scapy capture is diagnostic only and never the stored source. `POST /api/capture/compare?seconds=5`, or the **Compare with packet capture** button, captures header metadata on the selected interface without promiscuous mode and compares it with the counters over the same window. Packet bytes and counter bytes are compared, never added.

On this Windows 11 machine, Npcap allowed capture without administrator rights:

- **Idle Wi-Fi (12 s):** capture read 0.241 Mbps down against the counters' 0.245 Mbps.
- **During a real 20 MB HTTPS download:** capture saw only 8,647 of the 15,830 received packets and read 7.31 Mbps against the counters' 14.38 Mbps. Scapy's per-packet Python callback drops packets under load.

See [docs/PERMISSIONS.md](docs/PERMISSIONS.md).

## Interfaces and profiles

- **Choosing an interface.** No adapter name is hard-coded. Choose **Automatic** to follow the interface that owns the default route; it is rechecked every 10 seconds. You can also pick any listed interface, including Ethernet, Wi-Fi, hotspot, VPN, or virtual adapters.
- **Profiles.** A profile is one interface name. Readings, forecasts, threshold overrides, and alert episodes are stored per interface, so histories are never mixed. Different Wi-Fi networks on the same adapter share one profile.
- **Switching.** On a switch, the counters re-baseline and the change is drawn on the chart. The alert reads **Insufficient history** until 12 contiguous readings exist. The jump between interfaces is not treated as a burst. If the adapter's addresses change, the counters also re-baseline. The addresses are only hashed and never stored.

This computer's traffic is not the whole business network. `backend/integrations/telemetry.py` defines the contract a router or switch source would need to meet. No such source is implemented.

## Thresholds and alerts

- **Thresholds.** Download and upload thresholds are numbers you enter for testing. They are not measured capacity, and adapter link speed is never used. The resolution order is a per-interface value, then a global value, then the older single **capacity** value. Zero, negative, non-numeric, and infinite values are rejected. The chart line, `GET /api/thresholds`, and the alert all read the same resolved values.
- **Threshold exceeded.** Each stored reading is checked on the server, separately for each direction:
  - **Start:** a valid reading at or above the threshold.
  - **Recover:** 3 valid readings in a row below 90% of the threshold.
  - **Missing data:** missing or invalid readings neither start nor end an alert.
  - **Cooldown:** a return above the threshold within 30 seconds of a recovery reopens the same episode instead of counting as a new alert.

  Episodes are saved in SQLite with the threshold, the triggering value, the peak, and how the episode ended.
- **Traffic rising** means the latest reading is already well above its recent median: at least 5 Mbps, at least 5 Mbps above the median, and either three times the median or rising from a near-idle median. This is a baseline-relative anomaly flag, applied after the rise starts. It is not a prediction.
- **Predicted threshold risk** stays off unless a walk-forward test on stored runs shows the slope rule beating never-warn, persistence, a moving average, and smoothing. It must catch more crossings with no higher false-positive rate, have precision of at least 0.5, and be scored on at least 5 crossings. On the current data it does not pass, so the panel shows "Insufficient evidence for reliable advance warning".
- **Notifications.** Browser notifications are optional and sent once when an alert begins. The panel remains the alert of record.

## Forecasting

- **Model.** Smoothing is `F(t+1) = 0.3 × X(t) + 0.7 × F(t)`, held flat over the horizon. The moving average uses 12 samples, and persistence uses the latest value. Each valid reading saves one-step and horizon forecasts with the origin, target, method, parameters, and observation count. A forecast is scored only when a later reading lands within tolerance of its target time. A target with no reading stays unscored, never zero.
- **Diagnostics.** `GET /api/diagnostics` scores persistence, moving average, smoothing, and Holt's linear trend on all stored contiguous runs at 1, 5, and 15 minutes. Holt is kept only if it beats every baseline on both MAE and RMSE. On the current Wi-Fi data it is worse at every horizon, so the smoothing and moving-average baselines stay.

## Tests

```powershell
cd backend
python -m pytest -q
```

```powershell
cd frontend
npm run lint
node --test src/lib/monitoringView.test.js
npm run build
```

Read-only scripts, run from `backend/`:

- `python -m scripts.audit_data` audits the stored data.
- `python -m scripts.run_diagnostics` prints the diagnostics report.
- `python -m scripts.check_live` checks the running backend.
- `python -m scripts.probe_capture "Wi-Fi" 5` compares packet capture with the counters.
- `python -m scripts.measure_download "Wi-Fi" 20000000` measures one real 20 MB download with both sources.

The findings are in [docs/DATA_AUDIT.md](docs/DATA_AUDIT.md).

## Limitations

- This is the laptop's interface, not every device on the network.
- A flat forecast does not say when traffic will spike, and no advance warning has passed validation on this data.
- Fifteen-minute scores need a contiguous run longer than 15 minutes. The stored history has none yet, because runs fragmented before the sampling-drift fix.
- Scapy capture undercounts at high packet rates on this machine.
- Different Wi-Fi networks on one adapter share a profile.

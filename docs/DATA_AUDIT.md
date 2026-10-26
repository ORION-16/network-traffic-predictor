# Data audit, 2026-10-22

These are read-only checks of `backend/data/observations.sqlite` and the running backend. To reproduce them, run these from `backend/`:

- `python -m scripts.audit_data`
- `python -m scripts.run_diagnostics`
- `python -m scripts.check_live`

## Confirmed

**Stored data**

| Check | Result |
|---|---|
| Observations | 9,983 over 3.55 h, all from `psutil.net_io_counters` on Windows |
| Wi-Fi rows | 9,959 ok and 12 baseline |
| Ethernet 2 rows (virtual adapter) | 10 ok and 2 baseline, from two brief manual switches |
| Packet capture as the stored source | Never |
| Duplicate timestamps | 0 |
| Non-monotonic rows | 0 |
| Fixture-named interfaces | 0 |
| Download (rx) | median 0.10 Mbps, p99 2.98 Mbps, max 150.16 Mbps |
| Upload (tx) | median 0.02 Mbps, p99 2.11 Mbps, max 23.47 Mbps |

**Near-zero graph.** Idle traffic on this laptop really is near zero; the median download is 0.10 Mbps. High values appear only while a transfer runs.

**Sampling drift (fixed).** Before the fix, the sampler waited a full interval after finishing each sample:

- The median interval was 1.243 s.
- 704 intervals fell outside 0.5–1.5 s.
- The history broke into 448 contiguous runs, the longest only 539 readings.
- So forecasts kept restarting, and no 15-minute target could be scored.

After the fix, the sampler runs on a fixed monotonic grid. In the last 120 live intervals the median was 0.999 s (range 0.965–1.041 s), and none fell outside 0.5–1.5 s.

**Alert ignored the saved threshold (fixed).** The saved threshold is 1.0 Mbps per direction. Before the fix, the alert compared readings only with a rise rule that required at least 5 Mbps. Traffic between 1 and 5 Mbps was above the saved threshold but still shown as "Low risk". After the fix, a server-side alert with hysteresis checks every stored reading. It has recorded four real Wi-Fi download episodes:

| Episode | Peak | How it ended |
|---|---|---|
| 1 | 1.51 Mbps | Recovered after 3 s |
| 2 | 1.05 Mbps | Recovered after 3 s |
| 3 | 1.40 Mbps | A manual interface switch ended it (`user_selected`), so it has no recovery time |
| 4 | 1.48 Mbps | Recovered after 22 s |

No upload episode has been recorded.

**Flat 5-minute forecast.** This is expected behavior of exponential smoothing, which holds one level flat over the horizon. It is not a defect and is labeled as such.

**Packet capture (Windows 11, Npcap, normal user).**

| Condition | Packet capture | OS counters | Packets seen by capture |
|---|---|---|---|
| Idle, 12 s | 0.241 Mbps down | 0.245 Mbps down | close match |
| 20 MB HTTPS download | 7.31 Mbps down | 14.38 Mbps down | 8,647 of 15,830 received |
| 5-second compare from the UI | 0.634 down / 0.179 up | 0.632 down / 0.179 up | 99.2% |

For the download row, the body alone was 13.23 Mbps averaged over the window. The counters add protocol overhead and background traffic on top of that.

Broadcast and multicast frames at first counted as neither direction. They are now counted as received.

**Walk-forward accuracy on stored Wi-Fi runs.** MAE and RMSE are in Mbps.

| Direction, horizon | n | Persistence | Moving average | Smoothing | Holt |
|---|---|---|---|---|---|
| Download, 1 min | 2,370 | 0.305 / 2.329 | **0.286** / 1.455 | 0.288 / 1.628 | 1.074 / 7.923 |
| Download, 5 min | 512 | 0.172 / 0.522 | **0.155** / 0.436 | 0.155 / 0.445 | 1.401 / 4.425 |
| Upload, 1 min | 2,370 | 0.153 / 0.819 | 0.149 / 0.487 | **0.147** / 0.529 | 0.391 / 2.163 |
| Upload, 5 min | 512 | 0.163 / 1.054 | **0.155** / 0.455 | 0.156 / 0.546 | 2.340 / 13.383 |
| 15 min | 0 | not scored | not scored | not scored | not scored |

- **Holt.** It is worse than every baseline at every horizon, so it is not used.
- **15 minutes.** No stored run is long enough to score it.
- **Bursts.** Only 2 burst targets exist at 1 minute. Every method missed them by about 5 Mbps, so the burst split is too small to rank methods.

**Advance warning, 5 minutes, at the saved 1 Mbps threshold.** The slope rule is the candidate; it was scored on runs of at least 20 readings.

| Direction | Crossings | Slope rule | Best baseline | Gate |
|---|---|---|---|---|
| Download | 13 | recall 1.0, precision 1.0, mean lead about 179 s | Smoothing: recall 0.38 | Fails: false-positive rate undefined, no quiet origins |
| Upload | 6 | recall 1.0, precision 0.80, false-positive rate 0.195, mean lead about 96 s | Smoothing: recall 0.50, false-positive rate 0.009 | Fails: false-positive rate is higher than the baseline's |

The dashboard therefore shows "Insufficient evidence for reliable advance warning".

## Not verified

- macOS and Linux collection and capture.
- Hotspot and VPN adapters. They appear in discovery and are classified by name or Windows metadata, but no traffic was measured on them.
- Automatic default-route following during a real Wi-Fi-to-Ethernet move. The logic is unit-checked; the API switch was exercised manually.
- Behavior on other Wi-Fi networks. All stored data is from one network.
- Whether Scapy keeps up on Linux or macOS, where capture runs through a different driver.

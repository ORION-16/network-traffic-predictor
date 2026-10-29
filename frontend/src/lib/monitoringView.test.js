import assert from "node:assert/strict";
import test from "node:test";

import { alertCopy, displayCount, displayMbps, ledgerAccuracy, levelShift, metricState, nextAlertLatch, riseWarning, thresholdCrossings, trafficOutlook } from "./monitoringView.js";

test("threshold crossings are found below, at, and above the line but never across a gap", () => {
  const rows = [
    { sampled_at: 1, quality: "ok", rx_mbps: 0.5 },
    { sampled_at: 2, quality: "ok", rx_mbps: 1.0 },
    { sampled_at: 3, quality: "ok", rx_mbps: 3.0 },
    { sampled_at: 4, quality: "ok", rx_mbps: 0.2 },
    { sampled_at: 5, quality: "gap", rx_mbps: null },
    { sampled_at: 6, quality: "ok", rx_mbps: 4.0 },
    { sampled_at: 7, quality: "ok", rx_mbps: 0.9 },
    { sampled_at: 8, quality: "ok", rx_mbps: 1.5 },
  ];
  assert.deepEqual(thresholdCrossings(rows, "rx_mbps", 1.0).map((item) => item.sampled_at), [2, 8]);
  assert.deepEqual(thresholdCrossings(rows, "rx_mbps", 0), []);
  assert.deepEqual(thresholdCrossings(rows, "rx_mbps", null), []);
  assert.deepEqual(thresholdCrossings(rows, "rx_mbps", 10), []);
});

test("threshold exceeded notifies once, outranks a rise, and clears with the server", () => {
  const quiet = { fresh: true, quality: "ok", rising: false, exceeded: false };
  const over = { ...quiet, exceeded: true, rising: true };
  const started = nextAlertLatch(nextAlertLatch(null, quiet, 1), over, 2);
  assert.equal(started.state, "threshold_exceeded");
  assert.equal(started.notify, true);
  const rising = nextAlertLatch(started, { ...quiet, rising: true }, 3);
  assert.equal(rising.state, "traffic_rising");
  assert.equal(rising.notify, false);
  const cleared = nextAlertLatch(started, quiet, 3);
  assert.equal(cleared.state, "normal");
  const copy = alertCopy({ state: "threshold_exceeded", explanation: "Download is at 4.20 Mbps against your 1 Mbps threshold." }, "threshold_exceeded");
  assert.equal(copy.label, "Threshold exceeded");
  assert.match(copy.explanation, /Download is at 4.20 Mbps/);
});

test("short history is labeled instead of shown as normal", () => {
  const latched = nextAlertLatch(null, { fresh: true, quality: "ok", insufficient: true }, 1);
  assert.equal(latched.state, "insufficient_history");
  assert.equal(alertCopy({ explanation: "Only 4 contiguous valid readings" }, latched.state).label, "Insufficient history");
});

test("missing throughput is unavailable rather than zero", () => {
  assert.equal(displayMbps(null), "unavailable");
  assert.equal(displayMbps(undefined), "unavailable");
  assert.equal(metricState(null), "unavailable");
});

test("a measured zero stays zero", () => {
  assert.equal(displayMbps(0), "0");
  assert.equal(displayCount(0), "0");
});

test("decimal Mbps formatting keeps small rates visible", () => {
  assert.equal(displayMbps(1), "1.00");
  assert.equal(displayMbps(0.008), "0.008");
});

test("dashboard view model does not invent a rate from an API null", () => {
  const payload = {
    current: { rx_mbps: null, tx_mbps: 1.25, quality: "baseline", source: "psutil.net_io_counters" },
  };
  assert.equal(displayMbps(payload.current.rx_mbps), "unavailable");
  assert.equal(displayMbps(payload.current.tx_mbps), "1.25");
});

test("a flat forecast near the latest reading is stable, not a spike time", () => {
  assert.equal(levelShift(1, 1.05), "stable");
  assert.equal(levelShift(1, 1.3), "increase");
  assert.equal(levelShift(null, 1), "unknown");
  const outlook = trafficOutlook({
    collection: { freshness: "fresh", status: "running" },
    current: { quality: "ok", rx_mbps: 1, tx_mbps: 0.4 },
    forecast: {
      receive: { sufficient: true, point_mbps: 1.02, observations_used: 20, minimum_observations: 2 },
      transmit: { sufficient: true, point_mbps: 0.41 },
    },
    capacity: { status: "unknown", source: "unknown", capacity_mbps: null },
    evaluation: { receive: { status: "pending" } },
    horizonSeconds: 300,
  });
  assert.match(outlook.trend, /stay near the recent level/);
  assert.match(outlook.trend, /not name a future spike/);
  assert.match(outlook.overload, /cannot yet be determined/);
  assert.match(outlook.accuracy, /not available yet/);
});

test("one low sample does not turn a flat forecast into an expected increase", () => {
  const history = Array.from({ length: 12 }, (_, index) => ({
    quality: "ok",
    rx_mbps: 1,
    tx_mbps: 1,
    sampled_at: index,
  }));
  history.push({ quality: "ok", rx_mbps: 0.2, tx_mbps: 0.2, sampled_at: 13 });
  const outlook = trafficOutlook({
    collection: { freshness: "fresh", status: "running" },
    current: { quality: "ok", rx_mbps: 0.2, tx_mbps: 0.2 },
    history,
    forecast: {
      receive: { sufficient: true, point_mbps: 1 },
      transmit: { sufficient: true, point_mbps: 1 },
    },
    capacity: { status: "unknown", source: "unknown", capacity_mbps: null },
    evaluation: { receive: { status: "pending" } },
    horizonSeconds: 300,
  });
  assert.match(outlook.trend, /stay near the recent level/);
});

test("a quiet reading stays normal and does not notify again", () => {
  const first = nextAlertLatch(null, { fresh: true, quality: "ok", rising: false, advanceEnabled: false, advancePredicts: false }, 1000);
  const second = nextAlertLatch(first, { fresh: true, quality: "ok", rising: false, advanceEnabled: false, advancePredicts: false }, 2000);
  assert.equal(first.state, "normal");
  assert.equal(first.notify, false);
  assert.equal(second.state, "normal");
  assert.equal(second.since, 1000);
  assert.equal(second.notify, false);
  assert.match(alertCopy({ advance: { message: "Insufficient evidence for reliable advance warning" } }, "normal").explanation, /Insufficient evidence/);
});

test("a burst alerts once and resets only after the rise stays gone", () => {
  const quiet = { fresh: true, quality: "ok", rising: false, advanceEnabled: false, advancePredicts: false };
  const rising = { ...quiet, rising: true };
  const started = nextAlertLatch(null, rising, 5000);
  assert.equal(started.state, "traffic_rising");
  assert.equal(started.notify, true);
  const held = nextAlertLatch(started, rising, 6000);
  assert.equal(held.notify, false);
  assert.equal(held.generation, started.generation);
  let latched = started;
  for (let poll = 0; poll < 4; poll += 1) {
    latched = nextAlertLatch(latched, quiet, 7000 + poll);
    assert.equal(latched.state, "traffic_rising");
  }
  const cleared = nextAlertLatch(latched, quiet, 8000);
  assert.equal(cleared.state, "normal");
  assert.equal(cleared.notify, false);
  const text = alertCopy({
    directions: ["receive"],
    receive: { latest_mbps: 24.9, prior_median_mbps: 0.2 },
    advance: { message: "Insufficient evidence for reliable advance warning" },
  }, "traffic_rising");
  assert.equal(text.label, "Traffic rising");
  assert.match(text.explanation, /Burst detected/);
  assert.match(text.explanation, /not a prediction/);
});

test("a missing sample does not become normal or a new alert", () => {
  const rising = nextAlertLatch(null, { fresh: true, quality: "ok", rising: true, advanceEnabled: false, advancePredicts: false }, 1000);
  const gap = nextAlertLatch(rising, { fresh: true, quality: "gap", rising: false, advanceEnabled: false, advancePredicts: false }, 2000);
  assert.equal(gap.state, "traffic_rising");
  assert.equal(gap.notify, false);
  const waiting = nextAlertLatch(null, { fresh: false, quality: "ok", rising: false, advanceEnabled: false, advancePredicts: false }, 3000);
  assert.equal(waiting.state, "unavailable");
  assert.equal(alertCopy(null, "unavailable").label, "Collector unavailable or stale");
});

test("high predicted risk is not shown when the advance warning is disabled", () => {
  const latched = nextAlertLatch(null, {
    fresh: true,
    quality: "ok",
    rising: false,
    advanceEnabled: false,
    advancePredicts: true,
  }, 1000);
  assert.equal(latched.state, "normal");
  assert.match(alertCopy({ advance: { message: "Insufficient evidence for reliable advance warning" } }, latched.state).label, /Normal/);
});

test("a rise warning describes the latest sample and is omitted when traffic is level", () => {
  assert.equal(riseWarning({ rising: false }), null);
  assert.equal(riseWarning(null), null);
  const text = riseWarning({ rising: true, latest_mbps: 28.52, prior_median_mbps: 3.75 });
  assert.match(text, /already risen/);
  assert.match(text, /not a prediction/);
  assert.match(text, /not the five-minute forecast/);
});

test("a saved-forecast ledger does not invent error before later measurements exist", () => {
  assert.match(ledgerAccuracy(null, 5), /Collecting data/);
  assert.match(
    ledgerAccuracy({ recorded: 4, scored: 1, receive: { one_step: { status: "insufficient_history" } } }, 5),
    /Insufficient history/,
  );
  const text = ledgerAccuracy({
    recorded: 30,
    scored: 15,
    receive: {
      one_step: {
        status: "evaluated",
        methods: {
          exponential_smoothing: { mae: 0.2, rmse: 0.3, n: 5 },
          persistence: { mae: 0.25, rmse: 0.4, n: 5 },
          moving_average: { mae: 0.22, rmse: 0.35, n: 5 },
        },
      },
      horizon: { status: "insufficient_history" },
    },
  }, 5);
  assert.match(text, /later measurement/);
  assert.match(text, /waiting for their target time/);
});

test("stale data and missing capacity do not become an overload warning", () => {
  const stale = trafficOutlook({
    collection: { freshness: "stale", status: "running" },
    current: { quality: "ok", rx_mbps: 10, tx_mbps: 10 },
    forecast: {
      receive: { sufficient: true, point_mbps: 80 },
      transmit: { sufficient: true, point_mbps: 80 },
    },
    capacity: { status: "configured", source: "user", capacity_mbps: 100 },
    evaluation: null,
    horizonSeconds: 900,
  });
  assert.match(stale.trend, /not current/);
  assert.match(stale.overload, /cannot yet be determined/);
});

test("a forecast above a configured capacity is labeled as a comparison", () => {
  const outlook = trafficOutlook({
    collection: { freshness: "fresh", status: "running" },
    current: { quality: "ok", rx_mbps: 1, tx_mbps: 1 },
    forecast: {
      receive: { sufficient: true, point_mbps: 2.5 },
      transmit: { sufficient: true, point_mbps: 1 },
    },
    capacity: { status: "configured", source: "user", capacity_mbps: 2, direction: "per_direction" },
    evaluation: {
      receive: {
        status: "evaluated",
        horizon_evaluation: "pending",
        methods: {
          exponential_smoothing: { mae: 0.2, rmse: 0.3, n: 40 },
          persistence: { mae: 0.25, rmse: 0.4, n: 40 },
          moving_average: { mae: 0.22, rmse: 0.35, n: 40 },
        },
      },
    },
    horizonSeconds: 300,
  });
  assert.match(outlook.trend, /above the recent level/);
  assert.match(outlook.overload, /above the 2\.00 Mbps threshold/);
  assert.match(outlook.overload, /not measured congestion/);
  assert.match(outlook.accuracy, /walk-forward/);
  assert.match(outlook.accuracy, /waiting for later observations/);
});

test("a saved direction threshold is the alert line, not an older capacity value", () => {
  const outlook = trafficOutlook({
    collection: { freshness: "fresh", status: "running" },
    current: { quality: "ok", rx_mbps: 1, tx_mbps: 1 },
    history: [],
    forecast: {
      receive: { sufficient: true, point_mbps: 2 },
      transmit: { sufficient: true, point_mbps: 2 },
    },
    capacity: { status: "configured", source: "user", capacity_mbps: 1, direction: "per_direction" },
    thresholds: { receive: 10, transmit: 10, sources: { receive: "global", transmit: "global" } },
    evaluation: null,
    horizonSeconds: 300,
  });
  assert.match(outlook.overload, /10\.00 Mbps threshold/);
  assert.match(outlook.overload, /older capacity value of 1\.00 Mbps/);
  assert.doesNotMatch(outlook.overload, /above the 1 Mbps/);
});

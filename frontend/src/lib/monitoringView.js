/** Display helpers for measured monitoring values. Null is unavailable, not zero. */

export function displayMbps(value) {
  if (value === null || value === undefined || value === "") return "unavailable";
  const number = Number(value);
  if (!Number.isFinite(number)) return "unavailable";
  if (number === 0) return "0";
  const abs = Math.abs(number);
  if (abs < 0.001) return number.toExponential(2);
  if (abs < 1) return number.toFixed(3);
  return number.toFixed(2);
}

export function displayCount(value) {
  if (value === null || value === undefined || value === "") return "unavailable";
  const number = Number(value);
  if (!Number.isFinite(number)) return "unavailable";
  return number.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

export function formatTimestamp(unixSeconds) {
  if (unixSeconds === null || unixSeconds === undefined || unixSeconds === "") return "unavailable";
  const date = new Date(Number(unixSeconds) * 1000);
  if (Number.isNaN(date.getTime())) return "unavailable";
  return date.toLocaleString();
}

const ALERT_CLEAR_POLLS = 5;
const ACTIVE_STATES = new Set(["traffic_rising", "high_predicted_risk", "threshold_exceeded"]);

/**
 * Hold an alert across a few quiet polls so one burst is one alert.
 * Threshold alerts already have server-side hysteresis, so they are not held here.
 */
export function nextAlertLatch(previous, reading, nowMs) {
  const prior = previous || {
    state: "unavailable",
    since: null,
    clearStreak: 0,
    generation: 0,
    notify: false,
  };
  const observed = reading?.fresh && reading?.quality === "ok";
  let instant = "unavailable";
  if (observed && reading.exceeded) instant = "threshold_exceeded";
  else if (observed && reading.rising) instant = "traffic_rising";
  else if (observed && reading.advanceEnabled && reading.advancePredicts) instant = "high_predicted_risk";
  else if (observed && reading.insufficient) instant = "insufficient_history";
  else if (observed) instant = "normal";

  const active = ACTIVE_STATES.has(prior.state);
  const holdable = prior.state === "traffic_rising" || prior.state === "high_predicted_risk";
  if (holdable && instant !== prior.state && !ACTIVE_STATES.has(instant)) {
    const clearStreak = prior.clearStreak + 1;
    if (clearStreak < ALERT_CLEAR_POLLS) {
      return { ...prior, clearStreak, notify: false };
    }
  }
  if (instant === prior.state) {
    return { ...prior, clearStreak: 0, notify: false, since: prior.since ?? nowMs };
  }
  const entered = ACTIVE_STATES.has(instant) && !active;
  return {
    state: instant,
    since: nowMs,
    clearStreak: 0,
    generation: prior.generation + (entered ? 1 : 0),
    notify: entered,
  };
}

export function alertCopy(alert, latchState) {
  const state = latchState || alert?.state || "unavailable";
  const advance = alert?.advance?.message || "Insufficient evidence for reliable advance warning";
  if (state === "threshold_exceeded") {
    return {
      label: "Threshold exceeded",
      explanation: alert?.state === "threshold_exceeded" && alert?.explanation
        ? alert.explanation
        : "A saved threshold was reached. The alert ends after 3 valid readings below 90% of the threshold.",
    };
  }
  if (state === "insufficient_history") {
    return {
      label: "Insufficient history",
      explanation: alert?.explanation || "Not enough contiguous readings yet on this interface for rise detection.",
    };
  }
  if (state === "traffic_rising") {
    const side = alert?.directions?.includes("transmit") && !alert?.directions?.includes("receive")
      ? alert?.transmit
      : alert?.receive;
    const latest = displayMbps(side?.latest_mbps);
    const prior = displayMbps(side?.prior_median_mbps);
    return {
      label: "Traffic rising",
      explanation: `Burst detected. Throughput has already risen to ${latest} Mbps from a recent level near ${prior} Mbps. This describes the latest sample. It is not a prediction that the rise was coming. ${advance}`,
    };
  }
  if (state === "high_predicted_risk") {
    return {
      label: "Predicted threshold risk",
      explanation: `${alert?.advance?.message || "The checked rule expects the saved threshold to be crossed within 5 minutes."} It does not name the exact start time.`,
    };
  }
  if (state === "normal") {
    const below = alert?.thresholds_mbps && (alert.thresholds_mbps.receive != null || alert.thresholds_mbps.transmit != null)
      ? "Rates are below your saved thresholds and not rising sharply."
      : "No rise is in progress. No threshold is saved.";
    return {
      label: "Normal",
      explanation: `${below} ${advance}`,
    };
  }
  return {
    label: "Collector unavailable or stale",
    explanation: alert?.state === "unavailable" && alert?.explanation
      ? alert.explanation
      : "The latest sample has no rate. Missing samples are not treated as zero, and no alert is issued.",
  };
}

/**
 * Points where a measured series reaches a threshold from below.
 * A gap or an invalid sample breaks the comparison, so a crossing is never
 * inferred across missing data.
 */
export function thresholdCrossings(history, field, threshold) {
  const limit = finite(threshold);
  if (limit === null || limit <= 0) return [];
  const crossings = [];
  let previous = null;
  for (const row of history || []) {
    const value = row?.quality === "ok" ? finite(row?.[field]) : null;
    if (value === null) {
      previous = null;
      continue;
    }
    if (previous !== null && previous < limit && value >= limit) {
      crossings.push({ sampled_at: row.sampled_at, mbps: value });
    }
    previous = value;
  }
  return crossings;
}

export function directionWord(side) {
  return side === "transmit" ? "upload" : "download";
}

export function percent(value) {
  const number = finite(value);
  return number === null ? "n/a" : `${(number * 100).toFixed(1)}%`;
}

export function mbpsMetric(value) {
  const number = finite(value);
  return number === null ? "n/a" : number.toFixed(3);
}

export function riseWarning(rise) {
  if (!rise?.rising) return null;
  const latest = displayMbps(rise.latest_mbps);
  const prior = displayMbps(rise.prior_median_mbps);
  return `Download has already risen to ${latest} Mbps from a recent level near ${prior} Mbps. This describes the latest sample. It is not a prediction that the rise was coming, and it is not the five-minute forecast.`;
}

export function metricState(value) {
  return value === null || value === undefined ? "unavailable" : "measured";
}

const STABLE_FRACTION = 0.15;
const STABLE_FLOOR_MBPS = 0.05;

function finite(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function recentLevel(history, field, fallback) {
  const values = (history || [])
    .filter((row) => row?.quality === "ok")
    .map((row) => finite(row?.[field]))
    .filter((value) => value !== null)
    .slice(-12);
  if (values.length < 2) return finite(fallback);
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function band(latest) {
  return Math.max(STABLE_FLOOR_MBPS, Math.abs(latest) * STABLE_FRACTION);
}

/** stable, increase, decrease, or unknown. A flat forecast is not a spike time. */
export function levelShift(latest, forecast) {
  const observed = finite(latest);
  const predicted = finite(forecast);
  if (observed === null || predicted === null) return "unknown";
  const delta = predicted - observed;
  if (Math.abs(delta) <= band(observed)) return "stable";
  return delta > 0 ? "increase" : "decrease";
}

function metricLine(metrics) {
  if (!metrics || metrics.mae == null || metrics.rmse == null) return "pending";
  return `MAE ${Number(metrics.mae).toFixed(3)}, RMSE ${Number(metrics.rmse).toFixed(3)} Mbps (n=${metrics.n})`;
}

/**
 * Business summary from a real forecast payload.
 * Missing rates stay unresolved. Training error is never described as test error.
 */
export function ledgerAccuracy(ledger, minutes) {
  if (!ledger || !ledger.recorded) {
    return "Collecting data. Forecasts are saved as readings arrive and scored when the target time is observed.";
  }
  const oneStep = ledger.receive?.one_step;
  const horizon = ledger.receive?.horizon;
  if (!oneStep || oneStep.status !== "evaluated") {
    return `Insufficient history. ${ledger.recorded} forecasts are saved and ${ledger.scored ?? 0} have a later measurement. Training error is not shown.`;
  }
  const methods = oneStep.methods || {};
  let text = `Saved download forecasts checked against a later measurement: smoothing ${metricLine(methods.exponential_smoothing)}; persistence ${metricLine(methods.persistence)}; moving average ${metricLine(methods.moving_average)}.`;
  if (horizon?.status === "evaluated") {
    text += ` At ${minutes} minutes, smoothing ${metricLine(horizon.methods?.exponential_smoothing)}.`;
  } else {
    text += ` The ${minutes}-minute saved forecasts are still waiting for their target time.`;
  }
  return text;
}

export function trafficOutlook({ collection, current, history, forecast, capacity, thresholds, evaluation, ledger, horizonSeconds }) {
  const minutes = Math.max(1, Math.round(Number(horizonSeconds) / 60));
  const freshness = collection?.freshness;
  const currentEnough = freshness === "fresh" && current?.quality === "ok";
  const receiveForecast = forecast?.receive?.sufficient ? finite(forecast.receive.point_mbps) : null;
  const transmitForecast = forecast?.transmit?.sufficient ? finite(forecast.transmit.point_mbps) : null;
  const forecastReady = receiveForecast !== null && transmitForecast !== null;

  let trend = "Waiting for enough evenly spaced readings before a forecast is shown.";
  if (freshness === "stale" || collection?.status === "error" || collection?.status === "interface_unavailable") {
    trend = "Monitoring is not current, so the forecast is not treated as a live estimate.";
  } else if (!currentEnough) {
    trend = "The latest reading has no rate yet. A blank rate is a missing sample, not zero traffic.";
  } else if (!forecastReady) {
    const used = forecast?.receive?.observations_used ?? 0;
    const minimum = forecast?.receive?.minimum_observations ?? 2;
    trend = `Waiting for data. The latest evenly spaced run has ${used} readings and this forecast needs ${minimum}.`;
  } else {
    const download = levelShift(recentLevel(history, "rx_mbps", current.rx_mbps), receiveForecast);
    const upload = levelShift(recentLevel(history, "tx_mbps", current.tx_mbps), transmitForecast);
    const shifts = [download, upload].filter((item) => item !== "unknown");
    if (shifts.length < 2) {
      trend = "A forecast cannot be compared until both download and upload have a measured latest rate.";
    } else if (shifts.every((item) => item === "stable")) {
      trend = `Traffic is expected to stay near the recent level for about ${minutes} minutes.`;
    } else if (shifts.every((item) => item === "increase" || item === "stable") && shifts.includes("increase")) {
      trend = `Traffic is expected to sit above the recent level for about ${minutes} minutes.`;
    } else if (shifts.every((item) => item === "decrease" || item === "stable") && shifts.includes("decrease")) {
      trend = `Traffic is expected to ease back from the recent level over about ${minutes} minutes.`;
    } else {
      trend = `Download and upload are not expected to move the same way over about ${minutes} minutes.`;
    }
    trend += " The line is a smoothed level held flat. It does not name a future spike or peak time, and it is only this computer.";
  }

  const legacy = capacity?.status === "configured" && capacity?.source === "user" ? finite(capacity.capacity_mbps) : null;
  const downloadLimit = finite(thresholds?.receive) ?? (capacity?.direction === "transmit_only" ? null : legacy);
  const uploadLimit = finite(thresholds?.transmit) ?? (capacity?.direction === "receive_only" ? null : legacy);
  const configured = downloadLimit !== null || uploadLimit !== null;
  let overload = "Overload risk cannot yet be determined.";
  if (!forecastReady || freshness !== "fresh") {
    overload = "Overload risk cannot yet be determined. The forecast is not current or does not have enough history.";
  } else if (!configured) {
    overload = "Overload risk cannot yet be determined. No threshold has been entered. Adapter link speed is not used.";
  } else {
    const pairs = [];
    if (downloadLimit !== null) pairs.push(["Download", receiveForecast, downloadLimit]);
    if (uploadLimit !== null) pairs.push(["Upload", transmitForecast, uploadLimit]);
    const worst = pairs.reduce((best, item) => (item[1] / item[2] > best[1] / best[2] ? item : best), pairs[0]);
    const pct = (worst[1] / worst[2]) * 100;
    const warning = finite(capacity?.warning_utilization_pct);
    if (pct >= 100) {
      overload = `${worst[0]} forecast ${displayMbps(worst[1])} Mbps is above the ${displayMbps(worst[2])} Mbps threshold used by the chart and the alert. That is a comparison with the number you entered, not measured congestion.`;
    } else if (warning !== null && pct >= warning) {
      overload = `${worst[0]} forecast is ${pct.toFixed(0)}% of the ${displayMbps(worst[2])} Mbps threshold, at or above the warning mark of ${warning}%. This is not measured congestion.`;
    } else {
      overload = `The forecast stays below the ${displayMbps(worst[2])} Mbps threshold used by the chart and the alert. This is only this computer, and it is not a congestion finding.`;
    }
    if (legacy !== null && ((downloadLimit !== null && downloadLimit !== legacy) || (uploadLimit !== null && uploadLimit !== legacy))) {
      overload += ` An older capacity value of ${displayMbps(legacy)} Mbps is saved and is not the alert line.`;
    }
  }

  const receiveEval = evaluation?.receive;
  let accuracy = ledger
    ? ledgerAccuracy(ledger, minutes)
    : "Out-of-sample error is not available yet. Training error is not shown in its place.";
  if (!ledger && receiveEval?.status === "evaluated") {
    const methods = receiveEval.methods || {};
    accuracy = `Download one-step walk-forward: smoothing ${metricLine(methods.exponential_smoothing)}; persistence ${metricLine(methods.persistence)}; moving average ${metricLine(methods.moving_average)}.`;
    if (receiveEval.horizon_evaluation === "evaluated" && methods.exponential_smoothing?.horizon) {
      accuracy += ` At ${minutes} minutes, smoothing ${metricLine(methods.exponential_smoothing.horizon)}. That score uses the same flat level against a later actual.`;
    } else {
      accuracy += ` The ${minutes}-minute score is waiting for later observations.`;
    }
  }

  return { trend, overload, accuracy };
}

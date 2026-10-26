import { useEffect, useRef } from "react";
import Plotly from "plotly.js-dist-min";
import { thresholdCrossings } from "../lib/monitoringView";

const PLOT_CONFIG = { responsive: true, displayModeBar: false };
const COLORS = {
  download: "#22d3ee",
  upload: "#a78bfa",
  downloadForecast: "#67e8f9",
  uploadForecast: "#ddd6fe",
  downloadThreshold: "#f59e0b",
  uploadThreshold: "#f472b6",
};
const OVERLAY_START = 2;

function stamp(unixSeconds) {
  return new Date(unixSeconds * 1000);
}

function measured(point, field) {
  return point.quality === "ok" ? point[field] : null;
}

/** Break the line where readings are missing, so a collection gap is never drawn as traffic. */
function seriesWithGaps(points, gapSeconds, previous = null) {
  const x = [];
  const rx = [];
  const tx = [];
  let last = previous;
  for (const point of points) {
    if (last && point.sampled_at - last.sampled_at > gapSeconds) {
      x.push(stamp((last.sampled_at + point.sampled_at) / 2));
      rx.push(null);
      tx.push(null);
    }
    x.push(stamp(point.sampled_at));
    rx.push(measured(point, "rx_mbps"));
    tx.push(measured(point, "tx_mbps"));
    last = point;
  }
  return { x, rx, tx };
}

function lineTrace(x, y, name, color, dash, extra = {}) {
  return {
    x,
    y,
    type: "scatter",
    mode: "lines",
    name,
    connectgaps: false,
    line: { color, width: 2, dash },
    hovertemplate: "%{y:.3f} Mbps<extra>%{fullData.name}</extra>",
    ...extra,
  };
}

function forecastTrace(series, name, color) {
  const ready = series?.sufficient && series.series?.length;
  return lineTrace(
    ready ? series.series.map((point) => stamp(point.timestamp)) : [],
    ready ? series.series.map((point) => point.mbps) : [],
    name,
    color,
    "dash",
    { showlegend: Boolean(ready) },
  );
}

function crossingTrace(history, field, threshold, name, color) {
  const points = thresholdCrossings(history, field, threshold);
  return {
    x: points.map((point) => stamp(point.sampled_at)),
    y: points.map((point) => point.mbps),
    type: "scatter",
    mode: "markers",
    name,
    marker: { color, size: 9, symbol: "triangle-up", line: { color: "#0f172a", width: 1 } },
    hovertemplate: "Reached threshold: %{y:.3f} Mbps<extra>%{fullData.name}</extra>",
    showlegend: points.length > 0,
  };
}

function overlays(history, forecast, thresholds) {
  return [
    forecastTrace(forecast?.receive, "Download forecast", COLORS.downloadForecast),
    forecastTrace(forecast?.transmit, "Upload forecast", COLORS.uploadForecast),
    crossingTrace(history, "rx_mbps", thresholds?.receive, "Download crossed threshold", COLORS.downloadThreshold),
    crossingTrace(history, "tx_mbps", thresholds?.transmit, "Upload crossed threshold", COLORS.uploadThreshold),
  ];
}

function thresholdShapes(thresholds) {
  const shapes = [];
  const annotations = [];
  const down = thresholds?.receive;
  const up = thresholds?.transmit;
  const add = (value, color, text, yshift) => {
    shapes.push({
      type: "line",
      xref: "paper",
      x0: 0,
      x1: 1,
      y0: value,
      y1: value,
      line: { color, width: 1.5, dash: "dot" },
    });
    annotations.push({
      xref: "paper",
      x: 1,
      y: value,
      xanchor: "right",
      yanchor: "bottom",
      yshift,
      text,
      showarrow: false,
      font: { size: 10, color },
    });
  };
  if (down != null && up != null && down === up) {
    add(down, COLORS.downloadThreshold, `Download & upload threshold ${down} Mbps`, 0);
  } else {
    if (down != null) add(down, COLORS.downloadThreshold, `Download threshold ${down} Mbps`, 0);
    if (up != null) add(up, COLORS.uploadThreshold, `Upload threshold ${up} Mbps`, down != null && Math.abs(down - up) < 0.05 * Math.max(down, up) ? -14 : 0);
  }
  return { shapes, annotations };
}

const TRANSITION_TEXT = {
  user_selected: "Interface changed",
  auto_selected: "Auto interface",
  default_route_changed: "Route moved",
  network_address_changed: "Network changed",
};

function buildLayout(forecast, thresholds, transitions, windowStart) {
  const { shapes, annotations } = thresholdShapes(thresholds);
  const origin = forecast?.receive?.origin_timestamp || forecast?.transmit?.origin_timestamp;
  if (origin && (forecast?.receive?.sufficient || forecast?.transmit?.sufficient)) {
    shapes.push({
      type: "line",
      x0: stamp(origin),
      x1: stamp(origin),
      yref: "paper",
      y0: 0,
      y1: 1,
      line: { color: "#64748b", width: 1, dash: "dot" },
    });
  }
  let labeledAt = null;
  const ordered = [...(transitions || [])].sort((a, b) => a.at - b.at);
  for (const item of ordered) {
    if (windowStart != null && item.at < windowStart) continue;
    shapes.push({
      type: "line",
      x0: stamp(item.at),
      x1: stamp(item.at),
      yref: "paper",
      y0: 0,
      y1: 1,
      line: { color: "#34d399", width: 1.5, dash: "dash" },
    });
    if (labeledAt !== null && item.at - labeledAt < 60) continue;
    labeledAt = item.at;
    annotations.push({
      x: stamp(item.at),
      yref: "paper",
      y: 0.98,
      yanchor: "top",
      xanchor: "right",
      textangle: -90,
      text: TRANSITION_TEXT[item.reason] || "Transition",
      showarrow: false,
      font: { size: 10, color: "#6ee7b7" },
    });
  }
  return {
    autosize: true,
    height: 340,
    margin: { t: 36, r: 24, b: 40, l: 56 },
    paper_bgcolor: "transparent",
    plot_bgcolor: "transparent",
    font: { color: "#94a3b8", family: "system-ui, sans-serif", size: 11 },
    legend: { orientation: "h", y: 1.2, font: { size: 11, color: "#cbd5e1" } },
    hovermode: "x unified",
    hoverlabel: { bgcolor: "#0f172a", bordercolor: "#334155", font: { color: "#e2e8f0" } },
    xaxis: { gridcolor: "rgba(51, 65, 85, 0.4)", title: { text: "Time" } },
    yaxis: {
      gridcolor: "rgba(51, 65, 85, 0.4)",
      title: { text: "Mbps", font: { color: "#cbd5e1", size: 11 } },
      rangemode: "tozero",
    },
    shapes,
    annotations,
  };
}

/**
 * Measured throughput, saved thresholds, threshold crossings, interface
 * transitions, and a separate flat forecast. Gaps stay empty.
 * New samples extend the existing lines instead of redrawing the whole history.
 */
export default function ThroughputChart({
  history = [],
  forecast,
  thresholds,
  transitions = [],
  downsampled = false,
  sampleInterval = 1,
  windowStart = null,
}) {
  const plotRef = useRef(null);
  const plottedRef = useRef(null);

  const hasMeasured = history.some(
    (point) => point.quality === "ok" && (point.rx_mbps !== null || point.tx_mbps !== null),
  );

  useEffect(() => {
    const element = plotRef.current;
    if (!element || !hasMeasured) return undefined;

    const bucket = downsampled ? Number(history[history.length - 1]?.interval_seconds) || sampleInterval : sampleInterval;
    const gapSeconds = Math.max(3 * bucket, 5);
    const layout = buildLayout(forecast, thresholds, transitions, windowStart);
    const overlayTraces = overlays(history, forecast, thresholds);
    const lastAt = history[history.length - 1]?.sampled_at;
    const plotted = plottedRef.current;
    const previousIndex = plotted && !downsampled ? history.findIndex((point) => point.sampled_at === plotted.lastAt) : -1;
    const fresh = previousIndex >= 0 ? history.slice(previousIndex + 1) : history;
    const canExtend = plotted && element.data && previousIndex >= 0 && fresh.length > 0 && fresh.length <= 5;

    const drawAll = () => {
      const series = seriesWithGaps(history, gapSeconds);
      const traces = [
        lineTrace(series.x, series.rx, "Download", COLORS.download),
        lineTrace(series.x, series.tx, "Upload", COLORS.upload),
        ...overlayTraces,
      ];
      Plotly.react(element, traces, layout, PLOT_CONFIG);
      plottedRef.current = { lastAt };
    };

    const moveOverlays = () => {
      Plotly.restyle(
        element,
        {
          x: overlayTraces.map((trace) => trace.x),
          y: overlayTraces.map((trace) => trace.y),
          showlegend: overlayTraces.map((trace) => trace.showlegend),
        },
        overlayTraces.map((_, index) => index + OVERLAY_START),
      );
      Plotly.relayout(element, { shapes: layout.shapes, annotations: layout.annotations });
    };

    if (plotted && element.data && previousIndex === history.length - 1) {
      moveOverlays();
    } else if (!canExtend) {
      drawAll();
    } else {
      const series = seriesWithGaps(fresh, gapSeconds, history[previousIndex]);
      Plotly.extendTraces(element, { x: [series.x, series.x], y: [series.rx, series.tx] }, [0, 1], history.length + 50);
      moveOverlays();
      plottedRef.current = { lastAt };
    }

    return undefined;
  }, [history, forecast, thresholds, transitions, hasMeasured, downsampled, sampleInterval, windowStart]);

  useEffect(() => {
    const element = plotRef.current;
    return () => {
      plottedRef.current = null;
      if (element) Plotly.purge(element);
    };
  }, []);

  if (!hasMeasured) {
    return (
      <p className="text-sm text-slate-400 py-10 text-center" id="throughput-chart-empty">
        Waiting for data. The first counter reading has no rate yet, and missing samples stay blank rather than zero.
      </p>
    );
  }

  return (
    <div id="throughput-chart">
      <div ref={plotRef} style={{ width: "100%", height: "340px" }} role="img" aria-label="Download and upload throughput over time with saved thresholds" />
      {downsampled && (
        <p className="text-xs text-slate-500 mt-1">Long window: each point is the highest reading in its time bucket, so short peaks stay visible.</p>
      )}
    </div>
  );
}

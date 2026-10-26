import { useState } from "react";
import { fetchDiagnostics, runCaptureComparison } from "../services/api";
import { displayMbps, mbpsMetric, percent } from "../lib/monitoringView";

const METHOD_NAMES = {
  persistence: "Persistence",
  moving_average: "Moving average (12)",
  exponential_smoothing: "Smoothing (α 0.3)",
  holt: "Holt trend",
};
const HORIZON_NAMES = { 60: "1 min", 300: "5 min", 900: "15 min" };

function sentence(text) {
  return text ? text[0].toUpperCase() + text.slice(1) : text;
}

function AccuracyTable({ block, direction }) {
  const horizons = Object.keys(block || {});
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs text-slate-300">
        <caption className="text-left text-slate-200 font-medium pb-1">{sentence(direction)} walk-forward error (Mbps)</caption>
        <thead className="text-slate-500">
          <tr>
            <th scope="col" className="text-left font-normal">Horizon</th>
            <th scope="col" className="text-left font-normal">Method</th>
            <th scope="col" className="text-right font-normal">MAE</th>
            <th scope="col" className="text-right font-normal">RMSE</th>
            <th scope="col" className="text-right font-normal">n</th>
            <th scope="col" className="text-right font-normal">Quiet MAE (n)</th>
            <th scope="col" className="text-right font-normal">Burst MAE (n)</th>
          </tr>
        </thead>
        <tbody>
          {horizons.map((horizon) => {
            const item = block[horizon];
            return Object.keys(METHOD_NAMES).map((method, index) => {
              const metrics = item.methods?.[method] || {};
              const quiet = item.quiet?.[method] || {};
              const burst = item.burst?.[method] || {};
              const best = item.best_by_mae === method;
              return (
                <tr key={`${horizon}-${method}`} className={index === 0 ? "border-t border-slate-800" : ""}>
                  <td className="py-0.5">{index === 0 ? `${HORIZON_NAMES[horizon] || `${horizon}s`} · coverage ${percent(item.target_coverage)}` : ""}</td>
                  <td className={best ? "text-emerald-200" : ""}>{METHOD_NAMES[method]}{best ? " · best" : ""}</td>
                  <td className="text-right">{mbpsMetric(metrics.mae)}</td>
                  <td className="text-right">{mbpsMetric(metrics.rmse)}</td>
                  <td className="text-right">{metrics.n ?? 0}</td>
                  <td className="text-right">{mbpsMetric(quiet.mae)} ({quiet.n ?? 0})</td>
                  <td className="text-right">{mbpsMetric(burst.mae)} ({burst.n ?? 0})</td>
                </tr>
              );
            });
          })}
        </tbody>
      </table>
    </div>
  );
}

function AdvanceTable({ report, direction }) {
  if (!report) {
    return <p className="text-xs text-slate-500">{sentence(direction)}: no threshold saved, so no crossings to score.</p>;
  }
  const rows = ["recent_slope", "exponential_smoothing", "moving_average", "persistence", "never"];
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs text-slate-300">
        <caption className="text-left text-slate-200 font-medium pb-1">
          {sentence(direction)} crossings of {report.threshold_mbps} Mbps within 5 min · {report.events} events · gate {report.gate_enabled ? "passed" : "not passed"}
        </caption>
        <thead className="text-slate-500">
          <tr>
            <th scope="col" className="text-left font-normal">Rule</th>
            <th scope="col" className="text-right font-normal">Precision</th>
            <th scope="col" className="text-right font-normal">Recall</th>
            <th scope="col" className="text-right font-normal">False-positive rate</th>
            <th scope="col" className="text-right font-normal">Missed events</th>
            <th scope="col" className="text-right font-normal">Mean lead</th>
            <th scope="col" className="text-right font-normal">Warnings / origins</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((name) => {
            const item = report.methods?.[name] || {};
            return (
              <tr key={name} className="border-t border-slate-800">
                <td className="py-0.5">{name === "recent_slope" ? "Recent slope (candidate)" : METHOD_NAMES[name] || "Never warn"}</td>
                <td className="text-right">{percent(item.precision)}</td>
                <td className="text-right">{percent(item.event_recall)}</td>
                <td className="text-right">{percent(item.false_positive_rate)}</td>
                <td className="text-right">{percent(item.missed_event_rate)}</td>
                <td className="text-right">{item.mean_lead_steps == null ? "n/a" : `${Math.round(item.mean_lead_steps)} s`}</td>
                <td className="text-right">{item.warnings ?? 0} / {item.origins ?? 0}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function CaptureResult({ result }) {
  if (!result) return null;
  if (result.status !== "ok") {
    return <p className="text-xs text-amber-200" id="capture-result">Packet capture {result.status.replaceAll("_", " ")}: {result.error}</p>;
  }
  return (
    <p className="text-xs text-slate-300" id="capture-result">
      Over {result.elapsed_seconds.toFixed(1)} s, packet capture saw {displayMbps(result.packet.rx_mbps)} Mbps down and {displayMbps(result.packet.tx_mbps)} Mbps up.
      The OS counters saw {displayMbps(result.counters?.rx_mbps)} and {displayMbps(result.counters?.tx_mbps)} Mbps.
      Capture observed {percent(result.packet_coverage?.rx)} of received and {percent(result.packet_coverage?.tx)} of sent packets.
      The stored values stay the OS counters. The two are compared, never added.
    </p>
  );
}

export default function DiagnosticsPanel() {
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [capture, setCapture] = useState(null);
  const [capturing, setCapturing] = useState(false);

  const load = async (refresh = false) => {
    setLoading(true);
    try {
      setReport(await fetchDiagnostics(refresh));
      setError(null);
    } catch (err) {
      setError(err.message || "Could not compute diagnostics");
    } finally {
      setLoading(false);
    }
  };

  const compare = async () => {
    setCapturing(true);
    try {
      setCapture(await runCaptureComparison(5));
    } catch (err) {
      setCapture({ status: "error", error: err.message || "Capture comparison failed" });
    } finally {
      setCapturing(false);
    }
  };

  const quality = report?.data_quality;
  return (
    <section className="glass-panel rounded-2xl p-4 sm:p-5 space-y-4" id="diagnostics" aria-labelledby="diagnostics-heading">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 id="diagnostics-heading" className="text-base font-semibold text-white">Diagnostics</h2>
          <p className="text-sm text-slate-400">Walk-forward scores on stored readings from this interface. Each forecast uses only earlier readings.</p>
        </div>
        <div className="flex gap-2">
          <button type="button" className="px-3 py-1.5 rounded-lg bg-indigo-600 text-sm text-white disabled:opacity-60" onClick={() => load(Boolean(report))} disabled={loading}>
            {loading ? "Computing…" : report ? "Refresh" : "Load diagnostics"}
          </button>
          <button type="button" className="px-3 py-1.5 rounded-lg border border-slate-700 text-sm text-slate-200 disabled:opacity-60" onClick={compare} disabled={capturing}>
            {capturing ? "Capturing 5 s…" : "Compare with packet capture"}
          </button>
        </div>
      </div>
      {error && <p className="text-sm text-rose-200" role="alert">{error}</p>}
      <CaptureResult result={capture} />
      {report?.status === "ok" && (
        <div className="space-y-4" id="diagnostics-body">
          <p className="text-xs text-slate-400" id="diagnostics-quality">
            {quality.valid_observations} valid of {quality.observations} readings over {(quality.duration_seconds / 3600).toFixed(2)} h ·
            valid-time coverage {percent(quality.valid_time_coverage)} · interval p50 {quality.interval_p50_seconds?.toFixed(2)} s, p95 {quality.interval_p95_seconds?.toFixed(2)} s ·
            {" "}{quality.irregular_intervals} irregular intervals · {quality.contiguous_runs} contiguous runs, longest {quality.longest_run} readings.
          </p>
          <AccuracyTable block={report.walk_forward.receive} direction="download" />
          <AccuracyTable block={report.walk_forward.transmit} direction="upload" />
          <p className="text-xs text-slate-500">
            Holt is used only if it beats every baseline on both MAE and RMSE. Justified here: download 5 min {report.walk_forward.receive["300"]?.holt_justified ? "yes" : "no"}, upload 5 min {report.walk_forward.transmit["300"]?.holt_justified ? "yes" : "no"}.
            A horizon with n = 0 has no run long enough to score it. {report.walk_forward.parameters.burst_rule}.
          </p>
          <AdvanceTable report={report.advance_warning.receive} direction="download" />
          <AdvanceTable report={report.advance_warning.transmit} direction="upload" />
          <p className="text-xs text-slate-500">{report.advance_warning.note}</p>
        </div>
      )}
    </section>
  );
}

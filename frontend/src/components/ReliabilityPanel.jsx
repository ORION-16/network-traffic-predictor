import { useState } from "react";
import { fetchReliability } from "../services/api";

function mbps(value) {
  return value == null ? "unavailable" : `${Number(value).toFixed(3)} Mbps`;
}

export default function ReliabilityPanel() {
  const [report, setReport] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  const measure = async () => {
    setLoading(true);
    try {
      setReport(await fetchReliability());
      setError(null);
    } catch (err) {
      setError(err.message || "Could not measure reliability");
    } finally {
      setLoading(false);
    }
  };

  const sampling = report?.sampling;
  const write = report?.sqlite_write;
  const retention = report?.retention;
  const process = report?.process;
  return (
    <details className="glass-panel rounded-2xl p-4 sm:p-5 space-y-3" id="reliability">
      <summary className="cursor-pointer list-none" id="reliability-heading">
        <span className="text-base font-semibold text-white">Reliability</span>
        <span className="mt-1 block text-sm text-slate-400">Sampling comes from stored readings. Write, load, and retention checks use a temporary database. This does not generate network traffic.</span>
      </summary>
      <div className="flex justify-end pt-3">
        <button type="button" className="px-3 py-1.5 rounded-lg bg-indigo-600 text-sm text-white disabled:opacity-60" onClick={measure} disabled={loading}>
          {loading ? "Measuring…" : "Measure now"}
        </button>
      </div>
      {error && <p className="text-sm text-rose-200" role="alert">{error}</p>}
      {report && (
        <div className="space-y-3 text-xs text-slate-300" id="reliability-report">
          <p>
            Stored intervals: median {sampling.interval_p50_seconds == null ? "n/a" : `${sampling.interval_p50_seconds.toFixed(3)} s`},
            p95 {sampling.interval_p95_seconds == null ? "n/a" : `${sampling.interval_p95_seconds.toFixed(3)} s`},
            max {sampling.interval_max_seconds == null ? "n/a" : `${sampling.interval_max_seconds.toFixed(3)} s`}.
            Invalid intervals {sampling.invalid_intervals}. Valid zero rates {sampling.valid_zero_rates}.
          </p>
          <p>
            Temporary SQLite: {write.rows} rows, median write {write.median_write_ms.toFixed(3)} ms, p95 {write.p95_write_ms.toFixed(3)} ms,
            {write.rows_per_second.toFixed(0)} rows/s. Retention deleted {retention.deleted_rows} expired row(s) and kept {retention.rows_kept}.
            Process CPU {process.cpu_percent.toFixed(1)}% over {process.interval_seconds}s, memory {(process.rss_bytes / 1_048_576).toFixed(1)} MB.
          </p>
          <p id="api-latency">
            {report.api_latency?.status === "measured"
              ? `Health API: median ${report.api_latency.median_ms.toFixed(1)} ms, max ${report.api_latency.max_ms.toFixed(1)} ms over ${report.api_latency.samples} requests.`
              : `Health API was not measured${report.api_latency?.error ? `: ${report.api_latency.error}` : ""}.`}
          </p>
          {report.write_load?.length > 0 && (
            <table className="w-full" id="write-load">
              <caption className="text-left text-slate-200 pb-1">SQLite insert load in this process. Not a network-link test.</caption>
              <thead className="text-slate-500">
                <tr>
                  <th scope="col" className="text-left font-normal align-bottom px-1">Level</th>
                  <th scope="col" className="text-right font-normal align-bottom px-1">Rows</th>
                  <th scope="col" className="text-right font-normal align-bottom px-1">Rows/s</th>
                  <th scope="col" className="text-right font-normal align-bottom px-1">CPU %</th>
                  <th scope="col" className="text-right font-normal align-bottom px-1">RSS after</th>
                </tr>
              </thead>
              <tbody>
                {report.write_load.map((item) => (
                  <tr key={item.level} className="border-t border-slate-800">
                    <td className="py-0.5 capitalize">{item.level}</td>
                    <td className="text-right">{item.rows_written}</td>
                    <td className="text-right">{item.rows_per_second?.toFixed(0)}</td>
                    <td className="text-right">{item.cpu_percent?.toFixed(1)}</td>
                    <td className="text-right">{(item.rss_after_bytes / 1_048_576).toFixed(1)} MB</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <table className="w-full">
            <caption className="text-left text-slate-200 pb-1">Controlled counter cases</caption>
            <thead className="text-slate-500">
              <tr>
                <th scope="col" className="text-left font-normal">Case</th>
                <th scope="col" className="text-left font-normal">Quality</th>
                <th scope="col" className="text-right font-normal">Download</th>
                <th scope="col" className="text-right font-normal">Upload</th>
              </tr>
            </thead>
            <tbody>
              {report.controlled_counters.map((item) => (
                <tr key={item.case} className="border-t border-slate-800">
                  <td className="py-0.5">{item.case.replaceAll("_", " ")}</td>
                  <td>{item.quality}</td>
                  <td className="text-right">{mbps(item.rx_mbps)}</td>
                  <td className="text-right">{mbps(item.tx_mbps)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-slate-500">{report.limitations}</p>
        </div>
      )}
    </details>
  );
}

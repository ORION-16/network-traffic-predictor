import { useCallback, useEffect, useState } from "react";
import ErrorAlert from "../components/ErrorAlert";
import AlertPanel from "../components/AlertPanel";
import DiagnosticsPanel from "../components/DiagnosticsPanel";
import ThroughputChart from "../charts/ThroughputChart";
import { useMonitoring } from "../hooks/useMonitoring";
import {
  clearCapacity,
  clearProfileThresholds,
  fetchMonitoringInterfaces,
  saveForecastHorizon,
  saveProfileThresholds,
  saveThresholds,
  selectAutoInterface,
  selectMonitoringInterface,
} from "../services/api";
import { alertCopy, displayMbps, formatTimestamp, nextAlertLatch, riseWarning, trafficOutlook } from "../lib/monitoringView";

const FORECAST_DEFAULTS = {
  method: "exponential_smoothing",
  window: 12,
  alpha: 0.3,
};
const WINDOWS = [
  { seconds: 300, label: "5 min" },
  { seconds: 900, label: "15 min" },
  { seconds: 3600, label: "1 hour" },
];
const SOURCE_TEXT = { user: "you entered", capacity: "saved capacity", global: "all interfaces", profile: "this interface only", unset: "not set" };

function parseThreshold(text) {
  if (text.trim() === "") return { value: undefined };
  const value = Number(text);
  if (!Number.isFinite(value) || value <= 0) return { error: "Thresholds must be numbers greater than 0 Mbps." };
  if (value > 1_000_000) return { error: "Thresholds must be at most 1,000,000 Mbps." };
  return { value };
}

function Stat({ label, value, id, tone = "text-white" }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className={`text-sm font-medium truncate ${tone}`} id={id} title={typeof value === "string" ? value : undefined}>{value}</dd>
    </div>
  );
}

export default function Dashboard() {
  const [horizon, setHorizon] = useState(300);
  const [historySeconds, setHistorySeconds] = useState(900);
  const [interfaces, setInterfaces] = useState([]);
  const [actionError, setActionError] = useState(null);
  const [downloadInput, setDownloadInput] = useState("");
  const [uploadInput, setUploadInput] = useState("");
  const [profileOnly, setProfileOnly] = useState(false);
  const [savedNote, setSavedNote] = useState(null);
  const [latch, setLatch] = useState(null);
  const [notificationPermission, setNotificationPermission] = useState(() => (
    typeof Notification === "undefined" ? "unsupported" : Notification.permission
  ));
  const { data, error: monitoringError, loading, reload } = useMonitoring({ ...FORECAST_DEFAULTS, horizon, historySeconds });

  const loadInterfaces = useCallback(async () => {
    try {
      const payload = await fetchMonitoringInterfaces();
      setInterfaces(payload.interfaces || []);
    } catch (err) {
      setActionError(err.message || "Could not list network interfaces");
    }
  }, []);

  useEffect(() => {
    loadInterfaces();
  }, [loadInterfaces]);

  useEffect(() => {
    const alert = data?.rise_alert;
    setLatch((previous) => nextAlertLatch(previous, {
      fresh: data?.collection?.freshness === "fresh",
      quality: data?.current?.quality,
      exceeded: alert?.state === "threshold_exceeded",
      rising: Boolean(alert?.rising),
      insufficient: alert?.state === "insufficient_history",
      advanceEnabled: Boolean(alert?.advance?.enabled),
      advancePredicts: Boolean(alert?.advance?.predicts),
    }, Date.now()));
  }, [data]);

  useEffect(() => {
    if (!latch?.notify || notificationPermission !== "granted" || typeof Notification === "undefined") return;
    const copy = alertCopy(data?.rise_alert, latch.state);
    try {
      new Notification(copy.label, { body: copy.explanation });
    } catch {
      // The panel is the alert of record when the browser refuses the notice.
    }
    // Generation changes only when an alert begins.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [latch?.generation, notificationPermission]);

  const collection = data?.collection;
  const current = data?.current;
  const thresholds = data?.thresholds;
  const outlook = trafficOutlook({
    collection,
    current,
    history: data?.history,
    forecast: data?.forecast,
    capacity: data?.capacity,
    evaluation: data?.evaluation,
    ledger: data?.forecast_ledger,
    horizonSeconds: horizon,
  });
  const dataset = data?.dataset;
  const measuredNow = current?.quality === "ok" && collection?.freshness === "fresh";
  const downloadNow = measuredNow ? `${displayMbps(current?.rx_mbps)} Mbps` : "unavailable";
  const uploadNow = measuredNow ? `${displayMbps(current?.tx_mbps)} Mbps` : "unavailable";
  const statusError = monitoringError || collection?.error || actionError;
  const alertView = alertCopy(data?.rise_alert, latch?.state);
  const selected = collection?.selected_interface;
  const selectedRecord = interfaces.find((item) => item.name === selected) || data?.interface;
  const mode = collection?.interface_mode || data?.profiles?.mode || "manual";
  const profile = data?.profiles?.items?.find((item) => item.selected);
  const freshnessTone = collection?.freshness === "fresh" ? "text-emerald-200" : collection?.freshness ? "text-amber-200" : "text-slate-300";

  const allowNotifications = async () => {
    if (typeof Notification === "undefined") {
      setNotificationPermission("unsupported");
      return;
    }
    setNotificationPermission(await Notification.requestPermission());
  };

  const onInterface = async (value) => {
    try {
      if (value === "__auto__") await selectAutoInterface();
      else await selectMonitoringInterface(value);
      setActionError(null);
      await Promise.all([reload(), loadInterfaces()]);
    } catch (err) {
      setActionError(err.message || "Could not select that interface");
    }
  };

  const onSaveThresholds = async (event) => {
    event.preventDefault();
    const down = parseThreshold(downloadInput);
    const up = parseThreshold(uploadInput);
    const problem = down.error || up.error;
    if (problem) {
      setActionError(problem);
      return;
    }
    const body = {};
    if (down.value !== undefined) body.download_threshold_mbps = down.value;
    if (up.value !== undefined) body.upload_threshold_mbps = up.value;
    if (!Object.keys(body).length) {
      setActionError("Enter a download or upload threshold, or use Clear.");
      return;
    }
    try {
      if (profileOnly && selected) await saveProfileThresholds(selected, body);
      else await saveThresholds(body);
      setActionError(null);
      setDownloadInput("");
      setUploadInput("");
      setSavedNote(profileOnly && selected ? `Saved for ${selected} only.` : "Saved for all interfaces.");
      await reload();
    } catch (err) {
      setActionError(err.message || "Could not save thresholds");
    }
  };

  const onClearThresholds = async () => {
    try {
      if (profileOnly && selected) {
        await clearProfileThresholds(selected);
        setSavedNote(`Cleared the ${selected} override. Global values apply.`);
      } else {
        await saveThresholds({ download_threshold_mbps: null, upload_threshold_mbps: null });
        await clearCapacity();
        setSavedNote("Cleared the download and upload thresholds, including the older single capacity value.");
      }
      setActionError(null);
      await reload();
    } catch (err) {
      setActionError(err.message || "Could not clear thresholds");
    }
  };

  return (
    <div className="min-h-screen bg-[#070b14] text-slate-100">
      <header className="border-b border-slate-800/80 bg-slate-950/70">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 py-4 flex flex-col sm:flex-row sm:items-end sm:justify-between gap-2">
          <div>
            <h1 className="text-lg font-semibold text-white">Network traffic</h1>
            <p className="text-sm text-slate-400">One interface on this computer. Not the router or other devices on the network.</p>
          </div>
          <p className="text-xs text-slate-500" aria-live="polite">
            {loading && !data ? "Connecting to the backend…" : collection?.status || "unavailable"}
            {collection?.freshness ? ` · ${collection.freshness}` : ""}
          </p>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-4 sm:px-6 py-6 space-y-6">
        <ErrorAlert error={statusError} onDismiss={() => setActionError(null)} />

        <section className="glass-panel rounded-2xl p-4 sm:p-5" id="overview" aria-label="Overview">
          <dl className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3">
            <Stat label="Collector" value={`${collection?.status || "unavailable"} · ${collection?.freshness || "no data"}`} id="overview-health" tone={freshnessTone} />
            <Stat label="Source" value={collection?.source || "unavailable"} id="overview-source" />
            <Stat label="Interface" value={selected ? `${selected}${selectedRecord?.kind ? ` · ${selectedRecord.kind}` : ""}` : "none"} id="overview-interface" />
            <Stat label="Profile" value={profile ? `${profile.name} · ${mode}` : mode} id="overview-profile" />
            <Stat label="Download" value={downloadNow} id="overview-download" />
            <Stat label="Upload" value={uploadNow} id="overview-upload" />
            <Stat label="Alert" value={alertView.label} id="overview-alert" tone={alertView.label === "Normal" ? "text-emerald-200" : alertView.label === "Threshold exceeded" ? "text-rose-200" : "text-amber-100"} />
            <Stat label="Packet capture" value={collection?.packet_capture?.is_capturing ? "running (diagnostic)" : "off · counters only"} id="overview-capture" />
          </dl>
        </section>

        <section className="glass-panel rounded-2xl p-4 sm:p-5 space-y-4" id="live-traffic" aria-labelledby="live-heading">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h2 id="live-heading" className="text-base font-semibold text-white">Live network traffic</h2>
              <p className="text-sm text-slate-400">Download and upload in decimal Mbps from OS byte counters. Near zero is normal when nothing is transferring. Gaps stay blank.</p>
            </div>
            <label className="text-sm text-slate-300 whitespace-nowrap">
              Window
              <select
                className="ml-2 bg-slate-900 border border-slate-700 rounded-lg px-2 py-1"
                value={historySeconds}
                onChange={(event) => setHistorySeconds(Number(event.target.value))}
                aria-label="Chart time window"
              >
                {WINDOWS.map((item) => <option key={item.seconds} value={item.seconds}>{item.label}</option>)}
              </select>
            </label>
          </div>
          <ThroughputChart
            history={data?.history || []}
            forecast={data?.forecast}
            thresholds={thresholds}
            transitions={data?.transitions || []}
            downsampled={Boolean(data?.history_resolution?.downsampled)}
            sampleInterval={collection?.sample_interval_seconds || 1}
            windowStart={data?.collected_at ? data.collected_at - historySeconds : null}
          />
          <p className="text-xs text-slate-500" id="history-summary">
            {selected || "No interface"} · every {collection?.sample_interval_seconds ?? "—"}s · last sample {formatTimestamp(current?.sampled_at)}
            {current?.quality ? ` · ${current.quality}` : ""}
            {" · "}
            {dataset?.valid_observations
              ? `${dataset.valid_observations} valid readings over ${(dataset.duration_seconds / 60).toFixed(1)} min`
              : "Collecting data"}
          </p>
        </section>

        <AlertPanel
          alert={data?.rise_alert}
          view={alertView}
          latchSince={latch?.since}
          notificationPermission={notificationPermission}
          onAllowNotifications={allowNotifications}
          events={data?.alert_events || []}
        />

        <section className="glass-panel rounded-2xl p-4 sm:p-5 space-y-4" id="traffic-forecast" aria-labelledby="forecast-heading">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 id="forecast-heading" className="text-base font-semibold text-white">Traffic forecast</h2>
              <p className="text-sm text-slate-400">Exponential smoothing, checked against persistence and a moving average. The dashed line is that level from the latest sample forward. It lags a sudden jump and does not predict when one will start.</p>
            </div>
            <label className="text-sm text-slate-300 whitespace-nowrap">
              Horizon
              <select
                className="ml-2 bg-slate-900 border border-slate-700 rounded-lg px-2 py-1"
                value={horizon}
                onChange={(event) => {
                  const next = Number(event.target.value);
                  setHorizon(next);
                  saveForecastHorizon(next).catch((err) => setActionError(err.message || "Could not save the forecast horizon"));
                }}
                aria-label="Forecast horizon"
              >
                <option value={60}>1 minute</option>
                <option value={300}>5 minutes</option>
                <option value={900}>15 minutes</option>
              </select>
            </label>
          </div>
          <p className="text-sm text-slate-100" id="trend-summary">{outlook.trend}</p>
          {riseWarning(data?.forecast?.receive?.recent_rise) && (
            <p className="text-sm text-amber-200" id="burst-warning">{riseWarning(data.forecast.receive.recent_rise)}</p>
          )}
          <p className="text-sm text-slate-300" id="overload-summary">{outlook.overload}</p>
          <p className="text-xs text-slate-500" id="accuracy-summary">{outlook.accuracy}</p>
        </section>

        <section className="glass-panel rounded-2xl p-4 sm:p-5 space-y-4" id="settings" aria-labelledby="settings-heading">
          <h2 id="settings-heading" className="text-base font-semibold text-white">Interface and thresholds</h2>
          <div className="grid gap-4 md:grid-cols-2">
            <label className="text-sm text-slate-300 block">
              Interface
              <select
                className="mt-1 w-full bg-slate-900 border border-slate-700 rounded-lg px-2 py-1.5"
                value={mode === "auto" ? "__auto__" : selected || ""}
                onChange={(event) => onInterface(event.target.value)}
                aria-label="Monitoring interface"
              >
                <option value="__auto__">Automatic: follow the active route{mode === "auto" && selected ? ` (${selected})` : ""}</option>
                {(interfaces.length ? interfaces : [{ name: selected || "" }]).map((item) => (
                  <option key={item.name} value={item.name}>
                    {item.name}
                    {item.is_default_route ? " · active path" : ""}
                    {item.kind ? ` · ${item.kind}` : ""}
                    {item.is_up === false ? " · down" : ""}
                  </option>
                ))}
              </select>
              <span className="mt-1 block text-xs text-slate-500">
                Switching re-baselines the counters, marks the change on the chart, and keeps each interface’s history and alerts separate. No reload is needed.
              </span>
            </label>

            <form onSubmit={onSaveThresholds} className="text-sm text-slate-300 space-y-2" aria-describedby="threshold-help">
              <div className="grid grid-cols-2 gap-2">
                <label className="block">
                  Download threshold (Mbps)
                  <input
                    className="mt-1 w-full bg-slate-900 border border-slate-700 rounded-lg px-2 py-1.5"
                    inputMode="decimal"
                    placeholder={thresholds?.receive != null ? String(thresholds.receive) : "Not set"}
                    value={downloadInput}
                    onChange={(event) => setDownloadInput(event.target.value)}
                    aria-label="Download threshold Mbps"
                    id="download-threshold-input"
                  />
                </label>
                <label className="block">
                  Upload threshold (Mbps)
                  <input
                    className="mt-1 w-full bg-slate-900 border border-slate-700 rounded-lg px-2 py-1.5"
                    inputMode="decimal"
                    placeholder={thresholds?.transmit != null ? String(thresholds.transmit) : "Not set"}
                    value={uploadInput}
                    onChange={(event) => setUploadInput(event.target.value)}
                    aria-label="Upload threshold Mbps"
                    id="upload-threshold-input"
                  />
                </label>
              </div>
              <label className="flex items-center gap-2 text-xs text-slate-400">
                <input type="checkbox" checked={profileOnly} onChange={(event) => setProfileOnly(event.target.checked)} disabled={!selected} />
                Apply only to {selected || "this interface"}
              </label>
              <div className="flex gap-2">
                <button type="submit" className="px-3 py-1.5 rounded-lg bg-indigo-600 text-white">Save</button>
                <button type="button" className="px-3 py-1.5 rounded-lg border border-slate-700" onClick={onClearThresholds}>Clear</button>
              </div>
              <p className="text-xs text-slate-500" id="threshold-help">
                Current: download {thresholds?.receive != null ? `${thresholds.receive} Mbps (${SOURCE_TEXT[thresholds.sources?.receive]})` : "not set"},
                upload {thresholds?.transmit != null ? `${thresholds.transmit} Mbps (${SOURCE_TEXT[thresholds.sources?.transmit]})` : "not set"}.
                These are test values you choose, not measured internet capacity, and adapter link speed is never used. {savedNote}
              </p>
            </form>
          </div>
          {data?.profiles?.items?.length > 1 && (
            <details className="text-xs text-slate-400">
              <summary className="cursor-pointer text-slate-300">Interface profiles ({data.profiles.items.length})</summary>
              <ul className="mt-2 space-y-1" id="profile-list">
                {data.profiles.items.map((item) => (
                  <li key={item.name}>
                    {item.name}{item.selected ? " (monitoring)" : ""}: {item.valid_observations} valid readings, last {formatTimestamp(item.latest_at)}
                    {item.has_own_thresholds ? " · own thresholds" : ""}
                  </li>
                ))}
              </ul>
              <p className="mt-2">{data.profiles.note}</p>
            </details>
          )}
        </section>

        <DiagnosticsPanel />
      </main>
    </div>
  );
}

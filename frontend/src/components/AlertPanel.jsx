import { displayMbps, formatTimestamp } from "../lib/monitoringView";

const TONES = {
  "Threshold exceeded": "bg-rose-500/15 text-rose-100 border-rose-500/40",
  "Traffic rising": "bg-amber-500/15 text-amber-100 border-amber-500/40",
  "Predicted threshold risk": "bg-orange-500/15 text-orange-100 border-orange-500/40",
  "Insufficient history": "bg-slate-500/15 text-slate-200 border-slate-500/40",
  "Collector unavailable or stale": "bg-slate-500/15 text-slate-300 border-slate-500/40",
  Normal: "bg-emerald-500/10 text-emerald-100 border-emerald-500/30",
};

function DirectionRow({ item }) {
  if (!item) return null;
  const configured = item.threshold_mbps != null;
  return (
    <tr className="border-t border-slate-800">
      <th scope="row" className="py-1.5 pr-3 text-left font-medium text-slate-200 capitalize">{item.label}</th>
      <td className="py-1.5 pr-3">{configured ? `${item.threshold_mbps} Mbps` : "not set"}</td>
      <td className="py-1.5 pr-3">{item.latest_mbps == null ? "unavailable" : `${displayMbps(item.latest_mbps)} Mbps`}</td>
      <td className="py-1.5 pr-3">
        {!configured ? "—" : item.active ? (
          <span className="text-rose-200">Above · recovery {item.recovery_progress}</span>
        ) : (
          <span className="text-emerald-200">Below</span>
        )}
      </td>
      <td className="py-1.5 pr-3">{formatTimestamp(item.last_alert_at)}</td>
      <td className="py-1.5">{formatTimestamp(item.last_recovery_at)}</td>
    </tr>
  );
}

export default function AlertPanel({ alert, view, latchSince, notificationPermission, onAllowNotifications, events = [] }) {
  const live = alert?.threshold_alert?.live;
  const tone = TONES[view.label] || TONES.Normal;
  return (
    <section className="glass-panel rounded-2xl p-4 sm:p-5 space-y-3" id="rise-alert" aria-labelledby="rise-alert-heading">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 id="rise-alert-heading" className="text-base font-semibold text-white">Traffic alert</h2>
          <p className="text-sm text-slate-400">
            Checks each stored reading against your saved download and upload thresholds, and flags sharp rises after they start.
          </p>
        </div>
        <p className={`text-sm font-semibold px-3 py-1 rounded-full border ${tone}`} id="rise-alert-state" role="status" aria-live="polite">
          {view.label}
        </p>
      </div>
      <p className="text-sm text-slate-200" id="rise-alert-explanation">{view.explanation}</p>
      <p className="text-xs text-slate-500" id="rise-alert-time">
        Panel state since {latchSince ? new Date(latchSince).toLocaleString() : "unavailable"}. Latest reading {formatTimestamp(alert?.sampled_at)}.
        {events.find((event) => !event.end_reason) ? ` Open episode started ${formatTimestamp(events.find((event) => !event.end_reason).started_at)}.` : ""}
      </p>

      {live && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs text-slate-300" id="threshold-table">
            <caption className="sr-only">Threshold status by direction</caption>
            <thead className="text-slate-500">
              <tr>
                <th scope="col" className="text-left font-normal pb-1">Direction</th>
                <th scope="col" className="text-left font-normal pb-1">Threshold</th>
                <th scope="col" className="text-left font-normal pb-1">Latest</th>
                <th scope="col" className="text-left font-normal pb-1">Status</th>
                <th scope="col" className="text-left font-normal pb-1">Last alert</th>
                <th scope="col" className="text-left font-normal pb-1">Last recovery</th>
              </tr>
            </thead>
            <tbody>
              <DirectionRow item={live.receive} />
              <DirectionRow item={live.transmit} />
            </tbody>
          </table>
        </div>
      )}

      {events.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs text-slate-300" id="alert-events">
            <caption className="text-left text-slate-300 pb-1">Recent episodes. None of these confirm a cyberattack.</caption>
            <thead className="text-slate-500">
              <tr>
                <th scope="col" className="text-left font-normal">Type</th>
                <th scope="col" className="text-left font-normal">Direction</th>
                <th scope="col" className="text-right font-normal">Rate</th>
                <th scope="col" className="text-right font-normal">Threshold / baseline</th>
                <th scope="col" className="text-left font-normal">Started</th>
                <th scope="col" className="text-right font-normal">Duration</th>
                <th scope="col" className="text-left font-normal">Ended</th>
              </tr>
            </thead>
            <tbody>
              {events.slice(0, 8).map((event) => (
                <tr key={event.id} className="border-t border-slate-800">
                  <td className="py-1 pr-2">{event.kind === "baseline_anomaly" ? "Baseline anomaly" : "Threshold"}</td>
                  <td className="py-1 pr-2">{event.direction === "transmit" ? "Upload" : "Download"}</td>
                  <td className="py-1 pr-2 text-right">{event.trigger_mbps == null ? "n/a" : `${displayMbps(event.trigger_mbps)} Mbps`}</td>
                  <td className="py-1 pr-2 text-right">
                    {event.kind === "baseline_anomaly"
                      ? (event.baseline_mbps == null ? "n/a" : `${displayMbps(event.baseline_mbps)} Mbps baseline`)
                      : (event.threshold_mbps == null ? "n/a" : `${event.threshold_mbps} Mbps`)}
                  </td>
                  <td className="py-1 pr-2">{formatTimestamp(event.started_at)}</td>
                  <td className="py-1 pr-2 text-right">{event.duration_seconds == null ? "n/a" : `${Math.round(event.duration_seconds)} s`}</td>
                  <td className="py-1">{event.end_reason === "recovered" ? formatTimestamp(event.ended_at) : event.end_reason ? event.end_reason.replaceAll("_", " ") : "active"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-xs text-slate-500" id="rise-alert-capacity">
        {alert?.capacity_note || "No threshold is saved. Adapter link speed is not used as capacity."} {alert?.advance?.message ? `Five-minute advance warning: ${alert.advance.message}.` : ""}
      </p>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <button type="button" className="px-3 py-1.5 rounded-lg border border-slate-700 text-sm text-slate-200 hover:bg-slate-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-400" onClick={onAllowNotifications}>
          Allow browser notifications
        </button>
        <p className="text-xs text-slate-500" id="rise-alert-permission">
          {notificationPermission === "granted" && "Browser notifications are on. One notice is sent when an alert starts, not on every sample."}
          {notificationPermission === "denied" && "Browser notifications are blocked. This panel still shows the alert."}
          {notificationPermission === "default" && "Browser notifications stay off until you allow them. This panel still shows the alert."}
          {notificationPermission === "unsupported" && "This browser does not offer notifications. This panel still shows the alert."}
        </p>
      </div>
    </section>
  );
}

import React from 'react';

/**
 * StatusBadge — shows connection and capture state visually with pulses.
 */
export default function StatusBadge({ connectionState, isCapturing, error }) {
  if (error) {
    return (
      <span
        id="status-badge"
        className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/30"
      >
        <span className="w-2 h-2 rounded-full bg-rose-500 animate-ping" />
        Error
      </span>
    );
  }

  if (connectionState === 'disconnected') {
    return (
      <span
        id="status-badge"
        className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-slate-800 text-slate-400 border border-slate-700"
      >
        <span className="w-2 h-2 rounded-full bg-slate-500" />
        Disconnected
      </span>
    );
  }

  if (connectionState === 'connecting') {
    return (
      <span
        id="status-badge"
        className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/30"
      >
        <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
        Connecting…
      </span>
    );
  }

  if (isCapturing) {
    return (
      <span
        id="status-badge"
        className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30"
      >
        <span className="relative flex h-2 w-2">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
          <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
        </span>
        Live Capturing
      </span>
    );
  }

  return (
    <span
      id="status-badge"
      className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-indigo-500/10 text-indigo-400 border border-indigo-500/30"
    >
      <span className="w-2 h-2 rounded-full bg-indigo-400" />
      Ready / Idle
    </span>
  );
}

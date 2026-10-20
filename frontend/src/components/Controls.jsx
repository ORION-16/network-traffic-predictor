import React from 'react';

/**
 * Controls — start capture, stop capture, export CSV, and reset counters.
 */
export default function Controls({
  isCapturing,
  onStart,
  onStop,
  onExportCsv,
  onReset,
  selectedInterface,
  isLoadingAction,
  hasPackets,
}) {
  return (
    <div className="flex flex-wrap items-center gap-2.5" id="capture-controls">
      {!isCapturing ? (
        <button
          id="btn-start-capture"
          onClick={onStart}
          disabled={!selectedInterface || isLoadingAction}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white shadow-lg shadow-emerald-950/40 disabled:opacity-50 disabled:cursor-not-allowed transition-all transform active:scale-95 cursor-pointer"
        >
          {isLoadingAction ? (
            <svg className="animate-spin h-3.5 w-3.5" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
            </svg>
          ) : (
            <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24">
              <path d="M8 5v14l11-7z" />
            </svg>
          )}
          Start Capture
        </button>
      ) : (
        <button
          id="btn-stop-capture"
          onClick={onStop}
          disabled={isLoadingAction}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold bg-rose-600 hover:bg-rose-500 text-white shadow-lg shadow-rose-950/40 disabled:opacity-50 disabled:cursor-not-allowed transition-all transform active:scale-95 cursor-pointer"
        >
          {isLoadingAction ? (
            <svg className="animate-spin h-3.5 w-3.5" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
            </svg>
          ) : (
            <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24">
              <rect x="6" y="6" width="12" height="12" rx="1.5" />
            </svg>
          )}
          Stop Capture
        </button>
      )}

      {/* CSV Export */}
      <button
        id="btn-export-csv"
        onClick={onExportCsv}
        disabled={!hasPackets}
        title={!hasPackets ? 'Capture packets to enable CSV export' : 'Export captured packet metadata'}
        className="inline-flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700/80 disabled:opacity-40 disabled:cursor-not-allowed transition-all cursor-pointer"
      >
        <svg className="w-3.5 h-3.5 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
        </svg>
        Export CSV
      </button>

      {/* Clear/Reset */}
      <button
        id="btn-reset-data"
        onClick={onReset}
        disabled={isCapturing || !hasPackets}
        title="Reset buffered data and counters"
        className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-medium bg-slate-800/60 hover:bg-slate-800 text-slate-400 hover:text-slate-200 border border-slate-800 disabled:opacity-30 disabled:cursor-not-allowed transition-all cursor-pointer"
      >
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
        </svg>
        Clear
      </button>
    </div>
  );
}

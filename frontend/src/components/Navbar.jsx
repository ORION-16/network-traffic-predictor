import React from 'react';
import StatusBadge from './StatusBadge';

/**
 * Navbar — responsive navigation header with branding, status badge, and interface indicator.
 */
export default function Navbar({
  selectedInterface,
  connectionState,
  isCapturing,
  error,
  onRefreshInterfaces,
  isRefreshing,
}) {
  return (
    <header className="border-b border-slate-800/80 bg-slate-950/70 backdrop-blur-xl sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between gap-4">
        {/* Brand / Logo */}
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-indigo-600 via-indigo-500 to-cyan-400 p-0.5 shadow-md shadow-indigo-500/20 flex items-center justify-center">
            <div className="w-full h-full bg-slate-950 rounded-[10px] flex items-center justify-center">
              <svg className="w-5 h-5 text-indigo-400" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
            </div>
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-base font-bold tracking-tight text-white">
                Network Traffic Predictor
              </h1>
              <span className="text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-full bg-indigo-500/15 text-indigo-300 border border-indigo-500/30">
                Phase 1
              </span>
            </div>
            <p className="text-[11px] text-slate-400 hidden sm:block">
              Real-time Packet Capture & Telemetry Monitor
            </p>
          </div>
        </div>

        {/* Center / Right status elements */}
        <div className="flex items-center gap-3">
          {/* Active interface tag */}
          {selectedInterface && (
            <div className="hidden md:flex items-center gap-1.5 px-3 py-1 rounded-xl bg-slate-900 border border-slate-800 text-xs">
              <span className="w-1.5 h-1.5 rounded-full bg-cyan-400" />
              <span className="text-slate-400">Target:</span>
              <span className="font-mono font-medium text-slate-200">{selectedInterface}</span>
            </div>
          )}

          {/* Refresh Interfaces Button */}
          <button
            onClick={onRefreshInterfaces}
            disabled={isCapturing || isRefreshing}
            title="Refresh available network interfaces"
            className="p-2 rounded-xl bg-slate-900 hover:bg-slate-800 text-slate-400 hover:text-slate-200 border border-slate-800 disabled:opacity-40 transition-colors cursor-pointer"
          >
            <svg
              className={`w-4 h-4 ${isRefreshing ? 'animate-spin text-indigo-400' : ''}`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
          </button>

          {/* Real-time Status Badge */}
          <StatusBadge connectionState={connectionState} isCapturing={isCapturing} error={error} />
        </div>
      </div>
    </header>
  );
}

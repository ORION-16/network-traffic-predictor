import React from 'react';

/**
 * InterfaceSelector — dropdown selector for choosing available network interfaces.
 */
export default function InterfaceSelector({
  interfaces = [],
  selectedInterface,
  onSelect,
  isLoading,
  isCapturing,
  error,
}) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-center gap-2" id="interface-selector">
      <label htmlFor="iface-select" className="text-xs font-semibold uppercase tracking-wider text-slate-400">
        Interface:
      </label>

      {isLoading ? (
        <div className="flex items-center gap-2 text-xs text-slate-400 bg-slate-900/80 px-3 py-2 rounded-xl border border-slate-800">
          <svg className="animate-spin h-3.5 w-3.5 text-indigo-400" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
          </svg>
          Loading interfaces...
        </div>
      ) : error ? (
        <div className="text-xs text-rose-400 bg-rose-500/10 px-3 py-1.5 rounded-xl border border-rose-500/30">
          ⚠️ {error}
        </div>
      ) : (
        <div className="relative">
          <select
            id="iface-select"
            value={selectedInterface}
            onChange={(e) => onSelect(e.target.value)}
            disabled={isCapturing}
            className="appearance-none bg-slate-900/90 text-slate-200 text-xs font-medium pl-3 pr-8 py-2 rounded-xl border border-slate-700/80 hover:border-slate-600 focus:outline-none focus:ring-2 focus:ring-indigo-500/40 focus:border-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
          >
            <option value="">Choose an interface...</option>
            {interfaces.map((iface) => (
              <option key={iface.name} value={iface.name}>
                {iface.name} {iface.is_loopback ? '(Loopback)' : iface.is_up ? '(Active)' : '(Down)'}
              </option>
            ))}
          </select>
          <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2 text-slate-400">
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7" />
            </svg>
          </div>
        </div>
      )}
    </div>
  );
}

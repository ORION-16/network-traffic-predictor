import React from 'react';

/**
 * MetricCard — displays real-time telemetry metrics with sleek accents.
 */
export default function MetricCard({ label, value, unit, icon, trend, color = 'indigo' }) {
  const colorMap = {
    indigo: 'text-indigo-400 bg-indigo-500/10 border-indigo-500/20 group-hover:border-indigo-500/40',
    cyan: 'text-cyan-400 bg-cyan-500/10 border-cyan-500/20 group-hover:border-cyan-500/40',
    emerald: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20 group-hover:border-emerald-500/40',
    amber: 'text-amber-400 bg-amber-500/10 border-amber-500/20 group-hover:border-amber-500/40',
    rose: 'text-rose-400 bg-rose-500/10 border-rose-500/20 group-hover:border-rose-500/40',
  };

  const activeColor = colorMap[color] || colorMap.indigo;

  return (
    <div
      id={`metric-${label.toLowerCase().replace(/\s+/g, '-')}`}
      className="glass-panel group relative p-5 rounded-2xl transition-all duration-300 hover:translate-y-[-2px] hover:shadow-lg flex flex-col justify-between"
    >
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-semibold tracking-wider uppercase text-slate-400">
          {label}
        </span>
        <div className={`p-2 rounded-xl border transition-colors ${activeColor}`}>
          {icon}
        </div>
      </div>

      <div className="flex items-baseline gap-2">
        <span className="text-2xl font-bold tracking-tight text-white font-mono">
          {value}
        </span>
        {unit && (
          <span className="text-xs font-medium text-slate-400">
            {unit}
          </span>
        )}
      </div>

      {trend && (
        <div className="mt-2 text-xs text-slate-500 flex items-center gap-1">
          {trend}
        </div>
      )}
    </div>
  );
}

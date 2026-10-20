import React, { useMemo } from 'react';
import PlotlyPlot from '../components/PlotlyPlot';

const PROTO_COLORS = [
  '#6366f1', // Indigo (TCP)
  '#06b6d4', // Cyan (UDP)
  '#f59e0b', // Amber (ICMP)
  '#10b981', // Emerald (ARP/Other)
  '#ec4899', // Pink
  '#8b5cf6', // Violet
  '#f97316', // Orange
  '#14b8a6', // Teal
  '#64748b', // Slate
];

/**
 * Modern donut chart for protocol distribution using Plotly.
 */
export default function ProtocolChart({ protocolDistribution = {} }) {
  const { labels, values, colors } = useMemo(() => {
    if (!protocolDistribution || Object.keys(protocolDistribution).length === 0) {
      return { labels: [], values: [], colors: [] };
    }

    const entries = Object.entries(protocolDistribution).sort((a, b) => b[1] - a[1]);
    return {
      labels: entries.map(([k]) => k),
      values: entries.map(([, v]) => v),
      colors: entries.map((_, i) => PROTO_COLORS[i % PROTO_COLORS.length]),
    };
  }, [protocolDistribution]);

  const layout = useMemo(
    () => ({
      autosize: true,
      height: 320,
      margin: { t: 20, r: 20, b: 40, l: 20 },
      paper_bgcolor: 'transparent',
      plot_bgcolor: 'transparent',
      font: { color: '#94a3b8', family: 'system-ui, -apple-system, sans-serif' },
      showlegend: true,
      legend: {
        orientation: 'h',
        x: 0,
        y: -0.15,
        font: { size: 11, color: '#cbd5e1' },
      },
    }),
    []
  );

  const plotData = useMemo(() => {
    if (labels.length === 0) return [];
    return [
      {
        type: 'pie',
        labels,
        values,
        hole: 0.62,
        marker: {
          colors,
          line: { color: '#0f172a', width: 2 },
        },
        textfont: { color: '#f8fafc', size: 12 },
        textinfo: 'label+percent',
        hoverinfo: 'label+value+percent',
      },
    ];
  }, [labels, values, colors]);

  if (labels.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-80 rounded-xl border border-dashed border-slate-800 bg-slate-900/40 text-slate-500">
        <svg
          className="w-10 h-10 mb-2 text-slate-600"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth="1.5"
            d="M11 3.055A9.001 9.001 0 1020.945 13H11V3.055z"
          />
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth="1.5"
            d="M20.488 9H15V3.512A9.025 9.025 0 0120.488 9z"
          />
        </svg>
        <p className="text-sm font-medium">No protocol data recorded</p>
        <span className="text-xs text-slate-600 mt-1">Packets captured will appear by layer 3/4 protocol</span>
      </div>
    );
  }

  return (
    <div className="w-full h-80">
      <PlotlyPlot
        data={plotData}
        layout={layout}
        config={{ responsive: true, displayModeBar: false }}
        style={{ width: '100%', height: '100%' }}
      />
    </div>
  );
}

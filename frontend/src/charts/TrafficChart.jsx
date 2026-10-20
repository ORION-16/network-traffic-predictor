import React, { useMemo } from 'react';
import PlotlyPlot from '../components/PlotlyPlot';

/**
 * Live traffic-over-time line chart using Plotly.
 * Displays packets/sec and throughput bytes/sec on dual y-axes.
 */
export default function TrafficChart({ trafficSeries = [] }) {
  const data = useMemo(() => {
    if (!trafficSeries || trafficSeries.length === 0) return [];

    const timestamps = trafficSeries.map((p) =>
      new Date(p.timestamp * 1000).toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      })
    );
    const packets = trafficSeries.map((p) => p.packets);
    const bytes = trafficSeries.map((p) => p.bytes || p.bytes_ || 0);

    return [
      {
        x: timestamps,
        y: packets,
        type: 'scatter',
        mode: 'lines+markers',
        name: 'Packets / sec',
        line: { color: '#6366f1', width: 2.5, shape: 'spline' },
        marker: { size: 4, color: '#818cf8' },
        fill: 'tozeroy',
        fillcolor: 'rgba(99, 102, 241, 0.08)',
      },
      {
        x: timestamps,
        y: bytes,
        type: 'scatter',
        mode: 'lines',
        name: 'Bytes / sec',
        yaxis: 'y2',
        line: { color: '#06b6d4', width: 2, dash: 'dot', shape: 'spline' },
      },
    ];
  }, [trafficSeries]);

  const layout = useMemo(
    () => ({
      autosize: true,
      height: 320,
      margin: { t: 20, r: 55, b: 40, l: 55 },
      paper_bgcolor: 'transparent',
      plot_bgcolor: 'transparent',
      font: { color: '#94a3b8', family: 'system-ui, -apple-system, sans-serif', size: 11 },
      showlegend: true,
      legend: {
        orientation: 'h',
        x: 0,
        y: 1.15,
        font: { size: 11, color: '#cbd5e1' },
      },
      xaxis: {
        gridcolor: 'rgba(51, 65, 85, 0.4)',
        linecolor: 'rgba(51, 65, 85, 0.6)',
        zerolinecolor: 'rgba(51, 65, 85, 0.4)',
        tickfont: { color: '#94a3b8', size: 10 },
      },
      yaxis: {
        title: { text: 'Packets/s', font: { color: '#818cf8', size: 11 } },
        gridcolor: 'rgba(51, 65, 85, 0.4)',
        linecolor: 'rgba(51, 65, 85, 0.6)',
        zerolinecolor: 'rgba(51, 65, 85, 0.4)',
        tickfont: { color: '#94a3b8', size: 10 },
      },
      yaxis2: {
        title: { text: 'Bytes/s', font: { color: '#22d3ee', size: 11 } },
        overlaying: 'y',
        side: 'right',
        gridcolor: 'transparent',
        linecolor: 'rgba(51, 65, 85, 0.6)',
        zerolinecolor: 'transparent',
        tickfont: { color: '#94a3b8', size: 10 },
      },
    }),
    []
  );

  if (!trafficSeries || trafficSeries.length === 0) {
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
            d="M7 12l3-3 3 3 4-4M8 21l4-4 4 4M3 4h18M4 4h16v12a2 2 0 01-2 2H6a2 2 0 01-2-2V4z"
          />
        </svg>
        <p className="text-sm font-medium">Awaiting traffic data...</p>
        <span className="text-xs text-slate-600 mt-1">Start capture to observe live volume metrics</span>
      </div>
    );
  }

  return (
    <div className="w-full h-80">
      <PlotlyPlot
        data={data}
        layout={layout}
        config={{ responsive: true, displayModeBar: false }}
        style={{ width: '100%', height: '100%' }}
      />
    </div>
  );
}

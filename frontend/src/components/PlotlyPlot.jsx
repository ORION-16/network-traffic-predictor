import React, { useEffect, useRef } from 'react';
import Plotly from 'plotly.js-dist-min';

/**
 * Robust React wrapper around Plotly.js (plotly.js-dist-min)
 * Compatible with React 18 & 19 without peer dependency mismatches.
 */
export default function PlotlyPlot({
  data = [],
  layout = {},
  config = { responsive: true, displayModeBar: false },
  style = { width: '100%', height: '100%' },
  className = '',
  useResizeHandler = true,
}) {
  const containerRef = useRef(null);

  useEffect(() => {
    const elem = containerRef.current;
    if (!elem) return;

    Plotly.react(elem, data, layout, config);
  }, [data, layout, config]);

  useEffect(() => {
    const elem = containerRef.current;
    if (!elem) return;

    const handleResize = () => {
      if (elem && elem.data) {
        Plotly.Plots.resize(elem);
      }
    };

    if (useResizeHandler) {
      window.addEventListener('resize', handleResize);
    }

    return () => {
      if (useResizeHandler) {
        window.removeEventListener('resize', handleResize);
      }
      if (elem) {
        Plotly.purge(elem);
      }
    };
  }, [useResizeHandler]);

  return <div ref={containerRef} style={style} className={className} />;
}

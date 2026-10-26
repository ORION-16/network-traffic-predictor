import { startTransition, useCallback, useEffect, useState } from "react";
import { fetchDashboard } from "../services/api";

/**
 * Poll the monitoring dashboard. A failed request leaves the last real payload
 * in place and surfaces the error. It does not substitute generated traffic.
 */
export function useMonitoring({ method, window, alpha, horizon, historySeconds = 900 }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    try {
      const payload = await fetchDashboard({
        method,
        window,
        alpha,
        horizonSeconds: horizon,
        historySeconds,
      });
      setData(payload);
      setError(null);
    } catch (err) {
      setError(err.message || "Monitoring API request failed");
    } finally {
      setLoading(false);
    }
  }, [method, window, alpha, horizon, historySeconds]);

  useEffect(() => {
    let stop = false;
    let timer = 0;
    const tick = async () => {
      const started = performance.now();
      try {
        const payload = await fetchDashboard({
          method,
          window,
          alpha,
          horizonSeconds: horizon,
          historySeconds,
        });
        if (!stop) {
          startTransition(() => {
            setData(payload);
            setError(null);
          });
        }
      } catch (err) {
        if (!stop) setError(err.message || "Monitoring API request failed");
      } finally {
        if (!stop) {
          setLoading(false);
          const elapsed = performance.now() - started;
          timer = setTimeout(tick, Math.max(200, 1000 - elapsed));
        }
      }
    };
    tick();
    return () => {
      stop = true;
      clearTimeout(timer);
    };
  }, [method, window, alpha, horizon, historySeconds]);

  return { data, error, loading, reload };
}

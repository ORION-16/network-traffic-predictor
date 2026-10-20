import { useEffect, useRef, useCallback, useState } from 'react';
import { getWebSocketUrl } from '../services/api';

/**
 * Custom hook for WebSocket connection to the capture stream.
 * Handles reconnection, incremental packet accumulation, and
 * connection state tracking.
 */
export function useCaptureSocket(isCapturing) {
  const wsRef = useRef(null);
  const reconnectTimer = useRef(null);
  const [connectionState, setConnectionState] = useState('disconnected'); // 'connecting' | 'connected' | 'disconnected'
  const [metrics, setMetrics] = useState({
    total_packets: 0,
    total_bytes: 0,
    packet_rate: 0,
    throughput: 0,
    protocol_distribution: {},
  });
  const [recentPackets, setRecentPackets] = useState([]);
  const [trafficSeries, setTrafficSeries] = useState([]);
  const [wsError, setWsError] = useState(null);

  const MAX_RECENT = 200; // keep last 200 packets in the table

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    setConnectionState('connecting');
    const ws = new WebSocket(getWebSocketUrl());
    wsRef.current = ws;

    ws.onopen = () => {
      setConnectionState('connected');
      setWsError(null);
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);

        if (data.metrics) setMetrics(data.metrics);
        if (data.traffic_series) setTrafficSeries(data.traffic_series);
        if (data.error) setWsError(data.error);

        if (data.new_packets?.length > 0) {
          setRecentPackets((prev) => {
            const combined = [...prev, ...data.new_packets];
            return combined.slice(-MAX_RECENT);
          });
        }
      } catch (err) {
        console.error('WebSocket message parse error:', err);
      }
    };

    ws.onerror = () => {
      setWsError('WebSocket connection error');
    };

    ws.onclose = () => {
      setConnectionState('disconnected');
      wsRef.current = null;
      // Auto-reconnect after 2 seconds
      reconnectTimer.current = setTimeout(() => {
        connect();
      }, 2000);
    };
  }, []);

  const disconnect = useCallback(() => {
    if (reconnectTimer.current) {
      clearTimeout(reconnectTimer.current);
      reconnectTimer.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setConnectionState('disconnected');
  }, []);

  // Connect when capturing starts
  useEffect(() => {
    connect();
    return () => disconnect();
  }, [connect, disconnect]);

  const resetData = useCallback(() => {
    setRecentPackets([]);
    setTrafficSeries([]);
    setMetrics({
      total_packets: 0,
      total_bytes: 0,
      packet_rate: 0,
      throughput: 0,
      protocol_distribution: {},
    });
    setWsError(null);
  }, []);

  return {
    connectionState,
    metrics,
    recentPackets,
    trafficSeries,
    wsError,
    resetData,
  };
}

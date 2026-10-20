import React, { useState, useEffect, useCallback, useTransition } from 'react';
import Navbar from '../components/Navbar';
import MetricCard from '../components/MetricCard';
import InterfaceSelector from '../components/InterfaceSelector';
import Controls from '../components/Controls';
import TrafficChart from '../charts/TrafficChart';
import ProtocolChart from '../charts/ProtocolChart';
import PacketTable from '../components/PacketTable';
import ErrorAlert from '../components/ErrorAlert';
import { useCaptureSocket } from '../hooks/useCaptureSocket';
import {
  fetchInterfaces,
  fetchCaptureStatus,
  startCapture,
  stopCapture,
  getExportCsvUrl,
} from '../services/api';

/**
 * Format raw bytes into human readable B / KB / MB / GB.
 */
function formatBytes(bytes) {
  if (bytes === 0 || !bytes) return { value: '0', unit: 'B' };
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return {
    value: parseFloat((bytes / Math.pow(k, i)).toFixed(2)).toString(),
    unit: sizes[i],
  };
}

/**
 * Main dashboard page for Phase 1 Network Traffic Predictor.
 */
export default function Dashboard() {
  const [interfaces, setInterfaces] = useState([]);
  const [selectedInterface, setSelectedInterface] = useState('');
  const [loadingInterfaces, setLoadingInterfaces] = useState(true);
  const [interfaceError, setInterfaceError] = useState(null);

  const [isCapturing, setIsCapturing] = useState(false);
  const [captureError, setCaptureError] = useState(null);
  const [actionLoading, setActionLoading] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);

  // Hook for live WebSocket packet updates
  const {
    connectionState,
    metrics,
    recentPackets,
    trafficSeries,
    wsError,
    resetData,
  } = useCaptureSocket(isCapturing);

  // Combine errors for banner display
  const activeError = captureError || wsError;

  // Fetch interface list
  const loadInterfaces = useCallback(async () => {
    try {
      setLoadingInterfaces(true);
      setInterfaceError(null);
      const data = await fetchInterfaces();
      const list = data.interfaces || [];
      setInterfaces(list);

      // Auto-select first active or loopback interface if none selected
      if (!selectedInterface && list.length > 0) {
        const preferred = list.find((i) => i.is_up && !i.is_loopback) || list[0];
        setSelectedInterface(preferred.name);
      }
    } catch (err) {
      setInterfaceError(err.message || 'Failed to load network interfaces');
    } finally {
      setLoadingInterfaces(false);
      setIsRefreshing(false);
    }
  }, [selectedInterface]);

  // Initial load: interfaces and initial capture status
  useEffect(() => {
    loadInterfaces();

    // Check initial capture status from backend
    fetchCaptureStatus()
      .then((status) => {
        setIsCapturing(status.is_capturing);
        if (status.interface) {
          setSelectedInterface(status.interface);
        }
        if (status.error) {
          setCaptureError(status.error);
        }
      })
      .catch((err) => {
        console.warn('Initial status fetch warning:', err);
      });
  }, []);

  const handleRefreshInterfaces = () => {
    setIsRefreshing(true);
    loadInterfaces();
  };

  // Start capture handler
  const handleStart = async () => {
    if (!selectedInterface) return;
    try {
      setActionLoading(true);
      setCaptureError(null);
      const res = await startCapture(selectedInterface);
      setIsCapturing(res.is_capturing);
      resetData();
    } catch (err) {
      setCaptureError(err.message || 'Failed to initiate packet capture');
    } finally {
      setActionLoading(false);
    }
  };

  // Stop capture handler
  const handleStop = async () => {
    try {
      setActionLoading(true);
      const res = await stopCapture();
      setIsCapturing(res.is_capturing);
    } catch (err) {
      setCaptureError(err.message || 'Failed to stop capture');
    } finally {
      setActionLoading(false);
    }
  };

  // CSV export handler
  const handleExportCsv = () => {
    const url = getExportCsvUrl();
    window.open(url, '_blank');
  };

  const formattedBytes = formatBytes(metrics.total_bytes);
  const formattedThroughput = formatBytes(metrics.throughput);

  return (
    <div className="min-h-screen bg-[#070b14] text-slate-100 flex flex-col font-sans">
      <Navbar
        selectedInterface={selectedInterface}
        connectionState={connectionState}
        isCapturing={isCapturing}
        error={activeError}
        onRefreshInterfaces={handleRefreshInterfaces}
        isRefreshing={isRefreshing}
      />

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">
        {/* Error Alert Banner */}
        <ErrorAlert error={activeError} onDismiss={() => setCaptureError(null)} />

        {/* Dashboard Control Bar */}
        <div className="glass-panel p-4 sm:p-5 rounded-2xl flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex flex-col sm:flex-row sm:items-center gap-4">
            <InterfaceSelector
              interfaces={interfaces}
              selectedInterface={selectedInterface}
              onSelect={setSelectedInterface}
              isLoading={loadingInterfaces}
              isCapturing={isCapturing}
              error={interfaceError}
            />

            {/* Quick Helper badge for interface selection */}
            {selectedInterface && (
              <span className="hidden lg:inline-flex text-[11px] text-slate-400 bg-slate-900/60 px-3 py-1 rounded-xl border border-slate-800">
                Packets will be captured from <strong className="text-slate-200 ml-1">{selectedInterface}</strong>
              </span>
            )}
          </div>

          <Controls
            isCapturing={isCapturing}
            onStart={handleStart}
            onStop={handleStop}
            onExportCsv={handleExportCsv}
            onReset={resetData}
            selectedInterface={selectedInterface}
            isLoadingAction={actionLoading}
            hasPackets={recentPackets.length > 0 || metrics.total_packets > 0}
          />
        </div>

        {/* Metrics Grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <MetricCard
            label="Total Packets"
            value={metrics.total_packets.toLocaleString()}
            unit="pkts"
            color="indigo"
            icon={
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
              </svg>
            }
          />

          <MetricCard
            label="Total Volume"
            value={formattedBytes.value}
            unit={formattedBytes.unit}
            color="cyan"
            icon={
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 7v10c0 2 1 3 3 3h10c2 0 3-1 3-3V7c0-2-1-3-3-3H7C5 4 4 5 4 7z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12h6m-3-3v6" />
              </svg>
            }
          />

          <MetricCard
            label="Packet Rate"
            value={metrics.packet_rate.toFixed(1)}
            unit="pkts/s"
            color="emerald"
            icon={
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
              </svg>
            }
          />

          <MetricCard
            label="Throughput"
            value={formattedThroughput.value}
            unit={`${formattedThroughput.unit}/s`}
            color="amber"
            icon={
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
              </svg>
            }
          />
        </div>

        {/* Charts Section: 2 Columns on desktop */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Traffic over time (spans 2 columns) */}
          <div className="lg:col-span-2 glass-panel p-5 rounded-2xl flex flex-col justify-between" id="traffic-time-chart">
            <div className="flex items-center justify-between mb-2">
              <div>
                <h3 className="text-sm font-semibold tracking-wide text-white uppercase">
                  Traffic Intensity Over Time
                </h3>
                <p className="text-xs text-slate-400">
                  Dual-axis time series of packet frequency & throughput
                </p>
              </div>
              {isCapturing && (
                <span className="flex items-center gap-1.5 text-[10px] text-emerald-400 font-mono">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping" />
                  Streaming 1Hz
                </span>
              )}
            </div>
            <TrafficChart trafficSeries={trafficSeries} />
          </div>

          {/* Protocol Distribution Donut (spans 1 column) */}
          <div className="glass-panel p-5 rounded-2xl flex flex-col justify-between" id="protocol-donut-chart">
            <div className="mb-2">
              <h3 className="text-sm font-semibold tracking-wide text-white uppercase">
                Protocol Composition
              </h3>
              <p className="text-xs text-slate-400">
                Layer 3/4 distribution of observed packets
              </p>
            </div>
            <ProtocolChart protocolDistribution={metrics.protocol_distribution} />
          </div>
        </div>

        {/* Recent Packets Feed Table */}
        <PacketTable packets={recentPackets} isCapturing={isCapturing} />
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-800/60 py-4 mt-8 bg-slate-950/40 text-center text-xs text-slate-500">
        <p>Network Traffic Predictor • Phase 1 Live Telemetry Module • Safe Header-Only Capture</p>
      </footer>
    </div>
  );
}

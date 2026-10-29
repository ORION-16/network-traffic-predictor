/**
 * REST API client for the Network Traffic Predictor backend.
 */

const API_BASE = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';

async function request(path, options = {}) {
  const url = `${API_BASE}${path}`;
  const headers = { ...options.headers };
  if (options.body && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }
  const resp = await fetch(url, {
    ...options,
    headers,
  });

  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    const message = body.detail || `HTTP ${resp.status}`;
    throw new Error(message);
  }
  return resp;
}

export async function fetchMonitoringInterfaces() {
  const resp = await request('/api/monitoring/interfaces');
  return resp.json();
}

export async function fetchInterfaces() {
  const resp = await request('/api/interfaces');
  return resp.json();
}

export async function fetchCaptureStatus() {
  const resp = await request('/api/capture/status');
  return resp.json();
}

export async function startCapture(interfaceName) {
  const resp = await request('/api/capture/start', {
    method: 'POST',
    body: JSON.stringify({ interface: interfaceName }),
  });
  return resp.json();
}

export async function stopCapture() {
  const resp = await request('/api/capture/stop', {
    method: 'POST',
  });
  return resp.json();
}

export function getExportCsvUrl() {
  return `${API_BASE}/api/capture/export/csv`;
}

export function getWebSocketUrl() {
  const base = API_BASE.replace(/^http/, 'ws');
  return `${base}/ws/capture`;
}

export async function fetchDashboard({
  method = 'exponential_smoothing',
  window = 12,
  alpha = 0.3,
  horizonSeconds = 60,
  historySeconds = 300,
} = {}) {
  const params = new URLSearchParams({
    method,
    window: String(window),
    alpha: String(alpha),
    horizon_seconds: String(horizonSeconds),
    history_seconds: String(historySeconds),
  });
  const resp = await request(`/api/monitoring/dashboard?${params}`);
  return resp.json();
}

export async function saveForecastHorizon(horizonSeconds) {
  const resp = await request('/api/monitoring/horizon', {
    method: 'PUT',
    body: JSON.stringify({ horizon_seconds: horizonSeconds }),
  });
  return resp.json();
}

export async function selectMonitoringInterface(name) {
  const resp = await request('/api/monitoring/interface', {
    method: 'PUT',
    body: JSON.stringify({ name }),
  });
  return resp.json();
}

export async function saveCapacity(body) {
  const resp = await request('/api/capacity', {
    method: 'PUT',
    body: JSON.stringify(body),
  });
  return resp.json();
}

export async function clearCapacity() {
  const resp = await request('/api/capacity', { method: 'DELETE' });
  return resp.json();
}

export async function saveThresholds(body) {
  const resp = await request('/api/thresholds', {
    method: 'PUT',
    body: JSON.stringify(body),
  });
  return resp.json();
}

export async function selectAutoInterface() {
  const resp = await request('/api/monitoring/interface', {
    method: 'PUT',
    body: JSON.stringify({ mode: 'auto' }),
  });
  return resp.json();
}

export async function saveProfileThresholds(name, body) {
  const resp = await request(`/api/profiles/${encodeURIComponent(name)}/thresholds`, {
    method: 'PUT',
    body: JSON.stringify(body),
  });
  return resp.json();
}

export async function clearProfileThresholds(name) {
  const resp = await request(`/api/profiles/${encodeURIComponent(name)}/thresholds`, { method: 'DELETE' });
  return resp.json();
}

export async function saveAlertRules(body) {
  const resp = await request('/api/alert-rules', {
    method: 'PUT',
    body: JSON.stringify(body),
  });
  return resp.json();
}

export async function fetchReliability() {
  const resp = await request('/api/reliability');
  return resp.json();
}

export async function fetchDiagnostics(refresh = false) {
  const resp = await request(`/api/diagnostics${refresh ? '?refresh=true' : ''}`);
  return resp.json();
}

export async function fetchCaptureAvailability() {
  const resp = await request('/api/capture/availability');
  return resp.json();
}

export async function runCaptureComparison(seconds = 5) {
  const resp = await request(`/api/capture/compare?seconds=${encodeURIComponent(seconds)}`, { method: 'POST' });
  return resp.json();
}

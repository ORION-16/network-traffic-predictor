/**
 * REST API client for the Network Traffic Predictor backend.
 */

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

async function request(path, options = {}) {
  const url = `${API_BASE}${path}`;
  const resp = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });

  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    const message = body.detail || `HTTP ${resp.status}`;
    throw new Error(message);
  }
  return resp;
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

"""REST endpoints for capture control and data export."""

from __future__ import annotations

import csv
import io
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from capture.sniffer import start_capture, stop_capture
from capture.state import CaptureStatus, capture_state
from schemas import CaptureStatusResponse, StartCaptureRequest

router = APIRouter(prefix="/api/capture", tags=["capture"])
logger = logging.getLogger(__name__)


def _status_response() -> CaptureStatusResponse:
    return CaptureStatusResponse(
        is_capturing=capture_state.is_capturing,
        interface=capture_state.interface,
        started_at=capture_state.started_at,
        total_packets=capture_state.aggregator.get_metrics().total_packets,
        total_bytes=capture_state.aggregator.get_metrics().total_bytes,
        error=capture_state.error,
    )


@router.get("/status", response_model=CaptureStatusResponse)
async def get_status() -> CaptureStatusResponse:
    """Return current capture status and basic metrics."""
    return _status_response()


@router.post("/start", response_model=CaptureStatusResponse)
async def start(req: StartCaptureRequest) -> CaptureStatusResponse:
    """Start packet capture on the requested interface."""
    iface = req.interface.strip()

    # Validate interface exists
    try:
        from scapy.arch import get_if_list

        available = get_if_list()
    except Exception:
        available = []

    if available and iface not in available:
        raise HTTPException(
            status_code=400,
            detail=f"Interface '{iface}' not found. Available: {', '.join(available)}",
        )

    if capture_state.is_capturing:
        raise HTTPException(status_code=409, detail="Capture is already running.")

    try:
        start_capture(iface)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    # Give the worker a moment to transition to RUNNING or ERROR
    import time
    for _ in range(10):
        time.sleep(0.1)
        if capture_state.status in (CaptureStatus.RUNNING, CaptureStatus.ERROR):
            break

    resp = _status_response()
    if capture_state.status == CaptureStatus.ERROR:
        raise HTTPException(status_code=500, detail=resp.error or "Capture failed to start")

    return resp


@router.post("/stop", response_model=CaptureStatusResponse)
async def stop() -> CaptureStatusResponse:
    """Stop the running capture."""
    if not capture_state.is_capturing and not capture_state.has_worker():
        raise HTTPException(status_code=409, detail="No capture is running.")

    stop_capture()
    return _status_response()


@router.get("/export/csv")
async def export_csv() -> StreamingResponse:
    """Export captured packet metadata as CSV.

    Works whether or not a capture is currently running.
    """
    packets = capture_state.aggregator.get_all_packets()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["timestamp", "src_ip", "dst_ip", "protocol", "length", "info"])
    for pkt in packets:
        writer.writerow([pkt.timestamp, pkt.src_ip, pkt.dst_ip, pkt.protocol, pkt.length, pkt.info])

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=capture.csv"},
    )

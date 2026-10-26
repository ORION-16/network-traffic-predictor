"""REST endpoints for capture control and data export."""

from __future__ import annotations

import csv
import io
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from fastapi import Query
from starlette.concurrency import run_in_threadpool

from capture.packet_rates import capture_availability, probe_capture
from capture.sniffer import start_capture, stop_capture
from capture.state import CaptureStatus, capture_state
from core.config import settings
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
        demo_mode=settings.demo_mode,
    )


@router.get("/status", response_model=CaptureStatusResponse)
async def get_status() -> CaptureStatusResponse:
    """Return current capture status and basic metrics."""
    return _status_response()


@router.post("/start", response_model=CaptureStatusResponse)
async def start(req: StartCaptureRequest) -> CaptureStatusResponse:
    """Start packet capture on the requested interface."""
    iface = req.interface.strip()

    if not settings.demo_mode:
        availability = capture_availability(iface)
        if not availability["available"]:
            raise HTTPException(status_code=400, detail=availability["reason"])

    if capture_state.is_capturing:
        raise HTTPException(status_code=409, detail="Capture is already running.")

    try:
        start_capture(iface)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    # Give the worker a moment to transition to RUNNING or ERROR
    import asyncio

    for _ in range(30):
        await asyncio.sleep(0.1)
        if capture_state.status in (CaptureStatus.RUNNING, CaptureStatus.ERROR):
            break

    resp = _status_response()
    if capture_state.status == CaptureStatus.ERROR:
        raise HTTPException(status_code=500, detail=resp.error or "Capture failed to start")

    return resp


@router.get("/availability")
async def availability(interface: str | None = None) -> dict:
    """Whether Scapy capture can be attempted on the monitored interface. Starts nothing."""
    from monitoring.collector import monitoring_collector

    name = (interface or monitoring_collector.selected_name() or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="No interface is selected.")
    result = await run_in_threadpool(capture_availability, name)
    result["authoritative_source"] = "psutil.net_io_counters"
    result["role"] = "diagnostic comparison only; packet bytes are never added to counter bytes"
    return result


@router.post("/compare")
async def compare(seconds: float = Query(default=5.0, ge=1.0, le=15.0)) -> dict:
    """Capture metadata for a bounded window and compare with OS counters over the same window."""
    from monitoring.collector import monitoring_collector

    if capture_state.is_capturing or capture_state.has_worker():
        raise HTTPException(status_code=409, detail="Stop the running capture before a comparison.")
    name = monitoring_collector.selected_name()
    if not name:
        raise HTTPException(status_code=400, detail="No interface is selected.")
    result = await run_in_threadpool(probe_capture, name, seconds)
    result["interface"] = name
    return result


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

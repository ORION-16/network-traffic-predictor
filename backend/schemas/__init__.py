"""Pydantic schemas for API request / response validation."""

from __future__ import annotations

from pydantic import BaseModel, Field


# ── Interface ──────────────────────────────────────────────────────────

class InterfaceInfo(BaseModel):
    name: str
    description: str = ""
    is_up: bool = False
    is_loopback: bool = False


class InterfaceListResponse(BaseModel):
    interfaces: list[InterfaceInfo]


# ── Capture control ───────────────────────────────────────────────────

class StartCaptureRequest(BaseModel):
    interface: str = Field(..., min_length=1, description="Network interface name")


class CaptureStatusResponse(BaseModel):
    is_capturing: bool
    interface: str | None = None
    started_at: float | None = None
    total_packets: int = 0
    total_bytes: int = 0
    error: str | None = None


# ── Packet metadata ──────────────────────────────────────────────────

class PacketMeta(BaseModel):
    timestamp: float
    src_ip: str
    dst_ip: str
    protocol: str
    length: int
    info: str = ""


# ── Live metrics (sent via WebSocket) ────────────────────────────────

class LiveMetrics(BaseModel):
    total_packets: int = 0
    total_bytes: int = 0
    packet_rate: float = 0.0
    throughput: float = 0.0  # bytes per second
    protocol_distribution: dict[str, int] = Field(default_factory=dict)


class WSUpdate(BaseModel):
    """Incremental WebSocket push — never sends the full history."""

    metrics: LiveMetrics
    new_packets: list[PacketMeta] = Field(default_factory=list)
    traffic_series: list[TrafficPoint] = Field(default_factory=list)
    is_capturing: bool = False
    error: str | None = None


class TrafficPoint(BaseModel):
    """One data point for the traffic-over-time chart."""

    timestamp: float
    packets: int
    bytes_: int = Field(alias="bytes")

    model_config = {"populate_by_name": True}


# Rebuild WSUpdate so the forward-ref to TrafficPoint resolves.
WSUpdate.model_rebuild()


# ── Error ─────────────────────────────────────────────────────────────

class ErrorResponse(BaseModel):
    detail: str

"""WebSocket endpoint for streaming live capture updates.

Pushes incremental updates at a controlled interval. Supports
reconnection by tracking per-connection cursors so clients
never receive the full history after reconnecting.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from capture.state import capture_state
from core.config import settings
from schemas import WSUpdate

router = APIRouter()
logger = logging.getLogger(__name__)

# Track connected clients for clean shutdown
_active_connections: set[WebSocket] = set()


@router.websocket("/ws/capture")
async def capture_ws(ws: WebSocket) -> None:
    await ws.accept()
    _active_connections.add(ws)
    logger.info("WebSocket client connected (%d total)", len(_active_connections))

    cursor = capture_state.aggregator.get_cursor()

    try:
        while True:
            # Build incremental update
            new_packets, cursor = capture_state.aggregator.get_new_packets(cursor)
            metrics = capture_state.aggregator.get_metrics()
            traffic = capture_state.aggregator.get_traffic_series()

            update = WSUpdate(
                metrics=metrics,
                new_packets=new_packets,
                traffic_series=traffic,
                is_capturing=capture_state.is_capturing,
                error=capture_state.error,
            )

            await ws.send_json(update.model_dump(by_alias=True))
            await asyncio.sleep(settings.ws_interval)

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as exc:
        logger.warning("WebSocket error: %s", exc)
    finally:
        _active_connections.discard(ws)


async def close_all_connections() -> None:
    """Gracefully close all WebSocket connections on shutdown."""
    for ws in list(_active_connections):
        try:
            await ws.close()
        except Exception:
            pass
    _active_connections.clear()

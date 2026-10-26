"""REST endpoints for listing network interfaces."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from monitoring.interfaces import discover_interfaces
from schemas import InterfaceInfo, InterfaceListResponse

router = APIRouter(prefix="/api/interfaces", tags=["interfaces"])
logger = logging.getLogger(__name__)


@router.get("", response_model=InterfaceListResponse)
async def list_interfaces() -> InterfaceListResponse:
    """Return interfaces on this computer.

    The default-route flag is the up, non-loopback interface that owns the
    host's outbound IPv4 path. Addresses are not included.
    """
    try:
        records = discover_interfaces()
    except Exception as exc:
        logger.warning("Could not enumerate interfaces: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Cannot list network interfaces on this system: {type(exc).__name__}",
        ) from exc

    if not records:
        raise HTTPException(status_code=500, detail="Cannot list network interfaces on this system.")

    return InterfaceListResponse(
        interfaces=[InterfaceInfo(**record.as_dict()) for record in records]
    )

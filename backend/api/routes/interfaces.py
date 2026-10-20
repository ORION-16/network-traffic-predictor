"""REST endpoints for listing network interfaces."""

from __future__ import annotations

import logging
import platform

from fastapi import APIRouter, HTTPException

from schemas import InterfaceInfo, InterfaceListResponse

router = APIRouter(prefix="/api/interfaces", tags=["interfaces"])
logger = logging.getLogger(__name__)


@router.get("", response_model=InterfaceListResponse)
async def list_interfaces() -> InterfaceListResponse:
    """Return available network interfaces.

    Uses psutil when available, falls back to netifaces or socket.
    Never exposes sensitive system information beyond interface names.
    """
    interfaces: list[InterfaceInfo] = []

    try:
        import psutil

        stats = psutil.net_if_stats()
        for name, snic in stats.items():
            interfaces.append(
                InterfaceInfo(
                    name=name,
                    description="",
                    is_up=snic.isup,
                    is_loopback=(name.startswith("lo")),
                )
            )
    except ImportError:
        # Fallback: enumerate via socket
        try:
            import socket
            import struct
            import fcntl
            import array

            if platform.system() == "Darwin":
                # macOS: use scapy's get_if_list
                try:
                    from scapy.arch import get_if_list

                    for name in get_if_list():
                        interfaces.append(
                            InterfaceInfo(
                                name=name,
                                description="",
                                is_up=True,
                                is_loopback=name.startswith("lo"),
                            )
                        )
                except Exception:
                    pass
            else:
                from scapy.arch import get_if_list

                for name in get_if_list():
                    interfaces.append(
                        InterfaceInfo(
                            name=name,
                            description="",
                            is_up=True,
                            is_loopback=name.startswith("lo"),
                        )
                    )
        except Exception as exc:
            logger.warning("Could not enumerate interfaces: %s", exc)

    if not interfaces:
        # Last-ditch attempt with scapy
        try:
            from scapy.arch import get_if_list

            for name in get_if_list():
                interfaces.append(
                    InterfaceInfo(
                        name=name,
                        description="",
                        is_up=True,
                        is_loopback=name.startswith("lo"),
                    )
                )
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Cannot list network interfaces on this system: {type(exc).__name__}",
            )

    return InterfaceListResponse(interfaces=interfaces)

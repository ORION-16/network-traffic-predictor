"""Discover local interfaces and choose the default-route interface.

No interface name is assumed. The preferred interface is the one that owns
the source address of a connected UDP socket toward a public address. That
socket is not used to send traffic. NIC-reported link speed is descriptive
only and is never a bottleneck capacity.
"""

from __future__ import annotations

import json
import logging
import platform
import re
import socket
import subprocess
import threading
import time
from dataclasses import asdict, dataclass

logger = logging.getLogger(__name__)

_WINDOWS_CACHE_LOCK = threading.Lock()
_WINDOWS_CACHE: dict[str, object] = {"at": 0.0, "rows": {}}
_WINDOWS_CACHE_SECONDS = 60.0

_VPN_WORDS = (
    "vpn",
    "tun",
    "tap",
    "wireguard",
    "wintun",
    "nordlynx",
    "tailscale",
    "zerotier",
    "openvpn",
    "anyconnect",
    "ipsec",
    "pptp",
    "l2tp",
    "sstp",
    "ikev2",
    "ppp",
)
_VIRTUAL_WORDS = (
    "virtual",
    "vethernet",
    "hyper-v",
    "vmware",
    "virtualbox",
    "vbox",
    "wsl",
    "docker",
    "vnic",
    "pseudo",
    "bluetooth",
    "awdl",
    "llw",
    "utun",
)
_BRIDGE_WORDS = ("bridge",)
_LOOPBACK_WORDS = ("loopback", "lo")


@dataclass(frozen=True)
class InterfaceRecord:
    name: str
    description: str
    is_up: bool
    is_loopback: bool
    kind: str
    kind_source: str
    medium: str
    is_default_route: bool
    reported_link_speed_mbps: float | None
    link_speed_status: str
    os_link_speed_text: str | None
    reported_duplex: str

    def as_dict(self) -> dict:
        return asdict(self)


def default_route_ipv4() -> str | None:
    """Return the local IPv4 chosen for an outbound route, without sending payload."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(2.0)
        sock.connect(("1.1.1.1", 443))
        address = sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()
    if not address or address.startswith("127."):
        return None
    return address


def _contains_any(text: str, words: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in words)


def classify_interface(
    name: str,
    description: str = "",
    *,
    virtual: bool | None = None,
    hardware: bool | None = None,
    media_type: str = "",
) -> tuple[str, str, str]:
    """Return (kind, kind_source, medium).

    kind is physical, virtual, loopback, vpn, bridge, or unknown.
    """
    blob = f"{name} {description}".strip()
    medium = "unknown"
    media = (media_type or "").lower()
    if "802.11" in media or "wi-fi" in blob.lower() or "wifi" in blob.lower() or "wlan" in blob.lower():
        medium = "wifi"
    elif "802.3" in media or "ethernet" in blob.lower():
        medium = "ethernet"

    if name.lower() in {"lo", "lo0"} or _contains_any(blob, ("loopback",)):
        return "loopback", "name", "loopback"

    source = "windows_adapter" if virtual is not None or hardware is not None else "name_heuristic"

    if _contains_any(blob, _VPN_WORDS) or name.lower().startswith("utun"):
        return "vpn", source if virtual is not None else "name_heuristic", medium
    if _contains_any(blob, _BRIDGE_WORDS):
        return "bridge", source if virtual is not None else "name_heuristic", medium
    if virtual is True or _contains_any(blob, _VIRTUAL_WORDS):
        return "virtual", source, medium
    if hardware is True:
        return "physical", "windows_adapter", medium
    if source == "name_heuristic" and medium in {"wifi", "ethernet"}:
        return "physical", "name_heuristic", medium
    return "unknown", source, medium


def parse_link_speed_text(text: str | None) -> float | None:
    """Parse an OS speed string into decimal Mbps. Returns None when it is not a speed."""
    if not text:
        return None
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*([kmg])?bps", text.strip(), flags=re.IGNORECASE)
    if not match:
        return None
    value = float(match.group(1))
    unit = (match.group(2) or "").lower()
    if value <= 0:
        return None
    if unit == "g":
        return value * 1000
    if unit == "k":
        return value / 1000
    if unit == "m" or unit == "":
        return value
    return None


def _duplex_name(value: int) -> str:
    try:
        import psutil

        if value == psutil.NIC_DUPLEX_FULL:
            return "full"
        if value == psutil.NIC_DUPLEX_HALF:
            return "half"
    except Exception:
        pass
    return "unknown"


def _windows_adapter_rows() -> dict[str, dict]:
    """Fixed, non-interactive Get-NetAdapter query. User input is never interpolated."""
    now = time.monotonic()
    with _WINDOWS_CACHE_LOCK:
        cached_at = float(_WINDOWS_CACHE["at"])
        cached_rows = _WINDOWS_CACHE["rows"]
        if isinstance(cached_rows, dict) and now - cached_at < _WINDOWS_CACHE_SECONDS:
            return cached_rows

    if platform.system() != "Windows":
        return {}

    command = (
        "Get-NetAdapter | Select-Object Name, InterfaceDescription, Status, "
        "LinkSpeed, HardwareInterface, Virtual, MediaType | ConvertTo-Json -Compress"
    )
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            timeout=8,
            shell=False,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("Windows adapter query failed: %s", exc)
        return {}

    if completed.returncode != 0 or not completed.stdout.strip():
        logger.warning("Windows adapter query returned no metadata")
        return {}

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        logger.warning("Windows adapter query returned malformed JSON")
        return {}

    rows = payload if isinstance(payload, list) else [payload]
    mapped: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict) or not row.get("Name"):
            continue
        mapped[str(row["Name"])] = {
            "description": str(row.get("InterfaceDescription") or ""),
            "virtual": row.get("Virtual"),
            "hardware": row.get("HardwareInterface"),
            "media_type": str(row.get("MediaType") or ""),
            "link_speed_text": str(row.get("LinkSpeed") or ""),
        }

    with _WINDOWS_CACHE_LOCK:
        _WINDOWS_CACHE["at"] = time.monotonic()
        _WINDOWS_CACHE["rows"] = mapped
    return mapped


def clear_windows_adapter_cache() -> None:
    with _WINDOWS_CACHE_LOCK:
        _WINDOWS_CACHE["at"] = 0.0
        _WINDOWS_CACHE["rows"] = {}


def discover_interfaces() -> list[InterfaceRecord]:
    """List interfaces. Addresses and hardware addresses are not returned."""
    import psutil

    stats = psutil.net_if_stats()
    addrs = psutil.net_if_addrs()
    route_ip = default_route_ipv4()
    metadata = _windows_adapter_rows()

    default_names: set[str] = set()
    if route_ip:
        for name, address_list in addrs.items():
            for address in address_list:
                if address.family == socket.AF_INET and address.address == route_ip:
                    default_names.add(name)

    records: list[InterfaceRecord] = []
    for name, snic in stats.items():
        meta = metadata.get(name, {})
        description = str(meta.get("description") or "")
        virtual = meta.get("virtual")
        hardware = meta.get("hardware")
        virtual_flag = bool(virtual) if isinstance(virtual, bool) else None
        hardware_flag = bool(hardware) if isinstance(hardware, bool) else None
        kind, kind_source, medium = classify_interface(
            name,
            description,
            virtual=virtual_flag,
            hardware=hardware_flag,
            media_type=str(meta.get("media_type") or ""),
        )
        speed = float(snic.speed) if snic.speed and snic.speed > 0 else None
        os_text = meta.get("link_speed_text") or None
        if isinstance(os_text, str) and parse_link_speed_text(os_text) is None:
            os_text = None
        records.append(
            InterfaceRecord(
                name=name,
                description=description,
                is_up=bool(snic.isup),
                is_loopback=kind == "loopback",
                kind=kind,
                kind_source=kind_source,
                medium=medium,
                is_default_route=name in default_names and kind != "loopback",
                reported_link_speed_mbps=speed,
                link_speed_status="reported" if speed is not None else "unknown",
                os_link_speed_text=os_text if isinstance(os_text, str) else None,
                reported_duplex=_duplex_name(int(snic.duplex)),
            )
        )

    records.sort(key=lambda item: (not item.is_default_route, not item.is_up, item.is_loopback, item.name.lower()))
    return records


def default_route_interface() -> str | None:
    """Cheap route owner lookup for the sampler thread. It does not spawn processes."""
    import psutil

    route_ip = default_route_ipv4()
    if not route_ip:
        return None
    stats = psutil.net_if_stats()
    for name, address_list in psutil.net_if_addrs().items():
        snic = stats.get(name)
        if snic is None or not snic.isup:
            continue
        if any(address.family == socket.AF_INET and address.address == route_ip for address in address_list):
            return name
    return None


def preferred_interface_name(records: list[InterfaceRecord] | None = None) -> str | None:
    """Select the up, non-loopback interface that owns the default route."""
    items = records if records is not None else discover_interfaces()
    for record in items:
        if record.is_default_route and record.is_up and not record.is_loopback:
            return record.name
    return None

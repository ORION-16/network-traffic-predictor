"""Direction-aware packet byte counts from Scapy, for comparison with OS counters.

Observed bytes are ``len(packet)`` as delivered by the capture driver. On
Ethernet and Npcap Wi-Fi capture this is the link-layer frame without the
frame check sequence. OS byte counters may count differently (offloaded
segmentation, headers, retransmissions, filtered packets), so the two
sources are compared, never added together.

Direction uses the interface's own addresses: a packet whose source is a
local address is transmit, whose destination is local, broadcast, or
multicast is receive. Packets that match neither are counted as ``other``
and excluded from both rates. Capture is not promiscuous. Payloads are never
stored.

Measured on this Windows/Npcap Wi-Fi host, Scapy matched the counters within
about 2% at idle but saw only about half the received packets during a fast
download, because the per-packet Python callback drops packets under load.
That is why the counters stay the stored source.
"""

from __future__ import annotations

import logging
import platform
import socket
import threading
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


def local_addresses(interface_name: str) -> tuple[set[str], set[str]]:
    """Return (ip_addresses, mac_addresses) for one interface. Not returned by the API."""
    import psutil

    ips: set[str] = set()
    macs: set[str] = set()
    for address in psutil.net_if_addrs().get(interface_name, []):
        if address.family in (socket.AF_INET, socket.AF_INET6):
            ips.add(address.address.split("%")[0].lower())
        elif address.address and len(address.address.replace("-", ":").split(":")) == 6:
            macs.add(address.address.replace("-", ":").lower())
    return ips, macs


def resolve_scapy_interface(interface_name: str):
    """Map an OS interface name to Scapy's interface object. Raises LookupError."""
    import scapy.all  # noqa: F401  Loads the platform interface provider.
    from scapy.config import conf

    if conf.ifaces is None:
        raise LookupError("Scapy did not load an interface list on this system.")
    try:
        conf.ifaces.reload()
    except Exception:
        pass
    for candidate in conf.ifaces.values():
        names = {
            str(getattr(candidate, "name", "") or ""),
            str(getattr(candidate, "network_name", "") or ""),
            str(getattr(candidate, "description", "") or ""),
        }
        if interface_name in names:
            return candidate
    raise LookupError(f"Scapy has no capture interface named {interface_name!r}.")


def capture_availability(interface_name: str) -> dict:
    """Describe whether Scapy capture can be attempted. Does not start a capture."""
    result = {
        "interface": interface_name,
        "scapy_installed": False,
        "driver": None,
        "available": False,
        "reason": None,
    }
    try:
        import scapy  # noqa: F401
        from scapy.config import conf
    except Exception as exc:
        result["reason"] = f"Scapy is not installed: {exc}"
        return result
    result["scapy_installed"] = True
    system = platform.system()
    if system == "Windows":
        result["driver"] = "npcap" if conf.use_pcap or _npcap_present() else None
        if result["driver"] is None:
            result["reason"] = "Npcap was not found. Install Npcap from https://npcap.com to capture on Windows."
            return result
    elif system == "Darwin":
        result["driver"] = "bpf"
    else:
        result["driver"] = "af_packet"
    try:
        resolve_scapy_interface(interface_name)
    except LookupError as exc:
        result["reason"] = str(exc)
        return result
    result["available"] = True
    result["reason"] = "Capture can be attempted. Permission is checked when capture starts."
    return result


def _npcap_present() -> bool:
    from pathlib import Path

    return Path(r"C:\Windows\System32\Npcap").exists()


@dataclass
class DirectionCounts:
    rx_bytes: int = 0
    tx_bytes: int = 0
    other_bytes: int = 0
    rx_packets: int = 0
    tx_packets: int = 0
    other_packets: int = 0


@dataclass
class PacketRateMeter:
    """Thread-safe byte totals by direction for one interface."""

    interface_name: str
    ips: set[str] = field(default_factory=set)
    macs: set[str] = field(default_factory=set)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    counts: DirectionCounts = field(default_factory=DirectionCounts)

    @classmethod
    def for_interface(cls, interface_name: str) -> "PacketRateMeter":
        ips, macs = local_addresses(interface_name)
        return cls(interface_name=interface_name, ips=ips, macs=macs)

    def classify(self, src_ip: str | None, dst_ip: str | None, src_mac: str | None, dst_mac: str | None) -> str:
        """tx, rx, or other. Broadcast and multicast frames delivered to this host are rx."""
        src_ip = (src_ip or "").lower()
        dst_ip = (dst_ip or "").lower()
        src_mac = (src_mac or "").lower()
        dst_mac = (dst_mac or "").lower()
        if src_ip and src_ip in self.ips:
            return "tx"
        if src_mac and src_mac in self.macs:
            return "tx"
        if dst_ip and dst_ip in self.ips:
            return "rx"
        if dst_mac and dst_mac in self.macs:
            return "rx"
        if _group_mac(dst_mac) or _group_ip(dst_ip):
            return "rx"
        return "other"

    def add(self, direction: str, length: int) -> None:
        with self._lock:
            if direction == "rx":
                self.counts.rx_bytes += length
                self.counts.rx_packets += 1
            elif direction == "tx":
                self.counts.tx_bytes += length
                self.counts.tx_packets += 1
            else:
                self.counts.other_bytes += length
                self.counts.other_packets += 1

    def add_packet(self, pkt) -> None:
        src_ip = dst_ip = src_mac = dst_mac = None
        try:
            from scapy.layers.inet import IP
            from scapy.layers.inet6 import IPv6
            from scapy.layers.l2 import Ether

            if pkt.haslayer(IP):
                src_ip, dst_ip = pkt[IP].src, pkt[IP].dst
            elif pkt.haslayer(IPv6):
                src_ip, dst_ip = pkt[IPv6].src, pkt[IPv6].dst
            if pkt.haslayer(Ether):
                src_mac, dst_mac = pkt[Ether].src, pkt[Ether].dst
        except Exception:
            pass
        self.add(self.classify(src_ip, dst_ip, src_mac, dst_mac), len(pkt))

    def snapshot(self) -> DirectionCounts:
        with self._lock:
            return DirectionCounts(**vars(self.counts))


def _group_mac(mac: str) -> bool:
    if not mac:
        return False
    try:
        return int(mac.split(":")[0], 16) & 1 == 1
    except ValueError:
        return False


def _group_ip(ip: str) -> bool:
    if not ip:
        return False
    if ip.startswith("ff"):
        return True
    if ip == "255.255.255.255" or ip.endswith(".255"):
        return True
    head = ip.split(".")[0]
    return head.isdigit() and 224 <= int(head) <= 239


def mbps(byte_count: int, elapsed: float) -> float | None:
    if elapsed <= 0:
        return None
    return byte_count * 8 / elapsed / 1_000_000


def probe_capture(interface_name: str, seconds: float = 5.0) -> dict:
    """Capture for a fixed time and compare with the OS counters over the same window."""
    import psutil

    availability = capture_availability(interface_name)
    result: dict = {"availability": availability, "status": "unavailable", "seconds": seconds}
    if not availability["available"]:
        result["error"] = availability["reason"]
        return result
    meter = PacketRateMeter.for_interface(interface_name)
    before = psutil.net_io_counters(pernic=True).get(interface_name)
    started = time.monotonic()
    try:
        from scapy.all import sniff

        iface = resolve_scapy_interface(interface_name)
        sniff(iface=iface, prn=meter.add_packet, store=False, timeout=seconds, promisc=False)
    except PermissionError as exc:
        result["status"] = "permission_denied"
        result["error"] = f"Capture needs elevated rights or Npcap user access: {exc}"
        return result
    except Exception as exc:
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result
    elapsed = time.monotonic() - started
    after = psutil.net_io_counters(pernic=True).get(interface_name)
    counts = meter.snapshot()
    result.update(
        {
            "status": "ok",
            "elapsed_seconds": elapsed,
            "packet": {
                "rx_mbps": mbps(counts.rx_bytes, elapsed),
                "tx_mbps": mbps(counts.tx_bytes, elapsed),
                "rx_packets": counts.rx_packets,
                "tx_packets": counts.tx_packets,
                "other_packets": counts.other_packets,
                "other_bytes": counts.other_bytes,
            },
            "counters": None,
        }
    )
    if before is not None and after is not None:
        result["counters"] = {
            "rx_mbps": mbps(after.bytes_recv - before.bytes_recv, elapsed),
            "tx_mbps": mbps(after.bytes_sent - before.bytes_sent, elapsed),
            "rx_packets": after.packets_recv - before.packets_recv,
            "tx_packets": after.packets_sent - before.packets_sent,
        }
        counter = result["counters"]
        result["packet_coverage"] = {
            "rx": counts.rx_packets / counter["rx_packets"] if counter["rx_packets"] > 0 else None,
            "tx": counts.tx_packets / counter["tx_packets"] if counter["tx_packets"] > 0 else None,
            "note": "Share of OS-counted packets that Scapy observed. Below 1 means capture missed packets.",
        }
    result["note"] = (
        "Packet bytes and OS counter bytes are separate measurements of the same traffic. "
        "They are compared, not summed."
    )
    return result

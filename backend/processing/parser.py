"""Extract safe metadata from a Scapy packet — never touches payloads."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scapy.packet import Packet

from schemas import PacketMeta

# Map IP protocol numbers to human-readable names.
_PROTO_MAP: dict[int, str] = {
    1: "ICMP",
    2: "IGMP",
    6: "TCP",
    17: "UDP",
    41: "IPv6-encap",
    47: "GRE",
    50: "ESP",
    51: "AH",
    58: "ICMPv6",
    89: "OSPF",
    132: "SCTP",
}


def parse_packet(pkt: "Packet") -> PacketMeta | None:
    """Return a PacketMeta for *pkt*, or None if it has no IP layer."""
    from scapy.layers.inet import IP, TCP, UDP, ICMP
    from scapy.layers.inet6 import IPv6

    ts = float(pkt.time) if hasattr(pkt, "time") else time.time()
    length = len(pkt)

    # ── IPv4 ─────────────────────────────────────────────────────
    if pkt.haslayer(IP):
        ip = pkt[IP]
        proto_num = ip.proto
        protocol = _PROTO_MAP.get(proto_num, f"IP/{proto_num}")
        info = _build_info(pkt, protocol)
        return PacketMeta(
            timestamp=ts,
            src_ip=ip.src,
            dst_ip=ip.dst,
            protocol=protocol,
            length=length,
            info=info,
        )

    # ── IPv6 ─────────────────────────────────────────────────────
    if pkt.haslayer(IPv6):
        ipv6 = pkt[IPv6]
        proto_num = ipv6.nh
        protocol = _PROTO_MAP.get(proto_num, f"IPv6/{proto_num}")
        info = _build_info(pkt, protocol)
        return PacketMeta(
            timestamp=ts,
            src_ip=ipv6.src,
            dst_ip=ipv6.dst,
            protocol=protocol,
            length=length,
            info=info,
        )

    # ── ARP and other non-IP ─────────────────────────────────────
    from scapy.layers.l2 import ARP

    if pkt.haslayer(ARP):
        arp = pkt[ARP]
        return PacketMeta(
            timestamp=ts,
            src_ip=arp.psrc or "0.0.0.0",
            dst_ip=arp.pdst or "0.0.0.0",
            protocol="ARP",
            length=length,
            info=f"op={arp.op}",
        )

    return None


def _build_info(pkt: "Packet", protocol: str) -> str:
    """Build a short info string (ports, flags) without exposing payloads."""
    from scapy.layers.inet import TCP, UDP

    parts: list[str] = []
    if pkt.haslayer(TCP):
        tcp = pkt[TCP]
        parts.append(f"{tcp.sport}→{tcp.dport}")
        flags = str(tcp.flags)
        if flags:
            parts.append(f"[{flags}]")
    elif pkt.haslayer(UDP):
        udp = pkt[UDP]
        parts.append(f"{udp.sport}→{udp.dport}")
    return " ".join(parts)

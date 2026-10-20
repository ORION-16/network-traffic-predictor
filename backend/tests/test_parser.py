"""Tests for processing.parser — packet metadata extraction."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from processing.parser import parse_packet


def _make_ip_packet(
    src: str = "192.168.1.1",
    dst: str = "10.0.0.1",
    proto: int = 6,
    sport: int = 12345,
    dport: int = 80,
    length: int = 100,
    flags: str = "S",
) -> MagicMock:
    """Create a mock Scapy packet with IP + TCP layers."""
    pkt = MagicMock()
    pkt.time = time.time()
    pkt.__len__.return_value = length

    # IP layer
    ip_layer = MagicMock()
    ip_layer.src = src
    ip_layer.dst = dst
    ip_layer.proto = proto

    # TCP layer
    tcp_layer = MagicMock()
    tcp_layer.sport = sport
    tcp_layer.dport = dport
    tcp_layer.flags = flags

    def has_layer(layer_cls):
        name = layer_cls.__name__ if hasattr(layer_cls, "__name__") else str(layer_cls)
        if name == "IP":
            return True
        if name == "TCP" and proto == 6:
            return True
        if name == "UDP" and proto == 17:
            return True
        return False

    pkt.haslayer.side_effect = has_layer

    def get_item(layer_cls):
        name = layer_cls.__name__ if hasattr(layer_cls, "__name__") else str(layer_cls)
        if name == "IP":
            return ip_layer
        if name == "TCP":
            return tcp_layer
        return MagicMock()

    pkt.__getitem__.side_effect = get_item
    return pkt


def _make_udp_packet(
    src: str = "192.168.1.2",
    dst: str = "8.8.8.8",
    sport: int = 50000,
    dport: int = 53,
    length: int = 60,
) -> MagicMock:
    """Create a mock Scapy UDP packet."""
    pkt = MagicMock()
    pkt.time = time.time()
    pkt.__len__.return_value = length

    ip_layer = MagicMock()
    ip_layer.src = src
    ip_layer.dst = dst
    ip_layer.proto = 17

    udp_layer = MagicMock()
    udp_layer.sport = sport
    udp_layer.dport = dport

    def has_layer(layer_cls):
        name = layer_cls.__name__ if hasattr(layer_cls, "__name__") else str(layer_cls)
        if name == "IP":
            return True
        if name == "UDP":
            return True
        return False

    pkt.haslayer.side_effect = has_layer

    def get_item(layer_cls):
        name = layer_cls.__name__ if hasattr(layer_cls, "__name__") else str(layer_cls)
        if name == "IP":
            return ip_layer
        if name == "UDP":
            return udp_layer
        return MagicMock()

    pkt.__getitem__.side_effect = get_item
    return pkt


def _make_non_ip_packet() -> MagicMock:
    """Create a mock packet with no IP/IPv6/ARP layer."""
    pkt = MagicMock()
    pkt.time = time.time()
    pkt.__len__.return_value = 42
    pkt.haslayer.return_value = False
    return pkt


class TestParsePacket:
    def test_tcp_packet(self):
        pkt = _make_ip_packet(src="1.2.3.4", dst="5.6.7.8", sport=443, dport=54321, flags="SA")
        meta = parse_packet(pkt)
        assert meta is not None
        assert meta.src_ip == "1.2.3.4"
        assert meta.dst_ip == "5.6.7.8"
        assert meta.protocol == "TCP"
        assert "443→54321" in meta.info
        assert "[SA]" in meta.info

    def test_udp_packet(self):
        pkt = _make_udp_packet(src="10.0.0.1", dst="8.8.4.4", sport=12345, dport=53)
        meta = parse_packet(pkt)
        assert meta is not None
        assert meta.protocol == "UDP"
        assert "12345→53" in meta.info

    def test_non_ip_returns_none(self):
        pkt = _make_non_ip_packet()
        meta = parse_packet(pkt)
        assert meta is None

    def test_packet_length(self):
        pkt = _make_ip_packet(length=1500)
        meta = parse_packet(pkt)
        assert meta is not None
        assert meta.length == 1500

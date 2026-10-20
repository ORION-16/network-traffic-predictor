"""Tests for processing.aggregator — metrics aggregation."""

from __future__ import annotations

import time

import pytest

from processing.aggregator import Aggregator
from schemas import PacketMeta


def _meta(protocol: str = "TCP", length: int = 100, ts: float | None = None) -> PacketMeta:
    return PacketMeta(
        timestamp=ts or time.time(),
        src_ip="192.168.1.1",
        dst_ip="10.0.0.1",
        protocol=protocol,
        length=length,
        info="",
    )


class TestAggregator:
    def test_empty_metrics(self):
        agg = Aggregator(max_packets=100)
        m = agg.get_metrics()
        assert m.total_packets == 0
        assert m.total_bytes == 0
        assert m.protocol_distribution == {}

    def test_add_single_packet(self):
        agg = Aggregator(max_packets=100)
        agg.add_packet(_meta(protocol="TCP", length=200))
        m = agg.get_metrics()
        assert m.total_packets == 1
        assert m.total_bytes == 200
        assert m.protocol_distribution == {"TCP": 1}

    def test_protocol_distribution(self):
        agg = Aggregator(max_packets=100)
        agg.add_packet(_meta(protocol="TCP", length=100))
        agg.add_packet(_meta(protocol="UDP", length=60))
        agg.add_packet(_meta(protocol="TCP", length=150))
        m = agg.get_metrics()
        assert m.protocol_distribution["TCP"] == 2
        assert m.protocol_distribution["UDP"] == 1
        assert m.total_packets == 3
        assert m.total_bytes == 310

    def test_bounded_storage(self):
        agg = Aggregator(max_packets=5)
        for i in range(10):
            agg.add_packet(_meta(length=i + 1))
        # Only 5 packets kept in deque
        all_pkts = agg.get_all_packets()
        assert len(all_pkts) == 5
        # But total counters are accurate
        m = agg.get_metrics()
        assert m.total_packets == 10

    def test_incremental_cursor(self):
        agg = Aggregator(max_packets=100)
        cursor = agg.get_cursor()
        assert cursor == 0

        agg.add_packet(_meta(protocol="TCP"))
        agg.add_packet(_meta(protocol="UDP"))

        new, cursor = agg.get_new_packets(0)
        assert len(new) == 2
        assert cursor == 2

        agg.add_packet(_meta(protocol="ICMP"))
        new, cursor = agg.get_new_packets(2)
        assert len(new) == 1
        assert new[0].protocol == "ICMP"
        assert cursor == 3

    def test_reset(self):
        agg = Aggregator(max_packets=100)
        agg.add_packet(_meta())
        agg.reset()
        m = agg.get_metrics()
        assert m.total_packets == 0
        assert agg.get_cursor() == 0
        assert agg.get_all_packets() == []

    def test_traffic_series(self):
        agg = Aggregator(max_packets=100)
        now = time.time()
        agg.add_packet(_meta(ts=now))
        series = agg.get_traffic_series()
        assert len(series) >= 1

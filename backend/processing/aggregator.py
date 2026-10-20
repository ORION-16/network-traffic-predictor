"""Thread-safe aggregation of live capture metrics."""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import TYPE_CHECKING

from core.config import settings
from schemas import LiveMetrics, PacketMeta, TrafficPoint


class Aggregator:
    """Accumulates packet metadata and computes rolling metrics.

    All public methods are thread-safe.  The aggregator owns bounded
    in-memory storage (a deque of PacketMeta) so memory stays under control.
    """

    def __init__(self, max_packets: int = settings.max_packets) -> None:
        self._lock = threading.Lock()
        self._max_packets = max_packets

        # Bounded packet history
        self._packets: deque[PacketMeta] = deque(maxlen=max_packets)

        # Counters
        self._total_packets: int = 0
        self._total_bytes: int = 0
        self._protocol_counts: dict[str, int] = {}

        # Rate tracking (sliding 1-second windows)
        self._rate_window: deque[tuple[float, int]] = deque()
        self._rate_window_size: float = 5.0  # seconds

        # Traffic-over-time buckets (1-second granularity, last 300s)
        self._traffic_series: deque[TrafficPoint] = deque(maxlen=300)
        self._current_bucket_ts: int = 0
        self._current_bucket_pkts: int = 0
        self._current_bucket_bytes: int = 0

        # Cursor so clients only get *new* packets since last read
        self._cursor: int = 0  # next index into _packets
        self._total_ever: int = 0  # monotonic insert count

    # ── Ingest ────────────────────────────────────────────────────

    def add_packet(self, meta: PacketMeta) -> None:
        now = time.time()
        with self._lock:
            self._packets.append(meta)
            self._total_packets += 1
            self._total_bytes += meta.length
            self._protocol_counts[meta.protocol] = (
                self._protocol_counts.get(meta.protocol, 0) + 1
            )
            self._rate_window.append((now, meta.length))
            self._total_ever += 1

            # Traffic-over-time bucketing
            bucket_ts = int(now)
            if bucket_ts == self._current_bucket_ts:
                self._current_bucket_pkts += 1
                self._current_bucket_bytes += meta.length
            else:
                # Flush previous bucket
                if self._current_bucket_ts > 0:
                    self._traffic_series.append(
                        TrafficPoint(
                            timestamp=float(self._current_bucket_ts),
                            packets=self._current_bucket_pkts,
                            **{"bytes": self._current_bucket_bytes},
                        )
                    )
                self._current_bucket_ts = bucket_ts
                self._current_bucket_pkts = 1
                self._current_bucket_bytes = meta.length

    # ── Query ─────────────────────────────────────────────────────

    def get_metrics(self) -> LiveMetrics:
        now = time.time()
        with self._lock:
            # Prune stale rate entries
            cutoff = now - self._rate_window_size
            while self._rate_window and self._rate_window[0][0] < cutoff:
                self._rate_window.popleft()

            elapsed = self._rate_window_size
            pkt_count = len(self._rate_window)
            byte_count = sum(b for _, b in self._rate_window)

            return LiveMetrics(
                total_packets=self._total_packets,
                total_bytes=self._total_bytes,
                packet_rate=round(pkt_count / elapsed, 2),
                throughput=round(byte_count / elapsed, 2),
                protocol_distribution=dict(self._protocol_counts),
            )

    def get_new_packets(self, last_seen: int) -> tuple[list[PacketMeta], int]:
        """Return packets added since *last_seen* cursor, plus the new cursor."""
        with self._lock:
            total = self._total_ever
            available = len(self._packets)
            # How many new since last_seen?
            new_count = total - last_seen
            if new_count <= 0:
                return [], total
            # Clamp to what's still in the deque
            new_count = min(new_count, available)
            result = list(self._packets)[-new_count:]
            return result, total

    def get_all_packets(self) -> list[PacketMeta]:
        with self._lock:
            return list(self._packets)

    def get_cursor(self) -> int:
        with self._lock:
            return self._total_ever

    def get_traffic_series(self, since: float = 0.0) -> list[TrafficPoint]:
        with self._lock:
            # Flush current bucket snapshot
            series = list(self._traffic_series)
            if self._current_bucket_ts > 0:
                series.append(
                    TrafficPoint(
                        timestamp=float(self._current_bucket_ts),
                        packets=self._current_bucket_pkts,
                        **{"bytes": self._current_bucket_bytes},
                    )
                )
            if since > 0:
                series = [s for s in series if s.timestamp >= since]
            return series

    # ── Reset ─────────────────────────────────────────────────────

    def reset(self) -> None:
        with self._lock:
            self._packets.clear()
            self._total_packets = 0
            self._total_bytes = 0
            self._protocol_counts.clear()
            self._rate_window.clear()
            self._traffic_series.clear()
            self._current_bucket_ts = 0
            self._current_bucket_pkts = 0
            self._current_bucket_bytes = 0
            self._total_ever = 0

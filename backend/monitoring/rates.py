"""Convert cumulative interface counters into rates.

Mbps uses decimal SI units:

    Mbps = byte_delta * 8 / elapsed_seconds / 1_000_000

Elapsed time comes from a monotonic clock. A cumulative counter is never
treated as an instantaneous rate. A missing counter stays missing; it is
not rewritten as zero. A zero rate is returned only when both counters
were present and the delta is zero.
"""

from __future__ import annotations

from dataclasses import dataclass

MIN_ELAPSED_SECONDS = 0.05


@dataclass(frozen=True)
class Counters:
    """One reading of cumulative OS counters."""

    monotonic: float
    wall: float
    rx_bytes: int | None
    tx_bytes: int | None
    rx_packets: int | None
    tx_packets: int | None
    rx_errors: int | None
    tx_errors: int | None
    rx_drops: int | None
    tx_drops: int | None


@dataclass(frozen=True)
class RateSample:
    elapsed_seconds: float | None
    rx_mbps: float | None
    tx_mbps: float | None
    rx_pps: float | None
    tx_pps: float | None
    rx_error_per_s: float | None
    tx_error_per_s: float | None
    rx_drop_per_s: float | None
    tx_drop_per_s: float | None
    quality: str
    valid: bool
    note: str


def bytes_to_mbps(byte_delta: int | None, elapsed_seconds: float | None) -> float | None:
    """Decimal Mbps from a byte delta. None when the inputs cannot support a rate."""
    if byte_delta is None or elapsed_seconds is None or elapsed_seconds <= 0:
        return None
    if byte_delta < 0:
        return None
    return (byte_delta * 8) / elapsed_seconds / 1_000_000


def per_second(delta: int | None, elapsed_seconds: float | None) -> float | None:
    if delta is None or elapsed_seconds is None or elapsed_seconds <= 0:
        return None
    if delta < 0:
        return None
    return delta / elapsed_seconds


def _delta(current: int | None, previous: int | None) -> tuple[str, int | None]:
    """Return (status, delta). status is ok, unsupported, or reset."""
    if current is None or previous is None:
        return "unsupported", None
    if current < previous:
        return "reset", None
    return "ok", current - previous


def compute_rate(
    previous: Counters | None,
    current: Counters,
    *,
    interface_changed: bool = False,
    max_elapsed_seconds: float = 15.0,
) -> RateSample:
    """Compare two cumulative readings.

    The caller should ignore a ``too_soon`` result and keep the previous
    baseline. Other qualities are stored. Rates are null unless ``quality``
    is ``ok``.
    """
    def make(quality: str, note: str, elapsed_seconds: float | None = None, **rates: float | None) -> RateSample:
        return RateSample(
            elapsed_seconds=elapsed_seconds,
            rx_mbps=rates.get("rx_mbps"),
            tx_mbps=rates.get("tx_mbps"),
            rx_pps=rates.get("rx_pps"),
            tx_pps=rates.get("tx_pps"),
            rx_error_per_s=rates.get("rx_error_per_s"),
            tx_error_per_s=rates.get("tx_error_per_s"),
            rx_drop_per_s=rates.get("rx_drop_per_s"),
            tx_drop_per_s=rates.get("tx_drop_per_s"),
            quality=quality,
            valid=quality == "ok",
            note=note,
        )

    if previous is None:
        return make(
            "baseline",
            "First reading after start or restart. Cumulative counters are stored; a rate needs a later reading.",
        )
    if interface_changed:
        return make(
            "interface_changed",
            "Interface changed. Counters from the previous interface are not subtracted.",
        )

    elapsed = current.monotonic - previous.monotonic
    if elapsed < MIN_ELAPSED_SECONDS:
        return make(
            "too_soon",
            "Elapsed monotonic time is too small to compute a rate.",
            elapsed_seconds=elapsed,
        )
    if elapsed > max_elapsed_seconds:
        return make(
            "gap",
            "The gap since the previous reading is too large to treat as one sampling interval. Missing samples are not filled in.",
            elapsed_seconds=elapsed,
        )

    byte_statuses = (
        _delta(current.rx_bytes, previous.rx_bytes)[0],
        _delta(current.tx_bytes, previous.tx_bytes)[0],
    )
    if "reset" in byte_statuses:
        return make(
            "counter_reset",
            "A cumulative byte counter decreased. This interval is not converted into a rate.",
            elapsed_seconds=elapsed,
        )

    rx_status, rx_bytes = _delta(current.rx_bytes, previous.rx_bytes)
    tx_status, tx_bytes = _delta(current.tx_bytes, previous.tx_bytes)
    if rx_status == "unsupported" and tx_status == "unsupported":
        return make(
            "unsupported",
            "This reading did not include receive or transmit byte counters.",
            elapsed_seconds=elapsed,
        )

    def _rate_pair(cur, prev):
        status, delta = _delta(cur, prev)
        if status != "ok":
            return None
        return per_second(delta, elapsed)

    note_parts: list[str] = []
    if rx_status == "unsupported":
        note_parts.append("Receive byte counter is unsupported on this reading.")
    if tx_status == "unsupported":
        note_parts.append("Transmit byte counter is unsupported on this reading.")

    wall_delta = current.wall - previous.wall
    if abs(wall_delta - elapsed) > 1.0:
        note_parts.append(
            "Wall-clock change and monotonic elapsed time differ by more than one second. The rate uses monotonic time."
        )

    packet_reset = (
        _delta(current.rx_packets, previous.rx_packets)[0] == "reset"
        or _delta(current.tx_packets, previous.tx_packets)[0] == "reset"
    )
    if packet_reset:
        note_parts.append("A packet counter decreased. Packet rates are omitted for this interval.")

    return make(
        "ok",
        " ".join(note_parts),
        elapsed_seconds=elapsed,
        rx_mbps=bytes_to_mbps(rx_bytes, elapsed) if rx_status == "ok" else None,
        tx_mbps=bytes_to_mbps(tx_bytes, elapsed) if tx_status == "ok" else None,
        rx_pps=None if packet_reset else _rate_pair(current.rx_packets, previous.rx_packets),
        tx_pps=None if packet_reset else _rate_pair(current.tx_packets, previous.tx_packets),
        rx_error_per_s=_rate_pair(current.rx_errors, previous.rx_errors),
        tx_error_per_s=_rate_pair(current.tx_errors, previous.tx_errors),
        rx_drop_per_s=_rate_pair(current.rx_drops, previous.rx_drops),
        tx_drop_per_s=_rate_pair(current.tx_drops, previous.tx_drops),
    )

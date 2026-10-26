"""Unit tests for counter deltas and decimal Mbps conversion."""

from monitoring.rates import Counters, bytes_to_mbps, compute_rate, per_second


def _counters(**overrides) -> Counters:
    base = dict(
        monotonic=10.0,
        wall=100.0,
        rx_bytes=1_000_000,
        tx_bytes=500_000,
        rx_packets=100,
        tx_packets=50,
        rx_errors=1,
        tx_errors=2,
        rx_drops=0,
        tx_drops=0,
    )
    base.update(overrides)
    return Counters(**base)


def test_one_megabit_from_bytes():
    # 125_000 bytes in one second is exactly 1 decimal Mbps.
    assert bytes_to_mbps(125_000, 1.0) == 1.0


def test_mbps_uses_elapsed_time():
    assert bytes_to_mbps(125_000, 2.0) == 0.5


def test_missing_counter_is_not_zero():
    assert bytes_to_mbps(None, 1.0) is None
    assert per_second(None, 1.0) is None


def test_zero_delta_is_a_real_zero():
    assert bytes_to_mbps(0, 1.0) == 0.0


def test_negative_delta_is_not_a_rate():
    assert bytes_to_mbps(-1, 1.0) is None


def test_invalid_elapsed_time():
    assert bytes_to_mbps(125_000, 0) is None
    assert bytes_to_mbps(125_000, -1) is None


def test_first_sample_is_baseline():
    sample = compute_rate(None, _counters())
    assert sample.quality == "baseline"
    assert sample.rx_mbps is None
    assert sample.valid is False


def test_rate_matches_formula():
    previous = _counters()
    current = _counters(
        monotonic=12.5,
        wall=102.5,
        rx_bytes=1_000_000 + 125_000,
        tx_bytes=500_000 + 250_000,
        rx_packets=110,
        tx_packets=60,
        rx_errors=1,
        tx_errors=4,
        rx_drops=0,
        tx_drops=3,
    )
    sample = compute_rate(previous, current, max_elapsed_seconds=15)
    assert sample.quality == "ok"
    assert sample.elapsed_seconds == 2.5
    assert sample.rx_mbps == bytes_to_mbps(125_000, 2.5)
    assert sample.tx_mbps == bytes_to_mbps(250_000, 2.5)
    assert sample.rx_pps == 10 / 2.5
    assert sample.tx_error_per_s == 2 / 2.5
    assert sample.tx_drop_per_s == 3 / 2.5


def test_counter_reset_discards_the_interval():
    previous = _counters(rx_bytes=5000)
    current = _counters(monotonic=11, wall=101, rx_bytes=10)
    sample = compute_rate(previous, current)
    assert sample.quality == "counter_reset"
    assert sample.rx_mbps is None
    assert sample.tx_mbps is None


def test_interface_change_does_not_subtract_old_counters():
    previous = _counters(rx_bytes=100)
    current = _counters(monotonic=11, wall=101, rx_bytes=10_000_000)
    sample = compute_rate(previous, current, interface_changed=True)
    assert sample.quality == "interface_changed"
    assert sample.rx_mbps is None


def test_large_gap_is_not_filled():
    previous = _counters()
    current = _counters(monotonic=40, wall=130, rx_bytes=2_000_000)
    sample = compute_rate(previous, current, max_elapsed_seconds=15)
    assert sample.quality == "gap"
    assert sample.rx_mbps is None


def test_too_soon_sample():
    previous = _counters()
    current = _counters(monotonic=10.01, wall=100.01)
    sample = compute_rate(previous, current)
    assert sample.quality == "too_soon"
    assert sample.valid is False


def test_unsupported_byte_counters():
    previous = _counters(rx_bytes=None, tx_bytes=None)
    current = _counters(monotonic=11, wall=101, rx_bytes=None, tx_bytes=None)
    sample = compute_rate(previous, current)
    assert sample.quality == "unsupported"
    assert sample.rx_mbps is None

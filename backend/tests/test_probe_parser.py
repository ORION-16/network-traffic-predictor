"""Ping output parsing. These fixtures are not live measurements."""

import pytest

from monitoring.probe import parse_ping_output, validate_probe_target


WINDOWS_PING = """
Pinging 1.1.1.1 with 32 bytes of data:
Reply from 1.1.1.1: bytes=32 time=14ms TTL=57
Reply from 1.1.1.1: bytes=32 time=16ms TTL=57
Reply from 1.1.1.1: bytes=32 time=15ms TTL=57

Ping statistics for 1.1.1.1:
    Packets: Sent = 3, Received = 3, Lost = 0 (0% loss),
Approximate round trip times in milli-seconds:
    Minimum = 14ms, Maximum = 16ms, Average = 15ms
"""

UNIX_PING = """
PING 1.1.1.1 (1.1.1.1): 56 data bytes
64 bytes from 1.1.1.1: icmp_seq=0 ttl=57 time=10.5 ms
64 bytes from 1.1.1.1: icmp_seq=1 ttl=57 time=11.5 ms

--- 1.1.1.1 ping statistics ---
2 packets transmitted, 2 received, 0.0% packet loss
"""


def test_windows_ping_rtt_loss_and_jitter():
    parsed = parse_ping_output(WINDOWS_PING, sent_expected=3)
    assert parsed["status"] == "ok"
    assert parsed["sent"] == 3
    assert parsed["received"] == 3
    assert parsed["loss_pct"] == 0
    assert parsed["rtt_avg_ms"] == pytest.approx(15)
    assert parsed["jitter_ms"] == pytest.approx(1.5)


def test_unix_ping_parser():
    parsed = parse_ping_output(UNIX_PING, sent_expected=2)
    assert parsed["status"] == "ok"
    assert parsed["sent"] == 2
    assert parsed["received"] == 2
    assert parsed["rtt_avg_ms"] == pytest.approx(11)


def test_unrecognized_output_does_not_become_zero_loss():
    parsed = parse_ping_output("not a ping", sent_expected=3)
    assert parsed["status"] == "parse_failed"
    assert parsed["loss_pct"] is None
    assert parsed["rtt_avg_ms"] is None


def test_total_loss_has_no_fabricated_rtt():
    text = "Packets: Sent = 3, Received = 0, Lost = 3 (100% loss),"
    parsed = parse_ping_output(text, sent_expected=3)
    assert parsed["status"] == "unreachable"
    assert parsed["loss_pct"] == pytest.approx(100)
    assert parsed["rtt_avg_ms"] is None


def test_probe_target_rejects_shell_metacharacters():
    with pytest.raises(ValueError):
        validate_probe_target("1.1.1.1; whoami")
    with pytest.raises(ValueError):
        validate_probe_target("example.com && ping")
    assert validate_probe_target("1.1.1.1") == "1.1.1.1"
    assert validate_probe_target("one.one.one.one") == "one.one.one.one"

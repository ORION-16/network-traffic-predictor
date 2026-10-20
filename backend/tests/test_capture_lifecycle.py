"""Tests for capture lifecycle — start, stop, error states.

All tests mock Scapy so no root privileges are required.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from capture.state import CaptureState, CaptureStatus


class TestCaptureState:
    def setup_method(self):
        self.state = CaptureState()

    def test_initial_state(self):
        assert self.state.status == CaptureStatus.IDLE
        assert self.state.interface is None
        assert not self.state.is_capturing
        assert self.state.error is None

    def test_start_transition(self):
        self.state.mark_starting("en0")
        assert self.state.status == CaptureStatus.STARTING
        assert self.state.interface == "en0"
        assert self.state.is_capturing

    def test_running_transition(self):
        self.state.mark_starting("en0")
        self.state.mark_running()
        assert self.state.status == CaptureStatus.RUNNING
        assert self.state.is_capturing

    def test_stop_transition(self):
        self.state.mark_starting("en0")
        self.state.mark_running()
        self.state.mark_stopping()
        assert self.state.status == CaptureStatus.STOPPING
        self.state.mark_stopped()
        assert self.state.status == CaptureStatus.IDLE
        assert not self.state.is_capturing

    def test_error_transition(self):
        self.state.mark_starting("en0")
        self.state.mark_error("Permission denied")
        assert self.state.status == CaptureStatus.ERROR
        assert "Permission denied" in self.state.error

    def test_worker_management(self):
        assert not self.state.has_worker()
        thread = threading.Thread(target=lambda: time.sleep(0.1))
        thread.start()
        self.state.set_worker(thread)
        assert self.state.has_worker()
        thread.join()

    def test_aggregator_reset_on_start(self):
        self.state.aggregator.add_packet(
            MagicMock(
                timestamp=time.time(),
                src_ip="1.1.1.1",
                dst_ip="2.2.2.2",
                protocol="TCP",
                length=100,
                info="",
            )
        )
        assert self.state.aggregator.get_metrics().total_packets == 1
        self.state.mark_starting("en0")
        assert self.state.aggregator.get_metrics().total_packets == 0


class TestCaptureLifecycle:
    """Integration-style tests for start/stop with mocked Scapy."""

    def test_start_and_stop(self):
        """Starting and stopping should transition through states cleanly."""
        from capture.state import capture_state as _global
        from capture.sniffer import start_capture, stop_capture

        _global.mark_stopped()
        _global.aggregator.reset()

        def blocking_sniff(**kwargs):
            while not _global.stop_event.is_set():
                time.sleep(0.05)

        with patch("scapy.all.sniff", side_effect=blocking_sniff):
            start_capture("lo0")
            time.sleep(0.2)
            assert _global.is_capturing

            stop_capture()
            assert not _global.is_capturing
            assert _global.status == CaptureStatus.IDLE

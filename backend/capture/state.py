"""Thread-safe shared capture state.

This module is the single source of truth for whether a capture is
running, which interface is active, and the Aggregator instance.
All state transitions are guarded by a reentrant lock so that
start / stop / status can be called from any thread safely.
"""

from __future__ import annotations

import threading
import time
from enum import Enum, auto

from processing.aggregator import Aggregator


class CaptureStatus(Enum):
    IDLE = auto()
    STARTING = auto()
    RUNNING = auto()
    STOPPING = auto()
    ERROR = auto()


class CaptureState:
    """Global, thread-safe capture state singleton."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._status: CaptureStatus = CaptureStatus.IDLE
        self._interface: str | None = None
        self._started_at: float | None = None
        self._error: str | None = None
        self._worker_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self.aggregator = Aggregator()

    # ── Properties ────────────────────────────────────────────────

    @property
    def status(self) -> CaptureStatus:
        with self._lock:
            return self._status

    @property
    def interface(self) -> str | None:
        with self._lock:
            return self._interface

    @property
    def started_at(self) -> float | None:
        with self._lock:
            return self._started_at

    @property
    def error(self) -> str | None:
        with self._lock:
            return self._error

    @property
    def is_capturing(self) -> bool:
        with self._lock:
            return self._status in (CaptureStatus.STARTING, CaptureStatus.RUNNING)

    @property
    def stop_event(self) -> threading.Event:
        return self._stop_event

    # ── Transitions ───────────────────────────────────────────────

    def mark_starting(self, interface: str) -> None:
        with self._lock:
            self._status = CaptureStatus.STARTING
            self._interface = interface
            self._started_at = time.time()
            self._error = None
            self._stop_event.clear()
            self.aggregator.reset()

    def mark_running(self) -> None:
        with self._lock:
            if self._status == CaptureStatus.STARTING:
                self._status = CaptureStatus.RUNNING

    def mark_stopping(self) -> None:
        with self._lock:
            self._status = CaptureStatus.STOPPING
            self._stop_event.set()

    def mark_stopped(self) -> None:
        with self._lock:
            self._status = CaptureStatus.IDLE
            self._interface = None
            self._started_at = None
            self._worker_thread = None

    def mark_error(self, message: str) -> None:
        with self._lock:
            self._status = CaptureStatus.ERROR
            self._error = message
            self._stop_event.set()
            self._worker_thread = None

    # ── Worker management ─────────────────────────────────────────

    def set_worker(self, thread: threading.Thread) -> None:
        with self._lock:
            self._worker_thread = thread

    def has_worker(self) -> bool:
        with self._lock:
            return self._worker_thread is not None and self._worker_thread.is_alive()

    def join_worker(self, timeout: float = 5.0) -> None:
        with self._lock:
            thread = self._worker_thread
        if thread is not None:
            thread.join(timeout=timeout)


# Module-level singleton
capture_state = CaptureState()

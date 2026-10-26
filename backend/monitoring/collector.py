"""Background sampler for one selected local interface.

The first reading after start, restart, or an interface change is a baseline.
Rates begin on the next reading. Counter resets and long gaps are stored as
invalid intervals instead of invented throughput.
"""

from __future__ import annotations

import logging
import os
import platform
import threading
import time
from pathlib import Path

from analytics.threshold_alert import ThresholdAlertTracker
from analytics.thresholds import effective_thresholds
from core.config import settings
from monitoring.interfaces import default_route_interface, discover_interfaces, preferred_interface_name
from monitoring.probe import run_probe, validate_probe_target
from monitoring.rates import Counters, compute_rate
from monitoring.store import Store

logger = logging.getLogger(__name__)

SOURCE = "psutil.net_io_counters"


def default_db_path() -> Path:
    raw = os.getenv("DB_PATH") or settings.db_path
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[1] / "data" / "observations.sqlite"


def address_signature(interface_name: str) -> tuple[str, int] | None:
    """A hash of this interface's addresses. The addresses themselves are not stored or returned."""
    import hashlib

    import psutil

    try:
        entries = psutil.net_if_addrs().get(interface_name)
    except Exception:
        return None
    if not entries:
        return None
    values = sorted(f"{entry.family}:{entry.address}" for entry in entries)
    digest = hashlib.sha256("|".join(values).encode()).hexdigest()
    return digest, len(values)


def next_deadline(previous: float, now: float, interval: float) -> float:
    """Next sample time on a fixed monotonic grid. Work time does not add drift.

    If sampling overran one or more slots, skip them rather than sampling in a burst.
    """
    deadline = previous + interval
    if deadline <= now:
        missed = int((now - previous) // interval)
        deadline = previous + (missed + 1) * interval
    return deadline


def probes_disabled() -> bool:
    return os.getenv("DISABLE_PROBES", "false").lower() == "true" or settings.disable_probes


def read_counters(interface_name: str) -> Counters | None:
    """Read cumulative counters for one interface. Missing fields stay None."""
    import psutil

    try:
        table = psutil.net_io_counters(pernic=True)
    except Exception as exc:
        logger.warning("Counter read failed: %s", exc)
        return None
    row = table.get(interface_name) if table else None
    if row is None:
        return None

    def optional(value: object) -> int | None:
        if value is None:
            return None
        return int(value)

    return Counters(
        monotonic=time.monotonic(),
        wall=time.time(),
        rx_bytes=optional(getattr(row, "bytes_recv", None)),
        tx_bytes=optional(getattr(row, "bytes_sent", None)),
        rx_packets=optional(getattr(row, "packets_recv", None)),
        tx_packets=optional(getattr(row, "packets_sent", None)),
        rx_errors=optional(getattr(row, "errin", None)),
        tx_errors=optional(getattr(row, "errout", None)),
        rx_drops=optional(getattr(row, "dropin", None)),
        tx_drops=optional(getattr(row, "dropout", None)),
    )


class Collector:
    def __init__(self, store: Store | None = None, *, interval: float | None = None) -> None:
        self.store = store or Store(default_db_path())
        self.interval = interval if interval is not None else max(0.2, float(settings.sample_interval))
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._probe_thread: threading.Thread | None = None
        self._prev: Counters | None = None
        self._prev_name: str | None = None
        self._status = "stopped"
        self._error: str | None = None
        self._last_sample_at: float | None = None
        self._samples = 0
        self._probe: dict | None = None
        self._last_probe_monotonic = 0.0
        self._alert_signature: str | None = None
        self._started = False
        self._forecast_run: list[dict] | None = None
        self._forecast_run_interface: str | None = None
        self._alerts = ThresholdAlertTracker()
        self._alerts_interface: str | None = None
        self._alert_event_ids: dict[str, int] = {}
        self._address_signature: tuple[str, int] | None = None
        self._loop_count = 0

    @property
    def status(self) -> str:
        with self._lock:
            return self._status

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self.store.init()
            self.store.close_open_alert_events("collector_restarted")
            self._stop.clear()
            self._status = "running"
            self._error = None
            self._started = True
        self._ensure_interface()
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._loop, name="interface-counters", daemon=True)
            self._thread.start()
            if not probes_disabled():
                self._probe_thread = threading.Thread(target=self._probe_loop, name="latency-probe", daemon=True)
                self._probe_thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        probe = self._probe_thread
        if thread is not None:
            thread.join(timeout=5)
        if probe is not None:
            probe.join(timeout=2)
        with self._lock:
            self._status = "stopped"
            self._thread = None
            self._probe_thread = None
            self._started = False

    def set_interface(self, name: str, *, mode: str = "manual", reason: str = "user_selected") -> dict:
        records = discover_interfaces()
        match = next((record for record in records if record.name == name), None)
        if match is None:
            raise ValueError(f"Interface {name!r} is not present on this computer.")
        previous = self.selected_name()
        self._switch_to(name, previous, reason)
        self.store.update_config({"monitor_interface": name, "interface_mode": mode})
        return match.as_dict()

    def set_auto_interface(self) -> dict | None:
        """Follow the default-route interface from now on."""
        preferred = preferred_interface_name()
        if not preferred:
            raise ValueError("No up interface owns the default route right now.")
        return self.set_interface(preferred, mode="auto", reason="auto_selected")

    def _switch_to(self, name: str, previous: str | None, reason: str) -> None:
        """Re-baseline counters and isolate alert state. The first new reading is a baseline."""
        with self._lock:
            self._prev = None
            self._prev_name = None
            self._error = None
            self._address_signature = None
            self._forecast_run = None
            self._forecast_run_interface = None
            if self._started:
                self._status = "running"
        self._reset_alerts(reason)
        if previous != name or reason != "user_selected":
            self.store.insert_transition(at=time.time(), from_interface=previous, to_interface=name, reason=reason)

    def selected_name(self) -> str | None:
        config = self.store.get_config()
        name = config.get("monitor_interface")
        if isinstance(name, str) and name:
            return name
        return None

    def config(self) -> dict:
        config = self.store.get_config()
        if not config.get("probe_target"):
            config["probe_target"] = settings.probe_target
        return config

    def thresholds(self, name: str | None = None) -> dict:
        return effective_thresholds(self.store.get_config(), name if name is not None else self.selected_name())

    def alert_snapshot(self) -> dict:
        name = self.selected_name()
        with self._lock:
            live = self._alerts.snapshot() if self._alerts_interface == name else None
        history = self.store.alert_history_summary(name) if name else {}
        return {"interface": name, "live": live, "history": history}

    def _reset_alerts(self, reason: str) -> None:
        with self._lock:
            open_ids = dict(self._alert_event_ids)
            self._alert_event_ids = {}
            self._alerts.reset()
            self._alerts_interface = None
        for event_id in open_ids.values():
            self.store.update_alert_event(event_id, end_reason=reason)

    def _apply_alerts(self, name: str, row: dict) -> None:
        thresholds = self.thresholds(name)
        with self._lock:
            if self._alerts_interface != name:
                self._alerts.reset()
                self._alert_event_ids = {}
                self._alerts_interface = name
                restore = True
            else:
                restore = False
        if restore:
            summary = self.store.alert_history_summary(name)
            with self._lock:
                for side, item in summary.items():
                    self._alerts.restore(
                        side,
                        last_alert_at=item["last_alert_at"],
                        last_recovery_at=item["last_recovery_at"],
                        episodes=item["episodes"],
                    )
        with self._lock:
            transitions = self._alerts.update(
                sampled_at=float(row["sampled_at"]),
                valid=bool(row.get("valid")) and row.get("quality") == "ok",
                values={"receive": row.get("rx_mbps"), "transmit": row.get("tx_mbps")},
                thresholds={"receive": thresholds["receive"], "transmit": thresholds["transmit"]},
            )
            event_ids = dict(self._alert_event_ids)
        for change in transitions:
            event_id = event_ids.get(change.side)
            if change.kind == "started":
                event_ids[change.side] = self.store.insert_alert_event(
                    interface_name=name,
                    direction=change.side,
                    kind="threshold_exceeded",
                    started_at=change.at,
                    threshold_mbps=change.threshold_mbps,
                    trigger_mbps=change.value_mbps,
                )
            elif event_id is None:
                continue
            elif change.kind == "reopened":
                self.store.update_alert_event(event_id, reopened=True, peak_mbps=change.value_mbps)
            elif change.kind == "peak":
                self.store.update_alert_event(event_id, peak_mbps=change.value_mbps)
            elif change.kind == "recovered":
                self.store.update_alert_event(event_id, ended_at=change.at, end_reason="recovered")
            elif change.kind == "cleared":
                self.store.update_alert_event(event_id, end_reason="threshold_removed")
                event_ids.pop(change.side, None)
        with self._lock:
            self._alert_event_ids = event_ids

    def _check_network_change(self, name: str) -> None:
        """Re-baseline when the default route moves (auto mode) or this interface's addresses change."""
        config = self.store.get_config()
        if config.get("interface_mode") == "auto":
            preferred = default_route_interface()
            if preferred and preferred != name:
                self._switch_to(preferred, name, "default_route_changed")
                self.store.update_config({"monitor_interface": preferred})
                return
        signature = address_signature(name)
        with self._lock:
            previous = self._address_signature
            self._address_signature = signature
        if previous is not None and signature is not None and signature != previous:
            self._switch_to(name, name, "network_address_changed")

    def update_config(self, patch: dict) -> dict:
        if "probe_target" in patch and patch["probe_target"]:
            patch["probe_target"] = validate_probe_target(str(patch["probe_target"]))
        if patch.get("capacity_mbps") is None and "capacity_mbps" in patch:
            patch["capacity_source"] = "unknown"
        elif patch.get("capacity_mbps") is not None:
            patch["capacity_source"] = "user"
        return self.store.update_config(patch)

    def health(self) -> dict:
        with self._lock:
            return {
                "status": self._status,
                "error": self._error,
                "sample_interval_seconds": self.interval,
                "last_sample_at": self._last_sample_at,
                "samples_since_start": self._samples,
                "source": SOURCE,
                "platform": platform.system(),
                "probes_enabled": not probes_disabled(),
                "scope": "local_machine_interface",
                "scope_note": (
                    "Counters are read from one interface on this computer. "
                    "They do not describe the router or other devices on the LAN."
                ),
            }

    def latest_probe(self) -> dict | None:
        with self._lock:
            if self._probe is not None:
                return dict(self._probe)
        return self.store.latest_probe()

    def probe_now(self) -> dict:
        if probes_disabled():
            return {
                "status": "disabled",
                "method": "icmp_echo",
                "error": "Probes are disabled in this process.",
                "rtt_avg_ms": None,
                "loss_pct": None,
                "jitter_ms": None,
            }
        now = time.monotonic()
        with self._lock:
            if now - self._last_probe_monotonic < 10 and self._probe is not None:
                cached = dict(self._probe)
                cached["rate_limited"] = True
                return cached
            self._last_probe_monotonic = now
            target = self._probe_target()
            count = self._probe_count()
        result = run_probe(target, count)
        self._remember_probe(result)
        return result

    def alert_signature(self) -> str | None:
        with self._lock:
            return self._alert_signature

    def set_alert_signature(self, signature: str) -> None:
        with self._lock:
            self._alert_signature = signature

    def sample_once(self) -> dict | None:
        """Take one reading. Safe to call from tests and from the sampler thread."""
        name = self.selected_name()
        if not name:
            with self._lock:
                self._ensure_interface()
                name = self.selected_name()
        if not name:
            with self._lock:
                self._status = "needs_interface"
            return None

        counters = read_counters(name)
        if counters is None:
            with self._lock:
                self._status = "interface_unavailable"
                self._error = f"Interface {name!r} has no counter reading. No zero-traffic row was stored."
                self._prev = None
                self._prev_name = None
            return None

        with self._lock:
            previous = self._prev
            previous_name = self._prev_name
            changed = previous_name is not None and previous_name != name
        result = compute_rate(
            previous,
            counters,
            interface_changed=changed,
            max_elapsed_seconds=max(5 * self.interval, 15.0),
        )
        if result.quality == "too_soon":
            return None

        row = {
            "sampled_at": counters.wall,
            "interval_seconds": result.elapsed_seconds,
            "interface_name": name,
            "rx_bytes": counters.rx_bytes,
            "tx_bytes": counters.tx_bytes,
            "rx_packets": counters.rx_packets,
            "tx_packets": counters.tx_packets,
            "rx_errors": counters.rx_errors,
            "tx_errors": counters.tx_errors,
            "rx_drops": counters.rx_drops,
            "tx_drops": counters.tx_drops,
            "rx_mbps": result.rx_mbps,
            "tx_mbps": result.tx_mbps,
            "rx_pps": result.rx_pps,
            "tx_pps": result.tx_pps,
            "rx_error_per_s": result.rx_error_per_s,
            "tx_error_per_s": result.tx_error_per_s,
            "rx_drop_per_s": result.rx_drop_per_s,
            "tx_drop_per_s": result.tx_drop_per_s,
            "valid": result.valid,
            "quality": result.quality,
            "source": SOURCE,
            "platform": platform.system(),
            "note": result.note,
        }
        inserted = self.store.insert_observation(row)
        if inserted:
            try:
                self._apply_alerts(name, row)
            except Exception:
                logger.exception("Threshold alert update failed")
        if inserted and row["valid"] and row.get("rx_mbps") is not None and row.get("tx_mbps") is not None:
            try:
                from monitoring.forecast_log import issue_from_rows, score_pending

                model_rows = self._extend_forecast_run(name, row)
                issue_from_rows(
                    self.store,
                    name,
                    model_rows,
                    sample_interval=self.interval,
                    horizon_seconds=self._forecast_horizon(),
                    window=12,
                    alpha=0.3,
                )
                score_pending(
                    self.store,
                    name,
                    tolerance=max(self.interval * 0.75, 0.5),
                    now=time.time(),
                )
            except Exception:
                logger.exception("Forecast log update failed")
        with self._lock:
            self._prev = counters
            self._prev_name = name
            self._last_sample_at = counters.wall
            self._samples += 1
            self._status = "running"
            self._error = None
            sample_count = self._samples
        if inserted and sample_count % 30 == 0:
            self.store.prune(max(60.0, settings.retention_hours * 3600))
        row["inserted"] = inserted
        return row

    def _loop(self) -> None:
        deadline = time.monotonic()
        while not self._stop.is_set():
            try:
                self._loop_count += 1
                if self._loop_count % 10 == 0:
                    name = self.selected_name()
                    if name:
                        self._check_network_change(name)
                self.sample_once()
            except Exception as exc:
                logger.exception("Interface sample failed")
                with self._lock:
                    self._status = "error"
                    self._error = str(exc)
            now = time.monotonic()
            deadline = next_deadline(deadline, now, self.interval)
            self._stop.wait(max(0.0, deadline - now))

    def _probe_loop(self) -> None:
        if self._stop.wait(2.0):
            return
        while not self._stop.is_set():
            try:
                result = run_probe(self._probe_target(), self._probe_count())
                self._remember_probe(result)
            except Exception as exc:
                logger.warning("Probe failed: %s", exc)
                self._remember_probe(
                    {
                        "sampled_at": time.time(),
                        "target": self._probe_target(),
                        "method": "icmp_echo",
                        "status": "failed",
                        "error": str(exc),
                        "rtt_avg_ms": None,
                        "loss_pct": None,
                        "jitter_ms": None,
                        "note": "Probe failed before a measurement was parsed.",
                    }
                )
            self._stop.wait(max(10.0, float(settings.probe_interval)))

    def _remember_probe(self, result: dict) -> None:
        with self._lock:
            self._probe = dict(result)
            self._last_probe_monotonic = time.monotonic()
        try:
            self.store.insert_probe(result)
        except Exception:
            logger.exception("Could not store probe result")

    def _probe_target(self) -> str:
        configured = self.config().get("probe_target") or settings.probe_target
        return validate_probe_target(str(configured))

    def forecast_rows_for_model(self, name: str) -> list[dict]:
        """Latest contiguous valid run, loaded once and then extended in memory."""
        with self._lock:
            if self._forecast_run_interface == name and self._forecast_run is not None:
                return list(self._forecast_run)
        loaded = self.store.history(name, limit=20000, valid_only=True)
        from monitoring.forecast_log import rows_for_forecast

        run = rows_for_forecast(loaded, self.interval)
        with self._lock:
            if self._forecast_run_interface == name and self._forecast_run is not None:
                return list(self._forecast_run)
            self._forecast_run = run
            self._forecast_run_interface = name
            return list(run)

    def _extend_forecast_run(self, name: str, row: dict) -> list[dict]:
        with self._lock:
            cached = self._forecast_run if self._forecast_run_interface == name else None
        if cached is None:
            return self.forecast_rows_for_model(name)
        if cached[-1].get("sampled_at") == row.get("sampled_at"):
            return list(cached)
        from monitoring.forecast_log import rows_for_forecast

        run = rows_for_forecast([*cached, row], self.interval)
        with self._lock:
            self._forecast_run = run
            self._forecast_run_interface = name
            return list(run)

    def _forecast_horizon(self) -> float:
        configured = self.config().get("forecast_horizon_seconds")
        try:
            if configured is not None and float(configured) > 0:
                return float(configured)
        except (TypeError, ValueError):
            pass
        return max(1.0, float(settings.forecast_horizon_seconds))

    def _probe_count(self) -> int:
        try:
            return max(1, min(int(settings.probe_count), 5))
        except (TypeError, ValueError):
            return 3

    def _ensure_interface(self) -> None:
        """Caller must hold the lock or accept a benign race during startup."""
        self.store.init()
        config = self.store.get_config()
        current = config.get("monitor_interface")
        records = discover_interfaces()
        names = {record.name for record in records}
        if isinstance(current, str) and current in names:
            return
        preferred = preferred_interface_name(records)
        if preferred:
            self.store.update_config({"monitor_interface": preferred})
            self._prev = None
            self._prev_name = None


monitoring_collector = Collector()

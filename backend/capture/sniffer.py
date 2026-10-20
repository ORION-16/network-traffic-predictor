"""Scapy-based packet capture worker.

Runs in a daemon thread so it never blocks the main FastAPI event loop.
The worker reads from capture_state.stop_event to know when to quit.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from typing import TYPE_CHECKING

from capture.state import capture_state
from core.config import settings
from processing.parser import parse_packet
from schemas import PacketMeta

if TYPE_CHECKING:
    from scapy.packet import Packet

logger = logging.getLogger(__name__)


def _sniff_callback(pkt: "Packet") -> None:
    """Per-packet callback executed inside the Scapy sniffer thread."""
    meta = parse_packet(pkt)
    if meta is not None:
        capture_state.aggregator.add_packet(meta)


def _should_stop(_pkt: "Packet") -> bool:
    """Scapy stop_filter — returns True when the stop event is set."""
    return capture_state.stop_event.is_set()


def _demo_worker(interface: str) -> None:
    """Synthetic packet generator for UI development when DEMO_MODE=true.

    Disabled by default. Never activated as a silent fallback.
    """
    logger.warning(
        "[DEMO MODE ACTIVE] Generating synthetic network packets for UI development on '%s'. "
        "Real packet capture is bypassed.",
        interface,
    )
    capture_state.mark_running()

    protocols = ["TCP", "UDP", "ICMP", "ARP"]
    weights = [0.65, 0.25, 0.07, 0.03]
    src_ips = ["192.168.1.10", "192.168.1.25", "10.0.0.12", "172.16.0.5"]
    dst_ips = ["142.250.190.46", "1.1.1.1", "8.8.8.8", "151.101.65.140", "104.244.42.1"]

    while not capture_state.stop_event.is_set():
        proto = random.choices(protocols, weights=weights)[0]
        src = random.choice(src_ips)
        dst = random.choice(dst_ips)
        length = random.randint(54, 1514)

        if proto == "TCP":
            info = f"{random.randint(49152, 65535)}→{random.choice([80, 443, 8080])} [PA]"
        elif proto == "UDP":
            info = f"{random.randint(49152, 65535)}→{random.choice([53, 123, 443])}"
        elif proto == "ICMP":
            info = "Echo (ping) request"
        else:
            info = "who-has 192.168.1.1 tell 192.168.1.25"

        meta = PacketMeta(
            timestamp=time.time(),
            src_ip=src,
            dst_ip=dst,
            protocol=proto,
            length=length,
            info=f"[DEMO] {info}",
        )
        capture_state.aggregator.add_packet(meta)
        time.sleep(random.uniform(0.02, 0.15))

    capture_state.mark_stopped()
    logger.info("Demo capture worker for %s exited", interface)


def _capture_worker(interface: str) -> None:
    """Entry point for real Scapy packet capture worker thread."""
    if settings.demo_mode:
        _demo_worker(interface)
        return

    try:
        from scapy.all import sniff as scapy_sniff

        capture_state.mark_running()
        logger.info("Live Scapy capture started on %s", interface)

        scapy_sniff(
            iface=interface,
            prn=_sniff_callback,
            stop_filter=_should_stop,
            store=False,  # never keep packets in Scapy's unbounded memory
            count=0,
        )
    except PermissionError:
        msg = (
            f"Permission denied capturing on '{interface}'. "
            "Raw socket capture requires elevated privileges. "
            "On macOS: sudo python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000. "
            "On Linux: sudo setcap cap_net_raw,cap_net_admin+eip $(which python3)."
        )
        logger.error(msg)
        capture_state.mark_error(msg)
        return
    except OSError as exc:
        msg = f"OS error capturing on '{interface}': {exc}"
        logger.error(msg)
        capture_state.mark_error(msg)
        return
    except Exception as exc:
        msg = f"Unexpected capture error on '{interface}': {exc}"
        logger.exception(msg)
        capture_state.mark_error(msg)
        return
    finally:
        if capture_state.status != capture_state.status.ERROR:
            capture_state.mark_stopped()
        logger.info("Capture worker for %s exited", interface)


def start_capture(interface: str) -> None:
    """Start packet capture on *interface* in a background thread.

    Raises RuntimeError if a capture is already running.
    """
    if capture_state.is_capturing or capture_state.has_worker():
        raise RuntimeError("A capture is already running. Stop it first.")

    capture_state.mark_starting(interface)
    thread = threading.Thread(
        target=_capture_worker,
        args=(interface,),
        name=f"sniffer-{interface}",
        daemon=True,
    )
    capture_state.set_worker(thread)
    thread.start()


def stop_capture() -> None:
    """Signal the sniffer thread to stop and wait for it to exit."""
    if not capture_state.is_capturing and not capture_state.has_worker():
        return  # nothing to stop
    capture_state.mark_stopping()
    capture_state.join_worker(timeout=5.0)
    capture_state.mark_stopped()

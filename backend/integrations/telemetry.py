"""Contract for traffic sources beyond this computer, such as router telemetry.

Nothing here is implemented or enabled. The dashboard measures one interface
on this computer through OS counters. A whole-network view needs a device that
sees all traffic, for example a router exposing SNMP ``ifHCInOctets`` or a
vendor API. A source that implements this protocol must:

* return cumulative byte counters with its own monotonic timestamp, so rates
  use the same delta formula as the local collector;
* return None for a value it cannot read, never zero;
* declare its scope, so its series is never merged with this computer's series.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TelemetryReading:
    monotonic: float
    wall: float
    rx_bytes: int | None
    tx_bytes: int | None


class TelemetrySource(Protocol):
    name: str
    scope: str  # for example "router_wan" or "lan_switch_port"

    def read(self) -> TelemetryReading | None:
        """One cumulative reading, or None when the device did not answer."""
        ...

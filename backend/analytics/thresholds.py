"""Resolve the saved download and upload thresholds for one interface profile.

A threshold is a value the user entered. It is never derived from adapter link
speed. Resolution order for each direction:

1. A per-profile value saved for this interface.
2. A global download or upload threshold.
3. The older single ``capacity_mbps`` setting, applied by its direction mode.

A missing value stays None, which means no threshold alert for that direction.
"""

from __future__ import annotations

import math

MAX_THRESHOLD_MBPS = 1_000_000.0
DIRECTION_KEYS = {"receive": "download_threshold_mbps", "transmit": "upload_threshold_mbps"}


def validate_threshold(value: object) -> float | None:
    """Return a positive finite Mbps value, None to clear, or raise ValueError."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("A threshold must be a number of Mbps.")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("A threshold must be a number of Mbps.") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError("A threshold must be greater than 0 Mbps.")
    if number > MAX_THRESHOLD_MBPS:
        raise ValueError("A threshold must be at most 1,000,000 Mbps.")
    return number


def _positive(value: object) -> float | None:
    try:
        return validate_threshold(value)
    except ValueError:
        return None


def _legacy(config: dict, side: str) -> float | None:
    if config.get("capacity_source") != "user":
        return None
    capacity = _positive(config.get("capacity_mbps"))
    if capacity is None:
        return None
    direction = config.get("direction") or "per_direction"
    if direction == "receive_only" and side != "receive":
        return None
    if direction == "transmit_only" and side != "transmit":
        return None
    return capacity


def effective_thresholds(config: dict, interface_name: str | None) -> dict:
    """Thresholds the chart, the API, and the alert all use."""
    profiles = config.get("profiles") if isinstance(config.get("profiles"), dict) else {}
    profile = profiles.get(interface_name) if interface_name else None
    profile = profile if isinstance(profile, dict) else {}
    result: dict = {"profile": interface_name, "receive": None, "transmit": None, "sources": {}}
    for side, key in DIRECTION_KEYS.items():
        value = _positive(profile.get(key))
        source = "profile"
        if value is None:
            value = _positive(config.get(key))
            source = "global"
        if value is None:
            value = _legacy(config, side)
            source = "capacity"
        if value is None:
            source = "unset"
        result[side] = value
        result["sources"][side] = source
    result["configured"] = result["receive"] is not None or result["transmit"] is not None
    result["note"] = (
        "Thresholds are values you entered for testing. They are not measured internet capacity "
        "and are not taken from adapter link speed."
    )
    return result


def compare(value: float | None, threshold: float | None) -> str:
    """below, equal, above, no_threshold, or missing. Equal counts as exceeded."""
    if threshold is None:
        return "no_threshold"
    if value is None:
        return "missing"
    if value > threshold:
        return "above"
    if value == threshold:
        return "equal"
    return "below"

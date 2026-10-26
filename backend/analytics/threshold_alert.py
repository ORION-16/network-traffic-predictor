"""Server-side threshold alert with hysteresis and cooldown, per direction.

Rules, applied to each stored sample in order:

* Enter when a valid rate is at or above the threshold.
* While active, a valid rate below ``CLEAR_RATIO * threshold`` counts toward
  recovery. ``CLEAR_SAMPLES`` such samples in a row end the alert. A rate in
  between resets the count, so traffic hovering at the line does not flap.
* A sample that is missing or invalid (gap, baseline, reset) neither enters nor
  recovers. The alert holds its last state and the payload says the data is
  not current.
* Re-entering within ``COOLDOWN_SECONDS`` of a recovery reopens the same
  episode. It does not count as a new alert and does not notify again.
* Removing a threshold ends the alert without recording a recovery.
"""

from __future__ import annotations

from dataclasses import dataclass, field

CLEAR_RATIO = 0.9
CLEAR_SAMPLES = 3
COOLDOWN_SECONDS = 30.0
SIDES = ("receive", "transmit")
LABELS = {"receive": "download", "transmit": "upload"}


@dataclass
class DirectionState:
    active: bool = False
    threshold_mbps: float | None = None
    since: float | None = None
    last_alert_at: float | None = None
    last_recovery_at: float | None = None
    peak_mbps: float | None = None
    latest_mbps: float | None = None
    below_count: int = 0
    episodes: int = 0
    event_id: int | None = None

    def snapshot(self, side: str) -> dict:
        return {
            "direction": side,
            "label": LABELS[side],
            "active": self.active,
            "threshold_mbps": self.threshold_mbps,
            "clear_below_mbps": None if self.threshold_mbps is None else self.threshold_mbps * CLEAR_RATIO,
            "since": self.since,
            "last_alert_at": self.last_alert_at,
            "last_recovery_at": self.last_recovery_at,
            "peak_mbps": self.peak_mbps,
            "latest_mbps": self.latest_mbps,
            "recovery_progress": f"{self.below_count}/{CLEAR_SAMPLES}" if self.active else None,
            "episodes": self.episodes,
        }


@dataclass
class Transition:
    side: str
    kind: str  # "started", "reopened", "recovered", "cleared", "peak"
    at: float
    threshold_mbps: float | None
    value_mbps: float | None
    state: DirectionState = field(repr=False, default_factory=DirectionState)


class ThresholdAlertTracker:
    def __init__(self) -> None:
        self.states = {side: DirectionState() for side in SIDES}

    def reset(self) -> None:
        """Forget live state, for example after switching interface profile."""
        self.states = {side: DirectionState() for side in SIDES}

    def restore(self, side: str, *, last_alert_at: float | None, last_recovery_at: float | None, episodes: int) -> None:
        state = self.states[side]
        state.last_alert_at = last_alert_at
        state.last_recovery_at = last_recovery_at
        state.episodes = episodes

    def update(self, *, sampled_at: float, valid: bool, values: dict, thresholds: dict) -> list[Transition]:
        transitions: list[Transition] = []
        for side in SIDES:
            state = self.states[side]
            threshold = thresholds.get(side)
            value = values.get(side) if valid else None
            state.latest_mbps = value
            if threshold is None:
                if state.active:
                    transitions.append(Transition(side, "cleared", sampled_at, state.threshold_mbps, value, state))
                state.active = False
                state.threshold_mbps = None
                state.below_count = 0
                state.since = None
                continue
            state.threshold_mbps = float(threshold)
            if value is None:
                continue
            if not state.active:
                if value >= threshold:
                    state.active = True
                    state.below_count = 0
                    reopened = (
                        state.last_recovery_at is not None
                        and sampled_at - state.last_recovery_at < COOLDOWN_SECONDS
                        and state.since is not None
                    )
                    if reopened:
                        state.peak_mbps = max(state.peak_mbps or value, value)
                        state.last_recovery_at = None
                        transitions.append(Transition(side, "reopened", sampled_at, threshold, value, state))
                    else:
                        state.peak_mbps = value
                        state.since = sampled_at
                        state.last_alert_at = sampled_at
                        state.episodes += 1
                        transitions.append(Transition(side, "started", sampled_at, threshold, value, state))
                continue
            if state.peak_mbps is None or value > state.peak_mbps:
                state.peak_mbps = value
                transitions.append(Transition(side, "peak", sampled_at, threshold, value, state))
            if value < threshold * CLEAR_RATIO:
                state.below_count += 1
                if state.below_count >= CLEAR_SAMPLES:
                    state.active = False
                    state.below_count = 0
                    state.last_recovery_at = sampled_at
                    transitions.append(Transition(side, "recovered", sampled_at, threshold, value, state))
            else:
                state.below_count = 0
        return transitions

    def snapshot(self) -> dict:
        return {side: self.states[side].snapshot(side) for side in SIDES}


def explain(side_snapshot: dict) -> str:
    label = side_snapshot["label"].capitalize()
    threshold = side_snapshot["threshold_mbps"]
    latest = side_snapshot["latest_mbps"]
    latest_text = "no current rate" if latest is None else f"{latest:.2f} Mbps"
    return (
        f"{label} reached the {threshold:g} Mbps threshold you saved. The latest reading is {latest_text}. "
        f"It recovers after {CLEAR_SAMPLES} valid readings below {threshold * CLEAR_RATIO:.2f} Mbps."
    )

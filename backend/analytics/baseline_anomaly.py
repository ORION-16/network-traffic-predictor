"""Optional comparison of the latest rate with the recent median.

This flags traffic that is already high relative to its own recent baseline.
It does not identify a cause, and it is not a statement that an attack occurred.
The baseline is frozen when an episode starts so a long burst stays one episode
until the rate falls back, instead of the median chasing the burst.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from analytics.threshold_alert import LABELS, SIDES, RecoveryRules, Transition

MIN_HISTORY = 12
HISTORY = 60


@dataclass
class BaselineConfig:
    enabled: bool = False
    multiplier: float = 3.0
    floor_mbps: float = 5.0
    margin_mbps: float = 5.0


def unusual(value: float, baseline: float, config: BaselineConfig) -> bool:
    if value < config.floor_mbps:
        return False
    if value - baseline < config.margin_mbps:
        return False
    return value >= config.multiplier * baseline


@dataclass
class _Side:
    history: deque = field(default_factory=lambda: deque(maxlen=HISTORY))
    active: bool = False
    since: float | None = None
    baseline_mbps: float | None = None
    peak_mbps: float | None = None
    latest_mbps: float | None = None
    below_count: int = 0
    last_alert_at: float | None = None
    last_recovery_at: float | None = None
    episodes: int = 0

    def snapshot(self, side: str, rules: RecoveryRules) -> dict:
        return {
            "direction": side,
            "label": LABELS[side],
            "active": self.active,
            "baseline_mbps": self.baseline_mbps,
            "latest_mbps": self.latest_mbps,
            "peak_mbps": self.peak_mbps,
            "since": self.since,
            "history_points": len(self.history),
            "recovery_progress": f"{self.below_count}/{rules.clear_samples}" if self.active else None,
            "episodes": self.episodes,
            "claim": "unusual_traffic_not_a_confirmed_attack",
        }


class BaselineAnomalyTracker:
    def __init__(self) -> None:
        self.sides = {side: _Side() for side in SIDES}

    def reset(self) -> None:
        self.sides = {side: _Side() for side in SIDES}

    def restore(self, side: str, *, episodes: int, last_alert_at: float | None, last_recovery_at: float | None) -> None:
        state = self.sides[side]
        state.episodes = episodes
        state.last_alert_at = last_alert_at
        state.last_recovery_at = last_recovery_at

    def resume_open(self, side: str, *, since: float, baseline_mbps: float | None, peak_mbps: float | None) -> None:
        state = self.sides[side]
        state.active = True
        state.since = since
        state.last_alert_at = since
        state.baseline_mbps = baseline_mbps
        state.peak_mbps = peak_mbps
        state.below_count = 0
        state.last_recovery_at = None

    def update(
        self,
        *,
        sampled_at: float,
        valid: bool,
        values: dict,
        config: BaselineConfig,
        rules: RecoveryRules,
    ) -> list[Transition]:
        changes: list[Transition] = []
        for side in SIDES:
            state = self.sides[side]
            value = values.get(side) if valid else None
            state.latest_mbps = value
            if not config.enabled:
                if state.active:
                    changes.append(Transition(side, "cleared", sampled_at, state.baseline_mbps, value, state))
                    state.active = False
                    state.below_count = 0
                continue
            if value is None:
                continue
            if not state.active:
                baseline = _median(state.history) if len(state.history) >= MIN_HISTORY else None
                if baseline is not None and unusual(value, baseline, config):
                    state.active = True
                    state.below_count = 0
                    state.baseline_mbps = baseline
                    reopened = (
                        state.last_recovery_at is not None
                        and sampled_at - state.last_recovery_at < rules.cooldown_seconds
                        and state.since is not None
                    )
                    if reopened:
                        state.peak_mbps = max(state.peak_mbps or value, value)
                        state.last_recovery_at = None
                        changes.append(Transition(side, "reopened", sampled_at, baseline, value, state))
                    else:
                        state.peak_mbps = value
                        state.since = sampled_at
                        state.last_alert_at = sampled_at
                        state.episodes += 1
                        changes.append(Transition(side, "started", sampled_at, baseline, value, state))
                else:
                    state.history.append(value)
                continue
            if state.peak_mbps is None or value > state.peak_mbps:
                state.peak_mbps = value
                changes.append(Transition(side, "peak", sampled_at, state.baseline_mbps, value, state))
            frozen = state.baseline_mbps if state.baseline_mbps is not None else 0.0
            if unusual(value, frozen, config):
                state.below_count = 0
            else:
                state.history.append(value)
                state.below_count += 1
                if state.below_count >= rules.clear_samples:
                    state.active = False
                    state.below_count = 0
                    state.last_recovery_at = sampled_at
                    changes.append(Transition(side, "recovered", sampled_at, state.baseline_mbps, value, state))
        return changes

    def snapshot(self, rules: RecoveryRules) -> dict:
        return {side: self.sides[side].snapshot(side, rules) for side in SIDES}


def _median(values: deque) -> float:
    ordered = sorted(values)
    count = len(ordered)
    mid = count // 2
    if count % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2

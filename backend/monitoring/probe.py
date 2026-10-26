"""Small ICMP echo probe.

The probe sends a fixed, tiny number of echo requests to a validated target.
It is not a load test. Loss from a handful of ICMP replies is a weak signal:
ICMP may be deprioritized, and the result is not TCP loss or a full-path
measurement. Jitter is the mean absolute difference between successive
numeric RTT samples. Samples reported only as below 1 ms are not converted
into a fabricated millisecond value.
"""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
import time

_HOSTNAME = re.compile(
    r"^(?=.{1,253}$)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)(?:\.(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?))*$"
)
_IPV4 = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")
_TIME = re.compile(r"time[=<]\s*([0-9]+(?:\.[0-9]+)?)|time<\s*1", flags=re.IGNORECASE)


def validate_probe_target(target: str) -> str:
    candidate = (target or "").strip()
    if not candidate or any(char.isspace() for char in candidate):
        raise ValueError("Probe target is empty or contains whitespace.")
    if ":" in candidate:
        raise ValueError("IPv6 probe targets are not supported by this probe.")
    if _IPV4.match(candidate):
        parts = [int(part) for part in candidate.split(".")]
        if any(part > 255 for part in parts):
            raise ValueError("Probe target is not a valid IPv4 address.")
        return candidate
    if _HOSTNAME.match(candidate):
        return candidate
    raise ValueError("Probe target must be a hostname or IPv4 address.")


def parse_ping_output(output: str, *, sent_expected: int) -> dict:
    """Parse Windows or Unix ping text. Unrecognized output is a failure, not zero loss."""
    text = output or ""
    samples: list[float | None] = []
    below_resolution = 0
    for match in re.finditer(r"time[=<]\s*([0-9]+(?:\.[0-9]+)?)|time<\s*1", text, flags=re.IGNORECASE):
        token = match.group(0).lower().replace(" ", "")
        if token.startswith("time<1"):
            samples.append(None)
            below_resolution += 1
        elif match.group(1) is not None:
            samples.append(float(match.group(1)))

    sent = _first_int(text, r"(?:Sent|transmitted)\s*=\s*(\d+)|(\d+)\s+packets transmitted")
    received = _first_int(text, r"(?:Received|received)\s*=\s*(\d+)|,\s*(\d+)\s+received")
    lost = _first_int(text, r"Lost\s*=\s*(\d+)")
    if sent is None:
        sent = sent_expected if samples or received is not None else None
    if received is None and sent is not None and lost is not None:
        received = max(0, sent - lost)
    if sent is None or received is None:
        return {
            "status": "parse_failed",
            "sent": sent,
            "received": received,
            "loss_pct": None,
            "rtt_avg_ms": None,
            "rtt_min_ms": None,
            "rtt_max_ms": None,
            "jitter_ms": None,
            "sample_count": len(samples),
            "rtt_status": "unavailable",
            "error": "Ping output was not recognized. Loss and latency were not invented.",
        }

    loss_pct = ((sent - received) / sent * 100) if sent > 0 else None
    numeric = [sample for sample in samples if sample is not None]
    rtt_status = "measured" if numeric else ("below_1ms" if below_resolution else "unavailable")
    jitter = _jitter(numeric) if len(numeric) >= 2 else None
    note = (
        "ICMP echo to a single target. Loss is the missing share of this small probe only. "
        "It is not TCP loss and it is not a measurement of every hop. "
        "Jitter is the mean absolute successive difference of numeric RTT samples."
    )
    if below_resolution:
        note += " At least one reply was reported as below 1 ms and was excluded from the average."
    status = "ok" if received > 0 or loss_pct is not None else "failed"
    if received == 0:
        status = "unreachable"
        rtt_status = "unavailable"
    return {
        "status": status,
        "sent": sent,
        "received": received,
        "loss_pct": loss_pct,
        "rtt_avg_ms": (sum(numeric) / len(numeric)) if numeric else None,
        "rtt_min_ms": min(numeric) if numeric else None,
        "rtt_max_ms": max(numeric) if numeric else None,
        "jitter_ms": jitter,
        "sample_count": len(numeric),
        "rtt_status": rtt_status,
        "error": None if status in {"ok", "unreachable"} else "Probe did not produce a usable result.",
        "note": note,
    }


def _jitter(samples: list[float]) -> float:
    diffs = [abs(samples[index] - samples[index - 1]) for index in range(1, len(samples))]
    return sum(diffs) / len(diffs)


def _first_int(text: str, pattern: str) -> int | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    for group in match.groups():
        if group is not None:
            return int(group)
    return None


def run_probe(target: str, count: int = 3) -> dict:
    """Run one bounded ICMP probe. The target is an argument, never a shell string."""
    safe_target = validate_probe_target(target)
    count = max(1, min(int(count), 5))
    ping = shutil.which("ping")
    sampled_at = time.time()
    base = {
        "sampled_at": sampled_at,
        "target": safe_target,
        "method": "icmp_echo",
        "sent": None,
        "received": None,
        "loss_pct": None,
        "rtt_avg_ms": None,
        "rtt_min_ms": None,
        "rtt_max_ms": None,
        "jitter_ms": None,
        "sample_count": 0,
        "rtt_status": "unavailable",
        "note": "ICMP echo probe.",
    }
    if ping is None:
        return {**base, "status": "unsupported", "error": "The ping executable is not available."}

    system = platform.system()
    if system == "Windows":
        command = [ping, "-n", str(count), "-w", "1000", safe_target]
    elif system == "Darwin":
        command = [ping, "-c", str(count), "-W", "1000", safe_target]
    else:
        command = [ping, "-c", str(count), "-W", "1", safe_target]

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=count * 2 + 4,
            shell=False,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {**base, "status": "failed", "error": "The probe timed out."}
    except OSError as exc:
        return {**base, "status": "failed", "error": f"The probe could not start: {exc}"}

    parsed = parse_ping_output(f"{completed.stdout}\n{completed.stderr}", sent_expected=count)
    parsed.update({"sampled_at": sampled_at, "target": safe_target, "method": "icmp_echo"})
    if completed.returncode != 0 and parsed.get("status") == "parse_failed":
        parsed["status"] = "failed"
        parsed["error"] = parsed.get("error") or "The probe failed and its output could not be parsed."
    return parsed

"""Print the diagnostics report for the stored observations. Read-only.

Run from backend/:  python -m scripts.run_diagnostics
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from monitoring.collector import Collector  # noqa: E402
from monitoring.diagnostics import build_diagnostics  # noqa: E402


def _short(value):
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, dict):
        return {key: _short(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_short(item) for item in value]
    return value


if __name__ == "__main__":
    collector = Collector()
    collector.store.init()
    report = build_diagnostics(collector, force=True)
    report.pop("ledger", None)
    print(json.dumps(_short(report), indent=1))

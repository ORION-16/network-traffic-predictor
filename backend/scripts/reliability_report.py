"""Print a reliability report from the local database and a temporary write probe."""

from __future__ import annotations

import json

from monitoring.collector import default_db_path
from monitoring.reliability import build_reliability_report
from monitoring.store import Store


def main() -> None:
    store = Store(default_db_path())
    store.init()
    config = store.get_config()
    report = build_reliability_report(store, config.get("monitor_interface"))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
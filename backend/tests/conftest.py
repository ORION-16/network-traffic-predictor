"""Keep pytest on a temporary database and away from live ICMP probes."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_test_dir = Path(tempfile.mkdtemp(prefix="ntp-tests-"))
os.environ["DB_PATH"] = str(_test_dir / "observations.sqlite")
os.environ["DISABLE_PROBES"] = "true"
os.environ["DEMO_MODE"] = "false"

"""Application configuration loaded from environment variables."""

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    """Immutable application settings."""

    host: str = field(default_factory=lambda: os.getenv("APP_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.getenv("APP_PORT", "8000")))
    cors_origins: list[str] = field(
        default_factory=lambda: os.getenv(
            "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
        ).split(",")
    )
    # Maximum number of packets kept in memory
    max_packets: int = field(
        default_factory=lambda: int(os.getenv("MAX_PACKETS", "10000"))
    )
    # WebSocket push interval in seconds
    ws_interval: float = field(
        default_factory=lambda: float(os.getenv("WS_INTERVAL", "1.0"))
    )
    # Demo mode: when True, generates synthetic traffic instead of real capture.
    # Disabled by default. Only enable for UI development without root privileges.
    # Interface-counter monitoring never uses this path.
    demo_mode: bool = field(
        default_factory=lambda: os.getenv("DEMO_MODE", "false").lower() == "true"
    )
    # Interface-counter sampling. Empty DB_PATH uses backend/data/observations.sqlite.
    sample_interval: float = field(
        default_factory=lambda: float(os.getenv("SAMPLE_INTERVAL", "1.0"))
    )
    forecast_horizon_seconds: float = field(
        default_factory=lambda: float(os.getenv("FORECAST_HORIZON_SECONDS", "300"))
    )
    retention_hours: float = field(
        default_factory=lambda: float(os.getenv("RETENTION_HOURS", "24"))
    )
    db_path: str = field(default_factory=lambda: os.getenv("DB_PATH", ""))
    disable_probes: bool = field(
        default_factory=lambda: os.getenv("DISABLE_PROBES", "false").lower() == "true"
    )
    probe_target: str = field(
        default_factory=lambda: os.getenv("LATENCY_PROBE_TARGET", "1.1.1.1")
    )
    probe_interval: float = field(
        default_factory=lambda: float(os.getenv("LATENCY_PROBE_INTERVAL", "30"))
    )
    probe_count: int = field(
        default_factory=lambda: int(os.getenv("LATENCY_PROBE_COUNT", "3"))
    )


settings = Settings()

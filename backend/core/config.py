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
            "CORS_ORIGINS", "http://localhost:5173"
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
    demo_mode: bool = field(
        default_factory=lambda: os.getenv("DEMO_MODE", "false").lower() == "true"
    )


settings = Settings()

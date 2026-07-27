"""
Ground Station Configuration
All settings are read from environment variables (with defaults).
Copy .env.example → .env and adjust before running.
"""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # ─── Network ──────────────────────────────────────────────────
    HOST: str = Field(default="0.0.0.0", description="Bind host for the web server")
    WEB_PORT: int = Field(default=8000, description="HTTP / WebSocket port")
    UDP_PORT: int = Field(default=5000, description="UDP port for incoming video stream")

    # ─── Video ────────────────────────────────────────────────────
    VIDEO_FPS_LIMIT: int = Field(
        default=30,
        description="Maximum frames per second pushed over WebSocket",
    )
    VIDEO_JPEG_QUALITY: int = Field(
        default=80,
        description="Re-encode JPEG quality (1–100) for WebSocket transport",
    )
    VIDEO_MAX_CLIENTS: int = Field(
        default=10,
        description="Maximum simultaneous WebSocket video clients",
    )

    # ─── Tailscale ────────────────────────────────────────────────
    TAILSCALE_ENABLED: bool = Field(
        default=False,
        description="Enable Tailscale-specific network logging / CORS behaviour",
    )

    # ─── Logging ──────────────────────────────────────────────────
    LOG_LEVEL: str = Field(
        default="INFO",
        description="Python logging level: DEBUG | INFO | WARNING | ERROR | CRITICAL",
    )

    # ─── Telemetry ────────────────────────────────────────────────
    TELEMETRY_HZ: float = Field(
        default=5.0,
        description="Simulated telemetry publish rate in Hz",
    )
    MAVLINK_HOSTS: str = Field(
        default="100.121.12.16,100.109.178.125",
        description="Comma-separated list of MAVLink TCP host IPs",
    )
    MAVLINK_DEFAULT_PORT: int = Field(default=5761, description="Default MAVLink TCP port")

    @property
    def mavlink_host_list(self) -> list[str]:
        return [c.strip() for c in self.MAVLINK_HOSTS.split(",") if c.strip()]


    # ─── Snapshots ────────────────────────────────────────────────
    SNAPSHOT_DIR: str = Field(default="snapshots", description="Directory for saved snapshots")



    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
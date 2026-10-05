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

    # ─── APF Swarm ────────────────────────────────────────────────
    APF_D_SAFE: float = Field(default=10.0, description="Minimum safe separation (meters)")
    APF_D_INFLUENCE: float = Field(default=30.0, description="Distance at which avoidance begins (meters)")
    APF_K_ATT: float = Field(default=1.0, description="Attractive force gain")
    APF_K_REP: float = Field(default=100.0, description="Repulsive force gain")
    APF_MAX_OFFSET: float = Field(default=20.0, description="Maximum avoidance offset (meters)")
    APF_TICK_RATE_HZ: float = Field(default=5.0, description="APF computation loop rate (Hz)")

    # ─── Image Receiver Listener Config (per-UAV geotagged stitching ingestion)  ────────────────────────────────
    IMAGE_RECEIVER_ENABLED:bool = Field(
        default=True,
        description="Enable the image receiver listener for stitching ingestion"
    )
    IMAGE_RECEIVER_SLOTS:str = Field(
        default="1,2",
        description="Comma-separated list of image receiver slots"
    )
    IMAGE_RECEIVER_PORT: str = Field(
        default="6001,6002",
        description="UDP ports for per-UAV geotagged image ingestion (comma-separated, one per slot)"
    )
    IMAGE_RECEIVER_AUTO_STITCH_THRESHOLD: int = Field(
        default=5,
        description="Number of images to trigger auto-stitching (per slot)"
        )
    IMAGE_RECEIVER_AUTO_STITCH_ENABLED: bool = Field(
        default=True,
        description="Enable auto-stitching when threshold is reached (per slot)"
    )
    IMAGE_RECEIVER_FOLDER_MONITORING_ENABLED: bool = Field(
        default=True,
        description="Enable folder monitoring for new images (per slot)"
    )
    IMAGE_RECEIVER_OUTPUT_NAME: str = Field(
        default="finalResult.png",
        description="Name of the final output image file"
    )
    @property
    def image_receiver_uav_config(self) -> list[dict]:
        """
        One entry per configured UAV slot: port to bind + its stitching
        session identity + default session behavior, all declaratively
        pre-provisioned at startup (see app/main.py wiring, Step 4)
        """
        slots = [int(s.strip()) for s in self.IMAGE_RECEIVER_SLOTS.split(",") if s.strip()]
        ports = [int(p.strip()) for p in self.IMAGE_RECEIVER_PORT.split(",") if p.strip()]
        return [
            {
                "slot": slot,
                "port": port,
                "session_id": f"uav_{slot}",
                "auto_stitch_threshold": self.IMAGE_RECEIVER_AUTO_STITCH_THRESHOLD,
                "auto_stitch_enabled": self.IMAGE_RECEIVER_AUTO_STITCH_ENABLED,
                "folder_monitoring_enabled": self.IMAGE_RECEIVER_FOLDER_MONITORING_ENABLED,
                "output_name": self.IMAGE_RECEIVER_OUTPUT_NAME,
            }
            for slot, port in zip(slots, ports)
        ]


    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
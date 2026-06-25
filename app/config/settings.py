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

    # ─── Snapshots ────────────────────────────────────────────────
    SNAPSHOT_DIR: str = Field(default="snapshots", description="Directory for saved snapshots")

    # ─── YOLO Detection ───────────────────────────────────────────
    YOLO_ENABLED: bool = Field(
        default=True,
        description="Master switch for YOLO object detection",
    )
    YOLO_MODEL_PATH: str = Field(
        default="yolo11n.pt",
        description=(
            "Path atau nama model YOLO. "
            "'yolo11n.pt' akan auto-download saat pertama kali dipakai. "
            "Ganti ke path .pt custom untuk model Roboflow."
        ),
    )
    YOLO_CONF_THRESHOLD: float = Field(
        default=0.4,
        description="Minimum confidence score to keep a detection",
    )
    YOLO_IOU_THRESHOLD: float = Field(
        default=0.45,
        description="IoU threshold used for non-max suppression",
    )
    YOLO_MAX_FPS: float = Field(
        default=10.0,
        description="Maximum inference rate in Hz, independent of video broadcast FPS",
    )
    YOLO_DEVICE: str = Field(
        default="",
        description="Inference device: '' (auto), 'cpu', atau 'cuda:0'",
    )
    YOLO_TARGET_CLASSES: str = Field(
        default="person",
        description=(
            "Comma-separated class names to detect. "
            "Default 'person'. Contoh multi-class: 'person,head'"
        ),
    )

    @property
    def yolo_target_classes(self) -> list[str]:
        """Parse YOLO_TARGET_CLASSES string → list."""
        return [c.strip() for c in self.YOLO_TARGET_CLASSES.split(",") if c.strip()]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
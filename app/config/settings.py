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
    APF_D_SAFE: float = Field(default=10, description="Minimum safe separation (meters)")
    APF_D_INFLUENCE: float = Field(default=30.0, description="Distance at which avoidance begins (meters)")
    APF_K_ATT: float = Field(default=1.0, description="Attractive force gain")
    APF_K_REP: float = Field(default=100.0, description="Repulsive force gain")
    APF_MAX_OFFSET: float = Field(default=20.0, description="Maximum avoidance offset (meters)")
    APF_TICK_RATE_HZ: float = Field(default=5.0, description="APF computation loop rate (Hz)")
    APF_ENTER_M: float = Field(default=15.0, description="Avoidance engages when predicted closest approach is below this (meters)")
    APF_EXIT_M: float = Field(default=20.0, description="Avoidance releases above this separation (meters)")
    APF_PREDICTION_HORIZON_S: float = Field(default=4.0, description="Closest-approach look-ahead (seconds)")

    # Nearest-owner swarm: explicit site configuration, independent of legacy.
    SWARM_LEGACY_ENABLED: bool = True
    SWARM_OPERATOR_TOKEN: str = "ayyubirutijuangnovasintafaiz2026"
    SWARM_LINK_KEY: str = "ayyubirutijuangnovasintafaiz2026"
    SWARM_STORE_PATH: str = "data/swarm.sqlite3"
    SWARM_CENTER_LAT: float | None = None
    SWARM_CENTER_LON: float | None = None
    SWARM_RADIUS_M: float = Field(default=200, gt=0, le=10000)
    SWARM_MIN_ALT_M: float = Field(default=2, gt=0)
    SWARM_MAX_ALT_M: float = Field(default=50, gt=0, le=500)
    SWARM_TAKEOFF_ALT_M: float = Field(default=5, gt=0)
    SWARM_MIN_BATTERY_PCT: float = Field(default=25, gt=0, le=100)
    SWARM_FRESHNESS_S: float = Field(default=2, gt=0, le=3)
    # Min-max route planner that splits and orders waypoints per UAV. Match these to the
    # FC parameters and the companion's hold_duration_s.
    SWARM_PLANNER_V_CRUISE_MPS: float = Field(default=5, gt=0)    # WPNAV_SPEED
    SWARM_PLANNER_T_ACCEL_S: float = Field(default=2, ge=0)       # ~ WPNAV_SPEED / WPNAV_ACCEL
    SWARM_PLANNER_YAW_RATE_DPS: float = Field(default=60, ge=0)   # ATC_SLEW_YAW; 0 leaves yaw out
    SWARM_PLANNER_DWELL_S: float = Field(default=3, ge=0)         # companion hold per waypoint
    SWARM_PLANNER_WIND_SPEED_MPS: float = Field(default=0, ge=0)
    SWARM_PLANNER_WIND_FROM_DEG: float = Field(default=0, ge=0, lt=360)
    SWARM_PLANNER_TIME_LIMIT_S: float = Field(default=10, gt=0)   # CP-SAT / Routing budget
    # A UAV whose next waypoint stays blocked by an idle peer's separation zone this long
    # hands that waypoint to the peer.
    SWARM_DEFER_S: float = Field(default=25, ge=0)
    SWARM_ACK_TIMEOUT_S: float = Field(default=3, gt=0)
    SWARM_END_ACTION: str = Field(default="RTL", pattern="^(HOLD|RTL|LAND)$")



    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()

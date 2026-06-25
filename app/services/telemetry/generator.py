"""
TelemetryGenerator
──────────────────
Produces realistic simulated UAV telemetry at a configurable rate and
broadcasts JSON payloads to all /ws/telemetry WebSocket clients.

Designed so that real MAVLink telemetry can replace this service later
by fulfilling the same interface contract.
"""

import asyncio
import json
import logging
import math
import random
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

from app.services.websocket.manager import WebSocketManager
from app.config.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class TelemetryPacket:
    """Single telemetry snapshot published over WebSocket."""

    # Timing
    timestamp: float = field(default_factory=time.time)
    uptime_s: float = 0.0

    # Identity
    vehicle_id: int = 1
    vehicle_name: str = "UAV-01"

    # Position
    lat: float = -7.7956
    lon: float = 110.3695
    altitude_m: float = 50.0
    relative_alt_m: float = 50.0

    # Motion
    ground_speed_ms: float = 0.0
    air_speed_ms: float = 0.0
    heading_deg: float = 0.0
    climb_rate_ms: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    vz: float = 0.0

    # Orientation
    roll_deg: float = 0.0
    pitch_deg: float = 0.0
    yaw_deg: float = 0.0

    # Power
    battery_voltage: float = 16.4
    battery_current: float = 0.0
    battery_remaining_pct: int = 100

    # Link
    rssi: int = -65
    link_quality_pct: int = 100
    rx_errors: int = 0

    # Mission
    flight_mode: str = "STABILIZE"
    armed: bool = False
    mission_state: str = "IDLE"
    current_waypoint: int = 0
    total_waypoints: int = 0
    distance_to_wp_m: float = 0.0

    # GPS
    gps_fix: int = 3          # 0=no fix, 2=2D, 3=3D
    satellites_visible: int = 12
    hdop: float = 1.0

    # Computed
    ekf_ok: bool = True
    pre_arm_check: bool = True


# Flight-mode sequence used by the simulator
_FLIGHT_MODES = [
    "STABILIZE",
    "ALT_HOLD",
    "LOITER",
    "AUTO",
    "RTL",
    "LAND",
]

_MISSION_STATES = ["IDLE", "TAKEOFF", "WAYPOINT", "RTL", "LANDING", "COMPLETE"]


class TelemetryGenerator:
    """
    Simulates a flying UAV and publishes telemetry at TELEMETRY_HZ.
    All state is internal; swap this class for a MAVLink reader when ready.
    """

    def __init__(self, ws_manager: WebSocketManager) -> None:
        self._ws = ws_manager
        self._hz = settings.TELEMETRY_HZ
        self._start_time = time.monotonic()

        # Simulated UAV state
        self._lat = -7.7956 + random.uniform(-0.005, 0.005)
        self._lon = 110.3695 + random.uniform(-0.005, 0.005)
        self._alt = 0.0
        self._heading = random.uniform(0, 360)
        self._speed = 0.0
        self._battery = 100.0
        self._voltage = 16.8
        self._armed = False
        self._flight_mode = "STABILIZE"
        self._mission_state = "IDLE"
        self._waypoint = 0
        self._rssi = -60 + random.randint(-5, 5)
        self._sim_phase = 0.0   # drives oscillations

        # Persistent packet for latest snapshot
        self._latest: Optional[TelemetryPacket] = None
        logger.info("TelemetryGenerator ready (%.1f Hz)", self._hz)

    # ─── Public ───────────────────────────────────────────────────

    async def broadcast_loop(self) -> None:
        """Coroutine: advance simulation and broadcast at configured Hz."""
        logger.info("TelemetryGenerator broadcast loop started")
        interval = 1.0 / self._hz

        phase_t = 0.0
        flight_timer = 0.0
        TAKEOFF_DURATION = 8.0
        CRUISE_DURATION = 120.0
        LAND_DURATION = 8.0

        while True:
            await asyncio.sleep(interval)

            uptime = time.monotonic() - self._start_time
            phase_t += interval
            self._sim_phase = phase_t
            flight_timer += interval

            # ── State machine ─────────────────────────────────────
            if flight_timer < 5.0:
                self._armed = False
                self._flight_mode = "STABILIZE"
                self._mission_state = "IDLE"

            elif flight_timer < 5.0 + TAKEOFF_DURATION:
                self._armed = True
                self._flight_mode = "ALT_HOLD"
                self._mission_state = "TAKEOFF"
                progress = (flight_timer - 5.0) / TAKEOFF_DURATION
                self._alt = 80.0 * progress
                self._speed = 2.0 + 8.0 * progress

            elif flight_timer < 5.0 + TAKEOFF_DURATION + CRUISE_DURATION:
                self._flight_mode = "AUTO"
                self._mission_state = "WAYPOINT"
                cruise_t = flight_timer - 5.0 - TAKEOFF_DURATION
                # Figure-8 path
                self._lat += 0.000012 * math.sin(cruise_t * 0.05)
                self._lon += 0.000012 * math.cos(cruise_t * 0.025)
                self._alt = 80.0 + 5.0 * math.sin(cruise_t * 0.1)
                self._speed = 10.0 + 3.0 * math.sin(cruise_t * 0.2)
                self._heading = (self._heading + 0.5) % 360
                self._waypoint = int(cruise_t / 20) % 5 + 1

            elif flight_timer < 5.0 + TAKEOFF_DURATION + CRUISE_DURATION + LAND_DURATION:
                self._flight_mode = "LAND"
                self._mission_state = "LANDING"
                progress = (
                    flight_timer - 5.0 - TAKEOFF_DURATION - CRUISE_DURATION
                ) / LAND_DURATION
                self._alt = max(0.0, 80.0 * (1.0 - progress))
                self._speed = max(0.0, 5.0 * (1.0 - progress))
            else:
                # Reset cycle
                flight_timer = 0.0
                self._armed = False
                self._flight_mode = "STABILIZE"
                self._mission_state = "COMPLETE"
                self._alt = 0.0
                self._speed = 0.0
                self._waypoint = 0

            # ── Battery drain ─────────────────────────────────────
            if self._armed:
                drain = 0.003 * interval
                self._battery = max(0.0, self._battery - drain)
                current_draw = 15.0 + 5.0 * math.sin(phase_t * 0.3)
            else:
                current_draw = 0.2
            self._voltage = 16.8 * (0.7 + 0.3 * (self._battery / 100.0))

            # ── Link quality ──────────────────────────────────────
            self._rssi = int(
                -60 + 5 * math.sin(phase_t * 0.07) + random.uniform(-2, 2)
            )
            link_q = min(100, max(0, int(100 + (self._rssi + 90) * 2)))

            # ── Attitude noise ────────────────────────────────────
            roll = 2.0 * math.sin(phase_t * 1.1) + random.uniform(-0.3, 0.3)
            pitch = 1.5 * math.cos(phase_t * 0.9) + random.uniform(-0.3, 0.3)

            pkt = TelemetryPacket(
                timestamp=time.time(),
                uptime_s=round(uptime, 1),
                lat=round(self._lat, 7),
                lon=round(self._lon, 7),
                altitude_m=round(self._alt, 1),
                relative_alt_m=round(self._alt, 1),
                ground_speed_ms=round(self._speed, 1),
                air_speed_ms=round(self._speed + random.uniform(-0.5, 0.5), 1),
                heading_deg=round(self._heading % 360, 1),
                climb_rate_ms=round(
                    2.0 * math.cos(phase_t * 0.3) if self._armed else 0.0, 2
                ),
                roll_deg=round(roll, 1),
                pitch_deg=round(pitch, 1),
                yaw_deg=round(self._heading % 360, 1),
                battery_voltage=round(self._voltage, 2),
                battery_current=round(current_draw, 1),
                battery_remaining_pct=int(self._battery),
                rssi=self._rssi,
                link_quality_pct=link_q,
                flight_mode=self._flight_mode,
                armed=self._armed,
                mission_state=self._mission_state,
                current_waypoint=self._waypoint,
                total_waypoints=5,
                distance_to_wp_m=round(
                    50.0 * abs(math.sin(phase_t * 0.05)) if self._armed else 0.0, 1
                ),
                gps_fix=3 if self._armed else 3,
                satellites_visible=12 + random.randint(-1, 1),
                hdop=round(0.8 + 0.2 * abs(math.sin(phase_t * 0.03)), 2),
                ekf_ok=True,
                pre_arm_check=True,
            )

            self._latest = pkt

            if self._ws.has_telemetry_clients():
                payload = json.dumps(asdict(pkt))
                await self._ws.broadcast_telemetry(payload)

    def get_latest(self) -> Optional[dict]:
        if self._latest is None:
            return None
        return asdict(self._latest)

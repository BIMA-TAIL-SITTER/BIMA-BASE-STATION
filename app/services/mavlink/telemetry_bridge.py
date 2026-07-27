"""Translate routed MAVLink telemetry messages into frontend packets."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from dataclasses import asdict
from typing import Any, Dict, Optional

from app.config.settings import settings
from app.services.mavlink.connection import MavlinkTCPConnection
from app.services.mavlink.interfaces import MAVLinkTelemetryBridge
from app.services.telemetry.generator import TelemetryPacket
from app.services.websocket.manager import WebSocketManager

logger = logging.getLogger(__name__)
UAV_SLOTS = (1, 2, 3, 4)


class MavlinkTelemetryBridge(MAVLinkTelemetryBridge):
    """
    Maintain per-slot telemetry snapshots from messages routed by one reader.

    ``handle_message`` never reads a connection. ``broadcast_loop`` only emits
    the latest snapshot, leaving all receive ownership to MavlinkMessageRouter.
    """

    def __init__(self, ws_manager: WebSocketManager) -> None:
        self._ws = ws_manager
        self._hz = settings.TELEMETRY_HZ
        self.connections: Dict[int, Optional[MavlinkTCPConnection]] = {
            slot: None for slot in UAV_SLOTS
        }
        self._connect_tokens: Dict[int, int] = {
            slot: 0 for slot in UAV_SLOTS
        }
        self._missions: Dict[int, list[dict]] = {
            slot: [] for slot in UAV_SLOTS
        }
        self._home_positions: Dict[int, Optional[tuple[float, float]]] = {
            slot: None for slot in UAV_SLOTS
        }
        self.latest_packets: Dict[int, TelemetryPacket] = {
            slot: TelemetryPacket(
                vehicle_id=slot,
                vehicle_name=f"UAV-{slot:02d}",
            )
            for slot in UAV_SLOTS
        }
        self._running = False
        self._mode_mapping = {
            0: "STABILIZE",
            1: "ACRO",
            2: "ALT_HOLD",
            3: "AUTO",
            4: "GUIDED",
            5: "LOITER",
            6: "RTL",
            7: "CIRCLE",
            9: "LAND",
            11: "DRIFT",
            16: "POSHOLD",
        }

    async def connect_slot(self, slot: int, ip: str, port: int) -> bool:
        if slot not in self.connections:
            return False

        self._connect_tokens[slot] += 1
        token = self._connect_tokens[slot]

        current = self.connections[slot]
        self.connections[slot] = None
        if current is not None:
            await current.disconnect()

        connection = MavlinkTCPConnection(ip, port)
        try:
            await connection.connect()
            if self._connect_tokens[slot] != token:
                logger.info("Discarding stale connection for slot %d", slot)
                await connection.disconnect()
                return False
            self.connections[slot] = connection
            return True
        except Exception as exc:
            logger.error("Failed to connect slot %d: %s", slot, exc)
            await connection.disconnect()
            return False

    async def disconnect_slot(self, slot: int) -> None:
        if slot not in self.connections:
            return
        self._connect_tokens[slot] += 1
        connection = self.connections[slot]
        self.connections[slot] = None
        if connection is not None:
            await connection.disconnect()

    def set_mission(self, slot: int, waypoints: list[dict]) -> None:
        """Update the mission cache used by telemetry target calculations."""
        if slot not in self._missions:
            return
        self._missions[slot] = waypoints
        packet = self.latest_packets[slot]
        packet.total_waypoints = len(waypoints)
        self._update_target_waypoint(slot, packet)

    def get_status(self) -> dict:
        return {
            slot: (
                self.connections[slot].is_connected()
                if self.connections[slot]
                else False
            )
            for slot in UAV_SLOTS
        }

    async def handle_message(self, slot: int, message: Any) -> None:
        """Apply one routed MAVLink message to the selected telemetry packet."""
        if slot not in self.latest_packets:
            return

        message_type = message.get_type()
        packet = self.latest_packets[slot]

        if message_type == "HEARTBEAT":
            custom_mode = message.custom_mode
            packet.flight_mode = self._mode_mapping.get(
                custom_mode,
                f"MODE_{custom_mode}",
            )
            packet.armed = (message.base_mode & 128) != 0

        elif message_type == "GLOBAL_POSITION_INT":
            packet.lat = message.lat / 1e7
            packet.lon = message.lon / 1e7
            packet.altitude_m = message.alt / 1000.0
            packet.relative_alt_m = message.relative_alt / 1000.0
            packet.vx = message.vx / 100.0
            packet.vy = message.vy / 100.0
            packet.vz = message.vz / 100.0
            packet.ground_speed_ms = (
                packet.vx**2 + packet.vy**2
            ) ** 0.5
            home = self._home_positions.get(slot)
            if home and packet.lat is not None and packet.lon is not None:
                packet.home_distance_m = self._distance_m(
                    packet.lat,
                    packet.lon,
                    home[0],
                    home[1],
                )

        elif message_type == "ATTITUDE":
            packet.roll_deg = message.roll * 57.2958
            packet.pitch_deg = message.pitch * 57.2958
            packet.yaw_deg = message.yaw * 57.2958

        elif message_type == "VFR_HUD":
            packet.air_speed_ms = message.airspeed
            packet.heading_deg = message.heading
            packet.climb_rate_ms = message.climb

        elif message_type == "SYS_STATUS":
            packet.battery_voltage = message.voltage_battery / 1000.0
            packet.battery_current = message.current_battery / 100.0
            packet.battery_remaining_pct = message.battery_remaining

        elif message_type == "BATTERY_STATUS":
            if getattr(message, "voltages", None):
                valid_voltages = [
                    voltage
                    for voltage in message.voltages
                    if 0 < voltage < 65535
                ]
                if valid_voltages:
                    packet.battery_voltage = sum(valid_voltages) / 1000.0
            current = getattr(message, "current_battery", -1)
            if current >= 0:
                packet.battery_current = current / 100.0
            remaining = getattr(message, "battery_remaining", -1)
            if remaining >= 0:
                packet.battery_remaining_pct = remaining

        elif message_type == "GPS_RAW_INT":
            packet.gps_fix = message.fix_type
            packet.satellites_visible = message.satellites_visible
            packet.hdop = message.eph / 100.0

        elif message_type == "MISSION_CURRENT":
            packet.current_waypoint = message.seq
            total = getattr(message, "total", 0)
            if total:
                packet.total_waypoints = total
            self._update_target_waypoint(slot, packet)

        elif message_type == "MISSION_COUNT":
            packet.total_waypoints = message.count

        elif message_type == "NAV_CONTROLLER_OUTPUT":
            packet.distance_to_wp_m = float(message.wp_dist)

        elif message_type == "HOME_POSITION":
            self._home_positions[slot] = (
                message.latitude / 1e7,
                message.longitude / 1e7,
            )

    @staticmethod
    def _distance_m(
        lat_1: float,
        lon_1: float,
        lat_2: float,
        lon_2: float,
    ) -> float:
        earth_radius_m = 6_371_000.0
        latitude_delta = math.radians(lat_2 - lat_1)
        longitude_delta = math.radians(lon_2 - lon_1)
        latitude_1 = math.radians(lat_1)
        latitude_2 = math.radians(lat_2)
        haversine = (
            math.sin(latitude_delta / 2) ** 2
            + math.cos(latitude_1)
            * math.cos(latitude_2)
            * math.sin(longitude_delta / 2) ** 2
        )
        return earth_radius_m * 2 * math.atan2(
            math.sqrt(haversine),
            math.sqrt(1 - haversine),
        )

    def _update_target_waypoint(
        self,
        slot: int,
        packet: TelemetryPacket,
    ) -> None:
        mission = self._missions.get(slot, [])
        target = next(
            (
                waypoint
                for waypoint in mission
                if waypoint["seq"] == packet.current_waypoint
            ),
            None,
        )
        if not target:
            packet.target_waypoint_lat = None
            packet.target_waypoint_lon = None
            return

        packet.target_waypoint_lat = target["lat"]
        packet.target_waypoint_lon = target["lon"]
        if packet.lat is not None and packet.lon is not None:
            packet.distance_to_wp_m = self._distance_m(
                packet.lat,
                packet.lon,
                target["lat"],
                target["lon"],
            )

    async def broadcast_loop(self) -> None:
        """Broadcast current snapshots without reading the MAVLink connections."""
        self._running = True
        interval = 1.0 / self._hz

        while self._running:
            started_at = time.monotonic()
            for slot in UAV_SLOTS:
                connection = self.connections[slot]
                if connection is None or not connection.is_connected():
                    continue

                packet = self.latest_packets[slot]
                self._update_target_waypoint(slot, packet)
                packet.timestamp = time.time()
                if self._ws.has_telemetry_clients():
                    data = asdict(packet)
                    data["slot"] = slot
                    await self._ws.broadcast_telemetry(json.dumps(data))

            elapsed = time.monotonic() - started_at
            await asyncio.sleep(max(0.0, interval - elapsed))

    def get_latest(self) -> Optional[dict]:
        return {
            f"slot_{slot}": asdict(self.latest_packets[slot])
            for slot in UAV_SLOTS
        }

    async def stop(self) -> None:
        self._running = False
        for slot in UAV_SLOTS:
            await self.disconnect_slot(slot)

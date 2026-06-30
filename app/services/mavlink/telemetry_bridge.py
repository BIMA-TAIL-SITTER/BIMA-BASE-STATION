import asyncio
import json
import logging
import time
from dataclasses import asdict
from typing import Optional, Dict

from app.config.settings import settings
from app.services.mavlink.interfaces import MAVLinkTelemetryBridge
from app.services.mavlink.connection import MavlinkTCPConnection
from app.services.telemetry.generator import TelemetryPacket
from app.services.websocket.manager import WebSocketManager

logger = logging.getLogger(__name__)


class MavlinkTelemetryBridge(MAVLinkTelemetryBridge):
    """
    Reads from two independent MAVLink TCP connections (one per UI slot)
    and maps the data to TelemetryPacket.
    """

    def __init__(self, ws_manager: WebSocketManager) -> None:
        self._ws = ws_manager
        self._hz = settings.TELEMETRY_HZ
        
        self.connections: Dict[int, Optional[MavlinkTCPConnection]] = {
            1: None,
            2: None
        }
        self._connect_tokens: Dict[int, int] = {1: 0, 2: 0}
        self.latest_packets: Dict[int, TelemetryPacket] = {
            1: TelemetryPacket(vehicle_id=1, vehicle_name="UAV-01"),
            2: TelemetryPacket(vehicle_id=2, vehicle_name="UAV-02")
        }
        self._running = False
        
        # MAVLink field mapping
        self._mode_mapping = {
            0: "STABILIZE", 1: "ACRO", 2: "ALT_HOLD", 3: "AUTO", 4: "GUIDED",
            5: "LOITER", 6: "RTL", 7: "CIRCLE", 9: "LAND", 11: "DRIFT", 16: "POSHOLD"
        }

    async def connect_slot(self, slot: int, ip: str, port: int) -> bool:
        if slot not in self.connections:
            return False
            
        # Increment token so any pending connects are invalidated
        self._connect_tokens[slot] += 1
        my_token = self._connect_tokens[slot]
            
        # Disconnect existing if any
        if self.connections[slot]:
            await self.connections[slot].disconnect()
            
        conn = MavlinkTCPConnection(ip, port)
        try:
            await conn.connect()
            # If a newer request came in while we were connecting, discard this one
            if self._connect_tokens[slot] != my_token:
                logger.info("Discarding stale connection for slot %d", slot)
                await conn.disconnect()
                return False
                
            self.connections[slot] = conn
            return True
        except Exception as e:
            logger.error("Failed to connect slot %d: %s", slot, e)
            return False

    async def disconnect_slot(self, slot: int) -> None:
        if slot in self.connections:
            self._connect_tokens[slot] += 1
            if self.connections[slot]:
                await self.connections[slot].disconnect()
                self.connections[slot] = None

    def get_status(self) -> dict:
        return {
            1: self.connections[1].is_connected() if self.connections[1] else False,
            2: self.connections[2].is_connected() if self.connections[2] else False
        }

    async def broadcast_loop(self) -> None:
        self._running = True
        interval = 1.0 / self._hz
        
        while self._running:
            start_t = time.monotonic()
            
            for slot in [1, 2]:
                conn = self.connections[slot]
                if not conn or not conn.is_connected():
                    continue
                    
                # Read all pending messages (non-blocking)
                while True:
                    msg = conn.recv_msg()
                    if msg is None:
                        break
                        
                    t = msg.get_type()
                    pkt = self.latest_packets[slot]
                    
                    if t == "HEARTBEAT":
                        custom_mode = msg.custom_mode
                        pkt.flight_mode = self._mode_mapping.get(custom_mode, f"MODE_{custom_mode}")
                        pkt.armed = (msg.base_mode & 128) != 0 # MAV_MODE_FLAG_SAFETY_ARMED
                        
                    elif t == "GLOBAL_POSITION_INT":
                        pkt.lat = msg.lat / 1e7
                        pkt.lon = msg.lon / 1e7
                        pkt.altitude_m = msg.alt / 1000.0
                        pkt.relative_alt_m = msg.relative_alt / 1000.0
                        pkt.vx = msg.vx / 100.0
                        pkt.vy = msg.vy / 100.0
                        pkt.vz = msg.vz / 100.0
                        pkt.ground_speed_ms = (pkt.vx**2 + pkt.vy**2)**0.5
                        
                    elif t == "ATTITUDE":
                        pkt.roll_deg = msg.roll * 57.2958
                        pkt.pitch_deg = msg.pitch * 57.2958
                        pkt.yaw_deg = msg.yaw * 57.2958
                        
                    elif t == "VFR_HUD":
                        pkt.air_speed_ms = msg.airspeed
                        pkt.heading_deg = msg.heading
                        pkt.climb_rate_ms = msg.climb
                        
                    elif t == "SYS_STATUS":
                        pkt.battery_voltage = msg.voltage_battery / 1000.0
                        pkt.battery_current = msg.current_battery / 100.0
                        pkt.battery_remaining_pct = msg.battery_remaining
                        
                    elif t == "GPS_RAW_INT":
                        pkt.gps_fix = msg.fix_type
                        pkt.satellites_visible = msg.satellites_visible
                        pkt.hdop = msg.eph / 100.0
                
                pkt = self.latest_packets[slot]
                pkt.timestamp = time.time()
                
                # Broadcast for this slot
                if self._ws.has_telemetry_clients():
                    data = asdict(pkt)
                    data["slot"] = slot  # inject slot ID
                    payload = json.dumps(data)
                    await self._ws.broadcast_telemetry(payload)
                    
            elapsed = time.monotonic() - start_t
            sleep_t = max(0.0, interval - elapsed)
            await asyncio.sleep(sleep_t)

    def get_latest(self) -> Optional[dict]:
        # Legacy compat for /api/telemetry/latest
        return {
            "slot_1": asdict(self.latest_packets[1]),
            "slot_2": asdict(self.latest_packets[2])
        }
        
    async def stop(self):
        self._running = False
        for slot in [1, 2]:
            await self.disconnect_slot(slot)

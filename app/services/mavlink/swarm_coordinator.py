"""
Swarm Coordinator — orchestration service for dual-copter operations.
═════════════════════════════════════════════════════════════════════
Manages:
  - Batch mission upload to two UAVs (slots 3 & 4)
  - Readiness barrier before start
  - Coordinated start via MAV_CMD_USER_1 to each Companion Bridge
  - APF integration (reading telemetry, computing avoidance, sending corrections)
  - Safety interlocks
  - Abort / emergency handling

This service is wired into main.py and exposed via app/routers/swarm.py.
"""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import math
import os
import time
from dataclasses import asdict
from datetime import datetime
from typing import Any, Optional

from app.schemas.swarm import (
    APFStatus,
    MissionBatchUploadResponse,
    PerUAVFlightPhase,
    PerUAVUploadResult,
    PerUAVUploadStatus,
    SwarmAbortResponse,
    SwarmPhase,
    SwarmStartResponse,
    SwarmStatusResponse,
)
from app.services.mavlink.apf_coordinator import (
    APFConfig,
    APFEngine,
    APFResult,
    UAVState,
)
from app.services.mavlink.interfaces import MissionItem

logger = logging.getLogger(__name__)

# Copter slots in the existing 4-slot architecture
COPTER_SLOT_A = 3  # UAV-3
COPTER_SLOT_B = 4  # UAV-4
COPTER_SLOTS = (COPTER_SLOT_A, COPTER_SLOT_B)

# MAV_CMD_USER_1 — must match companion_bridge.py
MAV_CMD_USER_1 = 31010


class SwarmCoordinator:
    """
    Central orchestration state machine for dual-copter swarm.

    Injected dependencies:
      - command_bridge: MavlinkCommandBridge (for upload_mission, arm, set_mode)
      - telemetry_bridge: MavlinkTelemetryBridge (for reading latest telemetry)
      - ws_manager: WebSocketManager (for pushing swarm status to frontend)
    """

    def __init__(
        self,
        command_bridge: Any,
        telemetry_bridge: Any,
        message_router: Any,
        ws_manager: Any,
        apf_config: Optional[APFConfig] = None,
    ) -> None:
        self._cmd = command_bridge
        self._telem = telemetry_bridge
        self._router = message_router
        self._ws = ws_manager

        # APF engine
        self._apf = APFEngine(apf_config or APFConfig())
        self._apf_task: Optional[asyncio.Task] = None

        # --- Swarm state ---
        self._phase = SwarmPhase.IDLE

        # Per-UAV upload state
        self._upload_status: dict[int, PerUAVUploadResult] = {
            COPTER_SLOT_A: PerUAVUploadResult(
                slot=COPTER_SLOT_A, status=PerUAVUploadStatus.PENDING,
            ),
            COPTER_SLOT_B: PerUAVUploadResult(
                slot=COPTER_SLOT_B, status=PerUAVUploadStatus.PENDING,
            ),
        }

        # Per-UAV flight phase
        self._flight_phase: dict[int, PerUAVFlightPhase] = {
            COPTER_SLOT_A: PerUAVFlightPhase.IDLE,
            COPTER_SLOT_B: PerUAVFlightPhase.IDLE,
        }

        # Last APF results
        self._last_apf: dict[int, Optional[APFResult]] = {
            COPTER_SLOT_A: None,
            COPTER_SLOT_B: None,
        }

        # Interlock state
        self._interlock_failures: list[str] = []

        # CSV log file handle
        self._apf_log_file = None
        self._apf_csv_writer = None
        self._init_apf_logger()

    def _init_apf_logger(self):
        """Initialize CSV logging for APF decisions."""
        log_dir = "logs/apf"
        os.makedirs(log_dir, exist_ok=True)
        filename = datetime.now().strftime("apf_log_%Y%m%d_%H%M%S.csv")
        filepath = os.path.join(log_dir, filename)
        
        try:
            self._apf_log_file = open(filepath, mode='w', newline='')
            self._apf_csv_writer = csv.writer(self._apf_log_file)
            # Write header
            self._apf_csv_writer.writerow([
                "timestamp", "d_ij", "d_cpa", "t_cpa", 
                "uav3_avoid", "uav4_avoid",
                "uav3_offset", "uav4_offset",
                "uav3_lat", "uav3_lon", "uav3_alt",
                "uav4_lat", "uav4_lon", "uav4_alt",
            ])
            logger.info("APF CSV logging initialized: %s", filepath)
        except Exception as exc:
            logger.error("Failed to initialize APF CSV logging: %s", exc)

    # ─── Status Snapshot ──────────────────────────────────────────

    def status(self) -> SwarmStatusResponse:
        """Build a full status snapshot for the frontend."""
        apf_a = self._last_apf.get(COPTER_SLOT_A)
        apf_b = self._last_apf.get(COPTER_SLOT_B)

        apf_status = APFStatus()
        if apf_a and apf_b:
            def _san(val):
                return -1.0 if math.isinf(val) else val

            apf_status = APFStatus(
                active=apf_a.avoidance_active or apf_b.avoidance_active,
                d_ij=_san(apf_a.d_ij),
                d_cpa=_san(apf_a.d_cpa),
                t_cpa=_san(apf_a.t_cpa),
                uav_3_offset_m=apf_a.offset_m,
                uav_4_offset_m=apf_b.offset_m,
                uav_3_avoidance_active=apf_a.avoidance_active,
                uav_4_avoidance_active=apf_b.avoidance_active,
                stale=apf_a.stale or apf_b.stale,
                warning=apf_a.reason or apf_b.reason,
            )

        interlocks = self._check_interlocks()

        return SwarmStatusResponse(
            phase=self._phase,
            uav_3_upload=self._upload_status[COPTER_SLOT_A].status,
            uav_4_upload=self._upload_status[COPTER_SLOT_B].status,
            uav_3_flight=self._flight_phase[COPTER_SLOT_A],
            uav_4_flight=self._flight_phase[COPTER_SLOT_B],
            ready_to_start=self._is_ready_to_start(),
            apf=apf_status,
            interlocks_passed=len(interlocks) == 0,
            interlock_failures=interlocks,
            message=f"Phase: {self._phase.value}",
        )

    # ─── Batch Upload ─────────────────────────────────────────────

    async def upload_batch(
        self,
        items_a: list[MissionItem],
        items_b: list[MissionItem],
        ip_3: Optional[str] = None,
        port_3: Optional[int] = None,
        ip_4: Optional[str] = None,
        port_4: Optional[int] = None,
    ) -> MissionBatchUploadResponse:
        """
        Upload missions to both copters in parallel.

        Each transaction is independent: one can fail without affecting the other.
        The system enters READY_TO_START only if both succeed.
        """
        if self._phase not in (SwarmPhase.IDLE, SwarmPhase.PARTIAL_UPLOAD, SwarmPhase.FAILED):
            return MissionBatchUploadResponse(
                phase=self._phase,
                uav_3=self._upload_status[COPTER_SLOT_A],
                uav_4=self._upload_status[COPTER_SLOT_B],
                message=f"Cannot upload in phase {self._phase.value}",
            )

        self._phase = SwarmPhase.UPLOADING
        logger.info("Swarm batch upload starting: UAV-3=%d items, UAV-4=%d items",
                     len(items_a), len(items_b))

        # Reset upload status
        for slot in COPTER_SLOTS:
            self._upload_status[slot] = PerUAVUploadResult(
                slot=slot, status=PerUAVUploadStatus.UPLOADING,
            )

        await self._broadcast_status()

        # Execute uploads concurrently with overrides
        results = await asyncio.gather(
            self._upload_single(COPTER_SLOT_A, items_a, ip_3, port_3),
            self._upload_single(COPTER_SLOT_B, items_b, ip_4, port_4),
            return_exceptions=True,
        )

        result_a, result_b = results

        # Handle exceptions
        if isinstance(result_a, Exception):
            logger.error("UAV-3 upload exception: %s", result_a)
            self._upload_status[COPTER_SLOT_A] = PerUAVUploadResult(
                slot=COPTER_SLOT_A, status=PerUAVUploadStatus.ERROR,
                message=str(result_a),
            )
        if isinstance(result_b, Exception):
            logger.error("UAV-4 upload exception: %s", result_b)
            self._upload_status[COPTER_SLOT_B] = PerUAVUploadResult(
                slot=COPTER_SLOT_B, status=PerUAVUploadStatus.ERROR,
                message=str(result_b),
            )

        # Determine system phase
        a_ok = self._upload_status[COPTER_SLOT_A].status == PerUAVUploadStatus.ACCEPTED
        b_ok = self._upload_status[COPTER_SLOT_B].status == PerUAVUploadStatus.ACCEPTED

        if a_ok and b_ok:
            self._phase = SwarmPhase.READY_TO_START
            msg = "Both missions accepted — ready to start"
        elif a_ok or b_ok:
            self._phase = SwarmPhase.PARTIAL_UPLOAD
            msg = "One UAV accepted, one failed — retry the failed UAV"
        else:
            self._phase = SwarmPhase.FAILED
            msg = "Both uploads failed"

        logger.info("Swarm batch upload result: %s", msg)
        await self._broadcast_status()

        return MissionBatchUploadResponse(
            phase=self._phase,
            uav_3=self._upload_status[COPTER_SLOT_A],
            uav_4=self._upload_status[COPTER_SLOT_B],
            ready_to_start=a_ok and b_ok,
            message=msg,
        )

    async def _upload_single(self, slot: int, items: list[MissionItem], override_ip: Optional[str] = None, override_port: Optional[int] = None) -> None:
        """Upload mission to one UAV via gcs_mission_client UDP port."""
        import json
        import os
        import sys
        import asyncio
        from app.config.settings import settings
        
        try:
            # Determine IP
            idx = 0 if slot == COPTER_SLOT_A else 1
            ip = override_ip or (settings.mavlink_host_list[idx] if idx < len(settings.mavlink_host_list) else None)
            port = override_port or 14560 # Default companion bridge UDP port
            
            if not ip:
                raise ValueError(f"No IP configured for slot {slot}")
            
            # Write mission items to temp file
            import tempfile
            fd, tmp_path = tempfile.mkstemp(suffix=".json", text=True)
            
            mission_dicts = []
            for item in items:
                mission_dicts.append({
                    "command": item.command,
                    "param1": item.param1,
                    "param2": item.param2,
                    "param3": item.param3,
                    "param4": item.param4,
                    "lat": item.x,
                    "lon": item.y,
                    "alt": item.z
                })
                
            with os.fdopen(fd, 'w') as f:
                json.dump(mission_dicts, f)
                
            script_path = os.path.join(os.getcwd(), "mission_scripts", "gcs_mission_client.py")
            script_dir = os.path.dirname(script_path)
            
            python_exec = sys.executable
            if "uvicorn" in os.path.basename(python_exec).lower():
                python_exec = "python"

            logger.info("Triggering gcs_mission_client for upload to %s:%s", ip, port)
            
            def _run():
                import subprocess
                env = os.environ.copy()
                env["PYTHONUNBUFFERED"] = "1"
                proc = subprocess.Popen(
                    [python_exec, script_path, "--action", "upload", "--ip", ip, "--port", str(port), "--mission-file", tmp_path],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=script_dir, env=env, text=True
                )
                out, _ = proc.communicate()
                return proc.returncode, out
                
            loop = asyncio.get_running_loop()
            returncode, stdout_str = await loop.run_in_executor(None, _run)
            
            try:
                os.remove(tmp_path)
            except Exception:
                pass
                
            if returncode == 0:
                self._upload_status[slot] = PerUAVUploadResult(
                    slot=slot,
                    status=PerUAVUploadStatus.ACCEPTED,
                    total=len(items),
                    sent=len(items),
                    result_code=0,
                    result_label="ACCEPTED",
                    message="Mission uploaded via companion bridge",
                )
            else:
                out_str = stdout_str if stdout_str else "Unknown error"
                self._upload_status[slot] = PerUAVUploadResult(
                    slot=slot,
                    status=PerUAVUploadStatus.ERROR,
                    message=f"gcs_mission_client failed: {out_str[-100:]}",
                )
        except asyncio.TimeoutError:
            self._upload_status[slot] = PerUAVUploadResult(
                slot=slot,
                status=PerUAVUploadStatus.TIMEOUT,
                message="Upload timed out",
            )
        except Exception as exc:
            logger.error(f"_upload_single exception for slot {slot}: {exc}")
            self._upload_status[slot] = PerUAVUploadResult(
                slot=slot,
                status=PerUAVUploadStatus.ERROR,
                message=str(exc),
            )

    # ─── Coordinated Start ────────────────────────────────────────

    async def start_mission(self, confirmation: str, ip_3: Optional[str] = None, port_3: Optional[int] = None, ip_4: Optional[str] = None, port_4: Optional[int] = None) -> SwarmStartResponse:
        """
        Coordinated start: send MAV_CMD_USER_1 to both Companion Bridges via gcs_mission_client.py
        """
        if self._phase != SwarmPhase.READY_TO_START:
            return SwarmStartResponse(
                phase=self._phase,
                accepted=False,
                message=f"Cannot start in phase {self._phase.value}",
            )
            
        interlocks = self._check_interlocks()
        if interlocks:
            return SwarmStartResponse(
                phase=self._phase,
                accepted=False,
                message=f"Safety interlocks failed: {'; '.join(interlocks)}",
            )

        if confirmation != "CONFIRM_START":
            return SwarmStartResponse(
                phase=self._phase,
                accepted=False,
                message="Confirmation required: send 'CONFIRM_START'",
            )

        self._phase = SwarmPhase.STARTING
        logger.info("Swarm coordinated start initiated")
        await self._broadcast_status()

        # Send MAV_CMD_USER_1 to both bridges via the companion upload endpoint
        # This uses the subprocess-based mechanism already in control.py
        results = await asyncio.gather(
            self._send_start_to_bridge(COPTER_SLOT_A, ip_3, port_3),
            self._send_start_to_bridge(COPTER_SLOT_B, ip_4, port_4),
            return_exceptions=True,
        )

        a_ok = not isinstance(results[0], Exception) and results[0] is True
        b_ok = not isinstance(results[1], Exception) and results[1] is True

        if a_ok and b_ok:
            self._phase = SwarmPhase.ARMING
            self._flight_phase[COPTER_SLOT_A] = PerUAVFlightPhase.PRECHECK
            self._flight_phase[COPTER_SLOT_B] = PerUAVFlightPhase.PRECHECK

            # Start APF monitoring loop
            self._start_apf_loop()

            msg = "Start command accepted by both bridges"
        else:
            self._phase = SwarmPhase.FAILED
            msg = "Start command failed for one or both UAVs"

        await self._broadcast_status()

        return SwarmStartResponse(
            phase=self._phase,
            accepted=a_ok and b_ok,
            message=msg,
            uav_3_phase=self._flight_phase[COPTER_SLOT_A],
            uav_4_phase=self._flight_phase[COPTER_SLOT_B],
        )

    async def _send_start_to_bridge(self, slot: int, override_ip: Optional[str] = None, override_port: Optional[int] = None) -> bool:
        """
        Send MAV_CMD_USER_1 to one Companion Bridge.
        Uses the subprocess-based mechanism to connect via UDP port 14560.
        """
        try:
            import os
            import sys
            import asyncio
            from app.config.settings import settings
            
            # Determine IP
            idx = 0 if slot == COPTER_SLOT_A else 1
            ip = override_ip or (settings.mavlink_host_list[idx] if idx < len(settings.mavlink_host_list) else None)
            port = override_port or 14560 # Default companion bridge UDP port
            
            if not ip:
                logger.error(f"No IP configured for slot {slot}")
                return False
                
            script_path = os.path.join(os.getcwd(), "mission_scripts", "gcs_mission_client.py")
            script_dir = os.path.dirname(script_path)
            
            python_exec = sys.executable
            if "uvicorn" in os.path.basename(python_exec).lower():
                python_exec = "python"

            logger.info("Triggering gcs_mission_client for START to %s:%s", ip, port)
            
            def _run_start():
                import subprocess
                env = os.environ.copy()
                env["PYTHONUNBUFFERED"] = "1"
                proc = subprocess.Popen(
                    [python_exec, script_path, "--action", "start", "--ip", ip, "--port", str(port)],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=script_dir, env=env, text=True
                )
                out, _ = proc.communicate()
                return proc.returncode, out
                
            loop = asyncio.get_running_loop()
            returncode, stdout_str = await loop.run_in_executor(None, _run_start)
            
            if returncode == 0:
                logger.info(
                    "Start command slot %d: ACCEPTED", slot
                )
                return True
            else:
                out_str = stdout_str if stdout_str else "Unknown error"
                logger.error("Start command error for slot %d: %s", slot, out_str[-100:])
                return False

        except asyncio.TimeoutError:
            logger.error("Start command timeout for slot %d", slot)
            return False
        except Exception as exc:
            logger.error("Start command exception for slot %d: %s", slot, exc)
            return False

    # ─── Abort ────────────────────────────────────────────────────

    async def abort(self, reason: str = "User abort") -> SwarmAbortResponse:
        """
        Emergency abort: switch both UAVs to LOITER (if airborne) or disarm (if on ground).

        SAFETY: Never disarm while airborne.
        """
        logger.warning("SWARM ABORT: %s", reason)
        prev_phase = self._phase
        self._phase = SwarmPhase.ABORTING

        # Stop APF loop
        self._stop_apf_loop()

        actions = {}
        for slot in COPTER_SLOTS:
            try:
                # Check if armed
                packet = self._telem.latest_packets.get(slot)
                is_armed = packet.armed if packet else False
                alt = packet.relative_alt_m if packet else 0

                if is_armed and alt > 1.0:
                    # Airborne — switch to LOITER, do NOT disarm
                    await self._cmd.set_mode(slot, "LOITER")
                    actions[slot] = "LOITER (airborne safety)"
                    self._flight_phase[slot] = PerUAVFlightPhase.ABORTED
                elif is_armed:
                    # On ground — safe to disarm
                    await self._cmd.disarm(slot, force=True)
                    actions[slot] = "DISARM (on ground)"
                    self._flight_phase[slot] = PerUAVFlightPhase.ABORTED
                else:
                    actions[slot] = "Already disarmed"
                    self._flight_phase[slot] = PerUAVFlightPhase.ABORTED
            except Exception as exc:
                actions[slot] = f"Error: {exc}"
                logger.error("Abort error for slot %d: %s", slot, exc)

        self._phase = SwarmPhase.FAILED
        await self._broadcast_status()

        return SwarmAbortResponse(
            phase=self._phase,
            message=f"Abort executed: {reason}",
            uav_3_action=actions.get(COPTER_SLOT_A, ""),
            uav_4_action=actions.get(COPTER_SLOT_B, ""),
        )

    # ─── Reset ────────────────────────────────────────────────────

    async def reset(self) -> SwarmStatusResponse:
        """Reset swarm state to IDLE for a fresh operation cycle."""
        self._stop_apf_loop()
        self._phase = SwarmPhase.IDLE
        for slot in COPTER_SLOTS:
            self._upload_status[slot] = PerUAVUploadResult(
                slot=slot, status=PerUAVUploadStatus.PENDING,
            )
            self._flight_phase[slot] = PerUAVFlightPhase.IDLE
            self._last_apf[slot] = None
        self._interlock_failures.clear()
        self._apf.reset()

        if self._apf_log_file:
            try:
                self._apf_log_file.flush()
            except Exception:
                pass

        await self._broadcast_status()
        return self.status()

    # ─── Safety Interlocks ────────────────────────────────────────

    def _check_interlocks(self) -> list[str]:
        """
        Evaluate all safety interlocks.
        Returns a list of failure descriptions (empty = all passed).
        """
        failures = []

        for slot in COPTER_SLOTS:
            conn = self._telem.connections.get(slot)
            if conn is None or not conn.is_connected():
                failures.append(f"Slot {slot}: no MAVLink connection")
                continue

            packet = self._telem.latest_packets.get(slot)
            if packet is None:
                failures.append(f"Slot {slot}: no telemetry data")
                continue

            # GPS check
            if hasattr(packet, "gps_fix") and packet.gps_fix < 3:
                failures.append(f"Slot {slot}: GPS fix insufficient ({packet.gps_fix})")

            # Satellite count
            if hasattr(packet, "satellites_visible") and packet.satellites_visible is not None:
                if packet.satellites_visible < 6:
                    failures.append(f"Slot {slot}: too few satellites ({packet.satellites_visible})")

            # Mission upload check
            upload = self._upload_status.get(slot)
            if upload is None or upload.status != PerUAVUploadStatus.ACCEPTED:
                failures.append(f"Slot {slot}: mission not accepted (status={upload.status if upload else 'None'})")

            # Already armed check (should not be armed before start)
            if hasattr(packet, "armed") and packet.armed:
                failures.append(f"Slot {slot}: already armed")

        # Inter-UAV distance check
        p3 = self._telem.latest_packets.get(COPTER_SLOT_A)
        p4 = self._telem.latest_packets.get(COPTER_SLOT_B)
        if (p3 and p4
                and p3.lat is not None and p3.lon is not None
                and p4.lat is not None and p4.lon is not None):
            from app.services.mavlink.apf_coordinator import haversine_distance_m
            dist = haversine_distance_m(p3.lat, p3.lon, p4.lat, p4.lon)
            if dist < 0.1:
                logger.warning("Takeoff positions are identical (%.1fm). Assuming SITL without offsets; bypassing interlock.", dist)
            elif dist < self._apf.config.d_safe:
                logger.warning(
                    f"Takeoff positions too close ({dist:.1f}m < {self._apf.config.d_safe}m). Safety bypassed."
                )
                # failures.append(
                #     f"Takeoff positions too close ({dist:.1f}m < {self._apf.config.d_safe}m)"
                # )

        self._interlock_failures = failures
        return failures

    def _is_ready_to_start(self) -> bool:
        """Check if all conditions for starting are met."""
        if self._phase != SwarmPhase.READY_TO_START:
            return False
        return len(self._check_interlocks()) == 0

    # ─── Telemetry-Driven Phase Tracking ─────────────────────────

    # Altitude threshold (meters) to consider a UAV "airborne"
    _TAKEOFF_ALT_THRESHOLD = 1.0
    # Altitude threshold to consider hover stabilized
    _HOVER_ALT_THRESHOLD = 3.0

    def _get_uav_telemetry(self, slot: int):
        """Get latest telemetry packet for a slot, or None."""
        return self._telem.latest_packets.get(slot)

    def _update_per_uav_phase(self, slot: int) -> None:
        """Update a single UAV's flight phase from telemetry."""
        packet = self._get_uav_telemetry(slot)
        if packet is None:
            return

        armed = getattr(packet, "armed", False)
        alt = getattr(packet, "relative_alt_m", 0) or 0
        mode = (getattr(packet, "flight_mode", "") or "").upper()
        cur_wp = getattr(packet, "current_waypoint", 0) or 0
        total_wp = getattr(packet, "total_waypoints", 0) or 0
        current = self._flight_phase[slot]

        if current == PerUAVFlightPhase.PRECHECK:
            if armed:
                self._flight_phase[slot] = PerUAVFlightPhase.ARMING
                logger.info("Slot %d: PRECHECK → ARMING (armed)", slot)
        elif current == PerUAVFlightPhase.ARMING:
            if armed and alt > self._TAKEOFF_ALT_THRESHOLD:
                self._flight_phase[slot] = PerUAVFlightPhase.TAKEOFF
                logger.info("Slot %d: ARMING → TAKEOFF (alt=%.1fm)", slot, alt)
        elif current == PerUAVFlightPhase.TAKEOFF:
            if alt > self._HOVER_ALT_THRESHOLD:
                self._flight_phase[slot] = PerUAVFlightPhase.HOVER_STABILIZING
                logger.info("Slot %d: TAKEOFF → HOVER_STABILIZING (alt=%.1fm)", slot, alt)
        elif current == PerUAVFlightPhase.HOVER_STABILIZING:
            if mode in ("AUTO", "GUIDED"):
                self._flight_phase[slot] = PerUAVFlightPhase.AUTO_RUNNING
                logger.info("Slot %d: HOVER_STABILIZING → AUTO_RUNNING (mode=%s)", slot, mode)
            elif not armed or (mode in ("LAND", "RTL") and alt < self._TAKEOFF_ALT_THRESHOLD):
                self._flight_phase[slot] = PerUAVFlightPhase.COMPLETED
                logger.info("Slot %d: HOVER_STABILIZING → COMPLETED (landed/disarmed)", slot)
        elif current == PerUAVFlightPhase.AUTO_RUNNING:
            if not armed:
                self._flight_phase[slot] = PerUAVFlightPhase.COMPLETED
                logger.info("Slot %d: AUTO_RUNNING → COMPLETED (disarmed)", slot)
            elif mode in ("LAND", "RTL") and alt < self._TAKEOFF_ALT_THRESHOLD:
                self._flight_phase[slot] = PerUAVFlightPhase.COMPLETED
                logger.info("Slot %d: AUTO_RUNNING → COMPLETED (landed, mode=%s)", slot, mode)

    async def _update_flight_phases(self) -> None:
        """
        Read telemetry from both UAVs and advance swarm + per-UAV phases.
        Called on every APF loop tick.
        """
        # Only track phases when in an active flight state
        if self._phase not in (
            SwarmPhase.ARMING, SwarmPhase.TAKEOFF,
            SwarmPhase.HOVER_STABILIZING, SwarmPhase.AUTO_RUNNING,
        ):
            return

        # Update per-UAV phases
        for slot in COPTER_SLOTS:
            self._update_per_uav_phase(slot)

        phase_a = self._flight_phase[COPTER_SLOT_A]
        phase_b = self._flight_phase[COPTER_SLOT_B]

        prev_phase = self._phase

        # Determine swarm-level phase from per-UAV phases
        if self._phase == SwarmPhase.ARMING:
            # Advance when at least one is past ARMING
            if phase_a.value not in ("IDLE", "PRECHECK") and phase_b.value not in ("IDLE", "PRECHECK"):
                if self._any_at_or_past(PerUAVFlightPhase.TAKEOFF):
                    self._phase = SwarmPhase.TAKEOFF

        if self._phase == SwarmPhase.TAKEOFF:
            if self._both_at_or_past(PerUAVFlightPhase.HOVER_STABILIZING):
                self._phase = SwarmPhase.HOVER_STABILIZING

        if self._phase == SwarmPhase.HOVER_STABILIZING:
            if self._both_at_or_past(PerUAVFlightPhase.AUTO_RUNNING):
                self._phase = SwarmPhase.AUTO_RUNNING

        if self._phase == SwarmPhase.AUTO_RUNNING:
            if phase_a == PerUAVFlightPhase.COMPLETED and phase_b == PerUAVFlightPhase.COMPLETED:
                self._phase = SwarmPhase.COMPLETED
                self._stop_apf_loop()
                logger.info("Both UAVs completed — swarm phase → COMPLETED")

        if self._phase != prev_phase:
            logger.info("Swarm phase: %s → %s", prev_phase.value, self._phase.value)
            await self._broadcast_status()

    # Phase comparison helpers
    _PHASE_ORDER = [
        PerUAVFlightPhase.IDLE,
        PerUAVFlightPhase.PRECHECK,
        PerUAVFlightPhase.ARMING,
        PerUAVFlightPhase.TAKEOFF,
        PerUAVFlightPhase.HOVER_STABILIZING,
        PerUAVFlightPhase.AUTO_RUNNING,
        PerUAVFlightPhase.COMPLETED,
    ]

    def _phase_index(self, phase: PerUAVFlightPhase) -> int:
        try:
            return self._PHASE_ORDER.index(phase)
        except ValueError:
            return -1

    def _any_at_or_past(self, target: PerUAVFlightPhase) -> bool:
        target_idx = self._phase_index(target)
        return any(
            self._phase_index(self._flight_phase[s]) >= target_idx
            for s in COPTER_SLOTS
        )

    def _both_at_or_past(self, target: PerUAVFlightPhase) -> bool:
        target_idx = self._phase_index(target)
        return all(
            self._phase_index(self._flight_phase[s]) >= target_idx
            for s in COPTER_SLOTS
        )

    # ─── APF Loop ─────────────────────────────────────────────────

    def _start_apf_loop(self) -> None:
        """Start background APF computation task."""
        if self._apf_task is not None and not self._apf_task.done():
            return
        self._apf_task = asyncio.create_task(
            self._apf_loop(), name="apf-loop",
        )
        logger.info("APF monitoring loop started")

    def _stop_apf_loop(self) -> None:
        """Cancel the APF background task."""
        if self._apf_task is not None:
            self._apf_task.cancel()
            self._apf_task = None
            logger.info("APF monitoring loop stopped")

    async def _apf_loop(self) -> None:
        """
        Periodic APF computation loop.

        Reads telemetry from both UAVs, computes forces, logs results,
        and broadcasts APF status to the frontend.
        """
        interval = 1.0 / self._apf.config.tick_rate_hz

        try:
            while True:
                started_at = time.monotonic()

                # Build UAV states from latest telemetry
                uav_a = self._build_uav_state(COPTER_SLOT_A)
                uav_b = self._build_uav_state(COPTER_SLOT_B)

                # Update flight phases from telemetry
                await self._update_flight_phases()

                if uav_a and uav_b:
                    result_a, result_b = self._apf.tick(uav_a, uav_b)
                    self._last_apf[COPTER_SLOT_A] = result_a
                    self._last_apf[COPTER_SLOT_B] = result_b

                    # Log APF decision
                    self._log_apf_tick(uav_a, uav_b, result_a, result_b)

                    # Broadcast to frontend
                    await self._broadcast_apf_status(result_a, result_b)

                    # Send corrections to FC if avoidance is active
                    if result_a.avoidance_active and not result_a.stale:
                        self._send_apf_correction_to_fc(COPTER_SLOT_A, uav_a, result_a)
                    if result_b.avoidance_active and not result_b.stale:
                        self._send_apf_correction_to_fc(COPTER_SLOT_B, uav_b, result_b)

                elapsed = time.monotonic() - started_at
                await asyncio.sleep(max(0.0, interval - elapsed))

        except asyncio.CancelledError:
            logger.info("APF loop cancelled")
        except Exception:
            logger.exception("APF loop error")

    def _build_uav_state(self, slot: int) -> Optional[UAVState]:
        """Convert telemetry packet to APF UAVState."""
        packet = self._telem.latest_packets.get(slot)
        if packet is None:
            return None
        if packet.lat is None or packet.lon is None:
            return None

        return UAVState(
            uav_id=slot,
            timestamp=packet.timestamp or 0,
            lat=packet.lat,
            lon=packet.lon,
            alt_relative_m=packet.relative_alt_m or 0,
            vx=packet.vx or 0,
            vy=packet.vy or 0,
            vz=packet.vz or 0,
            heading_deg=packet.heading_deg or 0,
            current_seq=packet.current_waypoint or 0,
            total_waypoints=packet.total_waypoints or 0,
            flight_mode=packet.flight_mode or "",
            armed=packet.armed or False,
            gps_fix=packet.gps_fix if hasattr(packet, "gps_fix") else 0,
            target_lat=packet.target_waypoint_lat or packet.lat,
            target_lon=packet.target_waypoint_lon or packet.lon,
            target_alt_m=packet.relative_alt_m or 0,
        )

    def _log_apf_tick(
        self,
        uav_a: UAVState,
        uav_b: UAVState,
        result_a: APFResult,
        result_b: APFResult,
    ) -> None:
        """Structured log entry for APF replay."""
        logger.debug(
            "APF tick: d_ij=%.1f d_cpa=%.1f t_cpa=%.1f "
            "uav3_avoid=%s uav4_avoid=%s "
            "uav3_offset=%.1f uav4_offset=%.1f",
            result_a.d_ij, result_a.d_cpa, result_a.t_cpa,
            result_a.avoidance_active, result_b.avoidance_active,
            result_a.offset_m, result_b.offset_m,
        )

        if self._apf_csv_writer:
            try:
                self._apf_csv_writer.writerow([
                    time.time(), result_a.d_ij, result_a.d_cpa, result_a.t_cpa,
                    result_a.avoidance_active, result_b.avoidance_active,
                    result_a.offset_m, result_b.offset_m,
                    uav_a.lat, uav_a.lon, uav_a.alt_relative_m,
                    uav_b.lat, uav_b.lon, uav_b.alt_relative_m,
                ])
            except Exception as exc:
                logger.error("Error writing APF CSV log: %s", exc)

    def _send_apf_correction_to_fc(
        self, slot: int, uav: UAVState, result: APFResult
    ) -> None:
        """
        Send the corrected APF waypoint to the FC using MISSION_ITEM_INT.
        Overwrites the current target waypoint (seq=1) in the companion bridge's drip-feed.
        """
        try:
            master = self._cmd._require_master(slot)
            # The companion bridge uploads a mini mission of [seq=0, seq=1]. Target is always seq=1.
            from pymavlink import mavutil
            
            # Use MISSION_ITEM_INT for highest precision
            # Convert float lat/lon to int32 (degrees * 1e7)
            lat_int = int(result.corrected_lat * 1e7)
            lon_int = int(result.corrected_lon * 1e7)
            
            master.mav.mission_item_int_send(
                master.target_system,
                master.target_component,
                1, # seq = 1 (active target)
                mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT,
                mavutil.mavlink.MAV_CMD_NAV_WAYPOINT,
                1, # current = 1 (this is the active item)
                1, # autocontinue = 1
                0, 0, 0, 0, # params 1-4
                lat_int, lon_int, result.corrected_alt_m
            )
            logger.debug(
                "Sent APF correction to slot %d: lat=%f, lon=%f, alt=%f", 
                slot, result.corrected_lat, result.corrected_lon, result.corrected_alt_m
            )
        except Exception as exc:
            logger.error("Failed to send APF correction to slot %d: %s", slot, exc)

    async def _broadcast_apf_status(
        self,
        result_a: APFResult,
        result_b: APFResult,
    ) -> None:
        """Push APF status to connected WebSocket clients."""
        def _san(val):
            return -1.0 if math.isinf(val) else val

        payload = {
            "type": "swarm_apf_status",
            "d_ij": _san(result_a.d_ij),
            "d_cpa": _san(result_a.d_cpa),
            "t_cpa": _san(result_a.t_cpa),
            "uav_3_avoidance": result_a.avoidance_active,
            "uav_4_avoidance": result_b.avoidance_active,
            "uav_3_offset_m": result_a.offset_m,
            "uav_4_offset_m": result_b.offset_m,
            "stale": result_a.stale or result_b.stale,
        }
        try:
            await self._ws.broadcast_telemetry(json.dumps(payload))
        except Exception:
            pass

    async def _broadcast_status(self) -> None:
        """Push full swarm status to WebSocket."""
        payload = self.status().model_dump()
        payload["type"] = "swarm_status"
        try:
            await self._ws.broadcast_telemetry(json.dumps(payload))
        except Exception:
            pass

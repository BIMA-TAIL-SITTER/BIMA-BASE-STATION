"""MAVLink command bridge with mission read/write protocol support."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Callable, Mapping, Optional, Sequence

os.environ["MAVLINK20"] = "1"

from pymavlink import mavutil, mavwp

from app.services.mavlink.connection import MavlinkTCPConnection
from app.services.mavlink.interfaces import (
    MissionItem,
    MissionTransferResult,
)
from app.services.mavlink.message_router import (
    MavlinkMessageRouter,
    MavlinkNotConnectedError,
)
from app.services.websocket.manager import WebSocketManager

logger = logging.getLogger(__name__)

ConnectionRegistry = Mapping[int, Optional[MavlinkTCPConnection]]
MissionCacheSink = Callable[[int, list[dict]], None]
MISSION_TYPE = mavutil.mavlink.MAV_MISSION_TYPE_MISSION
MISSION_ACCEPTED = mavutil.mavlink.MAV_MISSION_ACCEPTED


def _enum_label(enum_name: str, value: int, fallback: str) -> str:
    try:
        return mavutil.mavlink.enums[enum_name][value].name
    except (KeyError, AttributeError, TypeError):
        return f"{fallback}_{value}"


class MavlinkCommandBridge:
    """
    Execute mission transactions through the shared receive router.

    Non-mission command methods intentionally remain unimplemented in this
    task. Mission responses are matched with router futures, so this class
    never reads the native pymavlink connection.
    """

    def __init__(
        self,
        connections: ConnectionRegistry,
        message_router: MavlinkMessageRouter,
        ws_manager: WebSocketManager,
        mission_cache_sink: Optional[MissionCacheSink] = None,
    ) -> None:
        self._connections = connections
        self._router = message_router
        self._ws = ws_manager
        self._mission_cache_sink = mission_cache_sink

    async def arm(self, slot: int, force: bool = False) -> bool:
        """Arm one UAV and return whether its ACK was accepted."""
        master = self._require_master(slot)
        cmd_id = mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM

        def _is_arm_ack(msg: Any) -> bool:
            return (
                msg.get_type() == "COMMAND_ACK"
                and int(msg.command) == cmd_id
            )

        async with self._router.transaction_lock(slot):
            ack_future = self._router.expect(
                slot, {"COMMAND_ACK"}, _is_arm_ack,
            )
            master.mav.command_long_send(
                master.target_system,
                master.target_component,
                cmd_id,
                0,       # confirmation
                1,       # param1: 1 = arm
                21196 if force else 0,  # param2: 21196 = force
                0, 0, 0, 0, 0,
            )
            ack = await asyncio.wait_for(ack_future, timeout=5.0)

        result_code = int(ack.result)
        accepted = result_code == mavutil.mavlink.MAV_RESULT_ACCEPTED
        result_label = _enum_label("MAV_RESULT", result_code, "MAV_RESULT")
        logger.info(
            "ARM slot %d force=%s → %s (%d)",
            slot, force, result_label, result_code,
        )
        return accepted

    async def disarm(self, slot: int, force: bool = False) -> bool:
        """Disarm one UAV and return whether its ACK was accepted."""
        master = self._require_master(slot)
        cmd_id = mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM

        def _is_disarm_ack(msg: Any) -> bool:
            return (
                msg.get_type() == "COMMAND_ACK"
                and int(msg.command) == cmd_id
            )

        async with self._router.transaction_lock(slot):
            ack_future = self._router.expect(
                slot, {"COMMAND_ACK"}, _is_disarm_ack,
            )
            master.mav.command_long_send(
                master.target_system,
                master.target_component,
                cmd_id,
                0,       # confirmation
                0,       # param1: 0 = disarm
                21196 if force else 0,  # param2: 21196 = force
                0, 0, 0, 0, 0,
            )
            ack = await asyncio.wait_for(ack_future, timeout=5.0)

        result_code = int(ack.result)
        accepted = result_code == mavutil.mavlink.MAV_RESULT_ACCEPTED
        result_label = _enum_label("MAV_RESULT", result_code, "MAV_RESULT")
        logger.info(
            "DISARM slot %d force=%s → %s (%d)",
            slot, force, result_label, result_code,
        )
        return accepted

    async def set_mode(self, slot: int, mode: str) -> bool:
        """Set the requested autopilot flight mode for one UAV."""
        master = self._require_master(slot)

        # Resolve mode name → custom_mode number
        mode_map = master.mode_mapping()
        if not mode_map:
            raise ValueError("Could not retrieve mode mapping from autopilot")
        upper_mode = mode.upper()
        if upper_mode not in mode_map:
            raise ValueError(
                f"Unknown flight mode '{mode}'. "
                f"Available: {', '.join(sorted(mode_map.keys()))}"
            )
        custom_mode = mode_map[upper_mode]

        cmd_id = mavutil.mavlink.MAV_CMD_DO_SET_MODE

        def _is_mode_ack(msg: Any) -> bool:
            return (
                msg.get_type() == "COMMAND_ACK"
                and int(msg.command) == cmd_id
            )

        async with self._router.transaction_lock(slot):
            ack_future = self._router.expect(
                slot, {"COMMAND_ACK"}, _is_mode_ack,
            )
            master.mav.command_long_send(
                master.target_system,
                master.target_component,
                cmd_id,
                0,            # confirmation
                1,            # param1: MAV_MODE_FLAG_CUSTOM_MODE_ENABLED
                custom_mode,  # param2: custom_mode number
                0, 0, 0, 0, 0,
            )
            ack = await asyncio.wait_for(ack_future, timeout=5.0)

        result_code = int(ack.result)
        accepted = result_code == mavutil.mavlink.MAV_RESULT_ACCEPTED
        result_label = _enum_label("MAV_RESULT", result_code, "MAV_RESULT")
        logger.info(
            "SET_MODE slot %d mode=%s (%d) → %s (%d)",
            slot, mode, custom_mode, result_label, result_code,
        )
        return accepted

    async def return_to_launch(self, slot: int) -> bool:
        """Request return-to-launch for one UAV."""
        raise NotImplementedError("TODO: implement in control feature task")

    async def takeoff(self, slot: int, altitude_m: float) -> bool:
        """Request a copter takeoff to the target relative altitude."""
        raise NotImplementedError("TODO: implement in control feature task")

    async def goto(
        self,
        slot: int,
        latitude_deg: float,
        longitude_deg: float,
        altitude_m: float,
    ) -> bool:
        """Request guided movement to a global coordinate."""
        raise NotImplementedError("TODO: implement in control feature task")

    async def download_mission(self, slot: int) -> list[dict]:
        """Download the current mission using router-managed response futures."""
        master = self._require_master(slot)
        async with self._router.transaction_lock(slot):
            await self._emit(
                slot,
                {
                    "type": "mission_download_progress",
                    "status": "requesting",
                    "received": 0,
                    "total": 0,
                    "message": "Requesting mission list",
                },
            )
            count_future = self._router.expect(
                slot,
                {"MISSION_COUNT"},
                self._is_main_mission_message,
            )
            master.mav.mission_request_list_send(
                master.target_system,
                master.target_component,
                MISSION_TYPE,
            )
            count_message = await asyncio.wait_for(count_future, timeout=4.0)
            count = int(count_message.count)
            if count < 0 or count > 1000:
                raise RuntimeError(
                    f"Autopilot reported invalid mission count {count}",
                )

            waypoints: list[dict] = []
            for sequence in range(count):
                item_message = await self._request_mission_item(
                    slot,
                    master,
                    sequence,
                )
                waypoint = self._mission_message_to_dict(item_message)
                waypoints.append(waypoint)
                await self._emit(
                    slot,
                    {
                        "type": "mission_download_progress",
                        "status": "receiving",
                        "received": len(waypoints),
                        "total": count,
                        "message": (
                            f"Received mission item {len(waypoints)}/{count}"
                        ),
                    },
                )

            master.mav.mission_ack_send(
                master.target_system,
                master.target_component,
                MISSION_ACCEPTED,
                MISSION_TYPE,
            )

        if self._mission_cache_sink is not None:
            self._mission_cache_sink(slot, waypoints)
        await self._emit(
            slot,
            {
                "type": "mission_download_progress",
                "status": "complete",
                "received": len(waypoints),
                "total": len(waypoints),
                "message": f"Downloaded {len(waypoints)} mission items",
            },
        )
        return waypoints

    async def upload_mission(
        self,
        slot: int,
        items: Sequence[MissionItem],
    ) -> MissionTransferResult:
        """Upload mission items in the request, item, ACK sequence."""
        master = self._require_master(slot)
        loader = self._build_loader(master, items)
        total = loader.count()
        sent_sequences: set[int] = set()

        await self._emit_mission_upload(
            slot,
            status="starting",
            sent=0,
            total=total,
            message=f"Starting upload of {total} mission items",
        )

        try:
            async with self._router.transaction_lock(slot):
                response_future = self._router.expect(
                    slot,
                    {"MISSION_REQUEST_INT", "MISSION_REQUEST", "MISSION_ACK"},
                    self._is_main_mission_message,
                )
                master.mav.mission_count_send(
                    master.target_system,
                    master.target_component,
                    total,
                    MISSION_TYPE,
                )

                while True:
                    response = await asyncio.wait_for(
                        response_future,
                        timeout=5.0,
                    )
                    response_type = response.get_type()

                    if response_type == "MISSION_ACK":
                        result_code = int(response.type)
                        result_label = _enum_label(
                            "MAV_MISSION_RESULT",
                            result_code,
                            "MAV_MISSION_RESULT",
                        )
                        success = result_code == MISSION_ACCEPTED
                        message = (
                            f"Mission upload accepted ({result_label})"
                            if success
                            else f"Mission upload rejected ({result_label})"
                        )
                        result = MissionTransferResult(
                            success=success,
                            total=total,
                            transferred=len(sent_sequences),
                            result_code=result_code,
                            result_label=result_label,
                            message=message,
                        )
                        await self._emit_mission_upload(
                            slot,
                            status="complete" if success else "error",
                            sent=result.transferred,
                            total=total,
                            message=message,
                            result_code=result_code,
                            result_label=result_label,
                        )
                        if success and self._mission_cache_sink is not None:
                            self._mission_cache_sink(
                                slot,
                                [
                                    self._mission_item_to_dict(index, item)
                                    for index, item in enumerate(items)
                                ],
                            )
                        return result

                    sequence = int(response.seq)
                    if sequence < 0 or sequence >= total:
                        result_code = mavutil.mavlink.MAV_MISSION_INVALID_SEQUENCE
                        master.mav.mission_ack_send(
                            master.target_system,
                            master.target_component,
                            result_code,
                            MISSION_TYPE,
                        )
                        result_label = _enum_label(
                            "MAV_MISSION_RESULT",
                            result_code,
                            "MAV_MISSION_RESULT",
                        )
                        message = (
                            f"Autopilot requested invalid mission item "
                            f"{sequence}"
                        )
                        await self._emit_mission_upload(
                            slot,
                            status="error",
                            sent=len(sent_sequences),
                            total=total,
                            message=message,
                            result_code=result_code,
                            result_label=result_label,
                        )
                        return MissionTransferResult(
                            success=False,
                            total=total,
                            transferred=len(sent_sequences),
                            result_code=result_code,
                            result_label=result_label,
                            message=message,
                        )

                    response_future = self._router.expect(
                        slot,
                        {
                            "MISSION_REQUEST_INT",
                            "MISSION_REQUEST",
                            "MISSION_ACK",
                        },
                        self._is_main_mission_message,
                    )
                    if response_type == "MISSION_REQUEST_INT":
                        master.mav.send(loader.wp(sequence))
                    else:
                        self._send_legacy_item(
                            master,
                            sequence,
                            items[sequence],
                        )
                    sent_sequences.add(sequence)
                    await self._emit_mission_upload(
                        slot,
                        status="sending",
                        sent=len(sent_sequences),
                        total=total,
                        message=(
                            f"Sending mission item "
                            f"{len(sent_sequences)}/{total}"
                        ),
                    )

        except (asyncio.TimeoutError, MavlinkNotConnectedError) as exc:
            message = (
                "Mission upload timed out waiting for the autopilot"
                if isinstance(exc, asyncio.TimeoutError)
                else str(exc)
            )
            await self._emit_mission_upload(
                slot,
                status="error",
                sent=len(sent_sequences),
                total=total,
                message=message,
            )
            return MissionTransferResult(
                success=False,
                total=total,
                transferred=len(sent_sequences),
                result_code=None,
                result_label="TIMEOUT",
                message=message,
            )

    async def handle_command_ack(self, slot: int, message: Any) -> None:
        """Reserved for future non-mission command implementations."""
        raise NotImplementedError("TODO: implement in control feature task")

    async def _request_mission_item(
        self,
        slot: int,
        master: Any,
        sequence: int,
    ) -> Any:
        for attempt in range(3):
            item_future = self._router.expect(
                slot,
                {"MISSION_ITEM_INT", "MISSION_ITEM"},
                lambda message, expected=sequence: (
                    int(message.seq) == expected
                    and self._is_main_mission_message(message)
                ),
            )
            master.mav.mission_request_int_send(
                master.target_system,
                master.target_component,
                sequence,
                MISSION_TYPE,
            )
            try:
                return await asyncio.wait_for(item_future, timeout=2.0)
            except asyncio.TimeoutError:
                if attempt == 2:
                    raise
        raise asyncio.TimeoutError

    @staticmethod
    def _build_loader(
        master: Any,
        items: Sequence[MissionItem],
    ) -> mavwp.MAVWPLoader:
        loader = mavwp.MAVWPLoader()
        for sequence, item in enumerate(items):
            message = master.mav.mission_item_int_encode(
                master.target_system,
                master.target_component,
                sequence,
                int(item.frame),
                int(item.command),
                int(item.current),
                int(item.autocontinue),
                float(item.param1),
                float(item.param2),
                float(item.param3),
                float(item.param4),
                int(round(item.x * 1e7)),
                int(round(item.y * 1e7)),
                float(item.z),
                MISSION_TYPE,
            )
            loader.add(message)
        return loader

    @staticmethod
    def _send_legacy_item(
        master: Any,
        sequence: int,
        item: MissionItem,
    ) -> None:
        master.mav.mission_item_send(
            master.target_system,
            master.target_component,
            sequence,
            int(item.frame),
            int(item.command),
            int(item.current),
            int(item.autocontinue),
            float(item.param1),
            float(item.param2),
            float(item.param3),
            float(item.param4),
            float(item.x),
            float(item.y),
            float(item.z),
            MISSION_TYPE,
        )

    @staticmethod
    def _is_main_mission_message(message: Any) -> bool:
        return int(getattr(message, "mission_type", MISSION_TYPE)) == MISSION_TYPE

    @staticmethod
    def _mission_message_to_dict(message: Any) -> dict:
        is_int = message.get_type() == "MISSION_ITEM_INT"
        latitude = float(message.x) / 1e7 if is_int else float(message.x)
        longitude = float(message.y) / 1e7 if is_int else float(message.y)
        return {
            "seq": int(message.seq),
            "command": int(message.command),
            "command_name": _enum_label(
                "MAV_CMD",
                int(message.command),
                "MAV_CMD",
            ),
            "frame": int(message.frame),
            "frame_name": _enum_label(
                "MAV_FRAME",
                int(message.frame),
                "MAV_FRAME",
            ),
            "lat": latitude,
            "lon": longitude,
            "alt": float(message.z),
            "param1": float(message.param1),
            "param2": float(message.param2),
            "param3": float(message.param3),
            "param4": float(message.param4),
            "current": bool(message.current),
            "autocontinue": bool(message.autocontinue),
        }

    @staticmethod
    def _mission_item_to_dict(sequence: int, item: MissionItem) -> dict:
        return {
            "seq": sequence,
            "command": int(item.command),
            "command_name": _enum_label(
                "MAV_CMD",
                int(item.command),
                "MAV_CMD",
            ),
            "frame": int(item.frame),
            "frame_name": _enum_label(
                "MAV_FRAME",
                int(item.frame),
                "MAV_FRAME",
            ),
            "lat": float(item.x),
            "lon": float(item.y),
            "alt": float(item.z),
            "param1": float(item.param1),
            "param2": float(item.param2),
            "param3": float(item.param3),
            "param4": float(item.param4),
            "current": bool(item.current),
            "autocontinue": bool(item.autocontinue),
        }

    def _require_master(self, slot: int) -> Any:
        connection = self._router.get_connection(slot)
        master = getattr(connection, "master", None)
        if master is None:
            raise MavlinkNotConnectedError(
                f"UAV slot {slot} has no native pymavlink connection",
            )
        return master

    async def _emit_mission_upload(
        self,
        slot: int,
        *,
        status: str,
        sent: int,
        total: int,
        message: str,
        result_code: Optional[int] = None,
        result_label: Optional[str] = None,
    ) -> None:
        payload = {
            "type": "mission_upload_progress",
            "slot": slot,
            "status": status,
            "sent": sent,
            "total": total,
            "message": message,
            "result_code": result_code,
            "result_label": result_label,
        }
        await self._emit(slot, payload)

    async def _emit(self, slot: int, payload: dict) -> None:
        await self._ws.broadcast_control(slot, json.dumps(payload))

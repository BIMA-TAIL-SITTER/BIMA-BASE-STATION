"""Type-aware MAVLink parameter synchronization and write service."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import struct
import time
from typing import Any, Mapping, Optional

os.environ["MAVLINK20"] = "1"

from pymavlink import mavutil

from app.schemas.control import (
    ParamFetchProgress,
    ParamSetResponse,
    ParamSnapshot,
    ParamValue,
)
from app.services.mavlink.connection import MavlinkTCPConnection
from app.services.mavlink.message_router import (
    MavlinkMessageRouter,
    MavlinkNotConnectedError,
)
from app.services.websocket.manager import WebSocketManager

logger = logging.getLogger(__name__)

ConnectionRegistry = Mapping[int, Optional[MavlinkTCPConnection]]
# pymavlink 2.4.41 does not export these bitmask entries as module constants.
# Values come from the MAV_PROTOCOL_CAPABILITY enum in common.xml.
BYTEWISE_CAPABILITY = 16
C_CAST_CAPABILITY = 131072
ARDUPILOT_AUTOPILOT = mavutil.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA
REAL32 = mavutil.mavlink.MAV_PARAM_TYPE_REAL32

INTEGER_TYPES = {
    mavutil.mavlink.MAV_PARAM_TYPE_UINT8,
    mavutil.mavlink.MAV_PARAM_TYPE_INT8,
    mavutil.mavlink.MAV_PARAM_TYPE_UINT16,
    mavutil.mavlink.MAV_PARAM_TYPE_INT16,
    mavutil.mavlink.MAV_PARAM_TYPE_UINT32,
    mavutil.mavlink.MAV_PARAM_TYPE_INT32,
}

PACK_FORMATS = {
    mavutil.mavlink.MAV_PARAM_TYPE_UINT8: ">xxxB",
    mavutil.mavlink.MAV_PARAM_TYPE_INT8: ">xxxb",
    mavutil.mavlink.MAV_PARAM_TYPE_UINT16: ">xxH",
    mavutil.mavlink.MAV_PARAM_TYPE_INT16: ">xxh",
    mavutil.mavlink.MAV_PARAM_TYPE_UINT32: ">I",
    mavutil.mavlink.MAV_PARAM_TYPE_INT32: ">i",
}


def _param_type_name(param_type: int) -> str:
    try:
        return mavutil.mavlink.enums["MAV_PARAM_TYPE"][param_type].name
    except (KeyError, AttributeError, TypeError):
        return f"MAV_PARAM_TYPE_{param_type}"


def _normalize_param_id(raw_param_id: Any) -> str:
    if isinstance(raw_param_id, bytes):
        value = raw_param_id.decode("ascii", errors="ignore")
    else:
        value = str(raw_param_id)
    return value.split("\x00", 1)[0].strip().upper()


def encode_param_value(
    value: float,
    param_type: int,
    encoding: str,
) -> float:
    """
    Encode PARAM_SET values using pymavlink mavparm's bytewise algorithm.

    ArduPilot uses C-cast encoding, while PX4-style bytewise targets require
    the integer's raw bits to be reinterpreted as the message float field.
    """
    if encoding != "bytewise" or param_type == REAL32:
        return float(value)
    pack_format = PACK_FORMATS.get(param_type)
    if pack_format is None:
        raise ValueError(
            f"Bytewise PARAM_SET does not support {_param_type_name(param_type)}",
        )
    packed = struct.pack(pack_format, int(value))
    return struct.unpack(">f", packed)[0]


def decode_param_value(
    encoded_value: float,
    param_type: int,
    encoding: str,
) -> int | float:
    """Decode one PARAM_VALUE according to the target's advertised encoding."""
    if encoding == "bytewise" and param_type in PACK_FORMATS:
        packed = struct.pack(">f", float(encoded_value))
        return int(struct.unpack(PACK_FORMATS[param_type], packed)[0])
    if param_type in INTEGER_TYPES:
        return int(round(float(encoded_value)))
    return float(encoded_value)


class MavlinkParamBridge:
    """Synchronize and update parameter caches for the four UAV slots."""

    def __init__(
        self,
        connections: ConnectionRegistry,
        message_router: MavlinkMessageRouter,
        ws_manager: WebSocketManager,
    ) -> None:
        self._connections = connections
        self._router = message_router
        self._ws = ws_manager
        slots = list(connections)
        self._params_by_id: dict[int, dict[str, ParamValue]] = {
            slot: {} for slot in slots
        }
        self._params_by_index: dict[int, dict[int, ParamValue]] = {
            slot: {} for slot in slots
        }
        self._status: dict[int, str] = {
            slot: "idle" for slot in slots
        }
        self._total: dict[int, int] = {slot: 0 for slot in slots}
        self._messages: dict[int, Optional[str]] = {
            slot: None for slot in slots
        }
        self._encoding: dict[int, str] = {
            slot: "c_cast" for slot in slots
        }
        self._events: dict[int, asyncio.Event] = {
            slot: asyncio.Event() for slot in slots
        }
        self._tasks: dict[int, Optional[asyncio.Task[None]]] = {
            slot: None for slot in slots
        }
        self._last_progress_emit: dict[int, float] = {
            slot: 0.0 for slot in slots
        }
        self._broadcast_tasks: set[asyncio.Task[None]] = set()

    async def handle_message(self, slot: int, message: Any) -> None:
        """Consume routed capability, heartbeat, and PARAM_VALUE messages."""
        message_type = message.get_type()
        if message_type == "AUTOPILOT_VERSION":
            capabilities = int(getattr(message, "capabilities", 0))
            if capabilities & BYTEWISE_CAPABILITY:
                self._encoding[slot] = "bytewise"
            elif capabilities & C_CAST_CAPABILITY:
                self._encoding[slot] = "c_cast"
            return

        if message_type == "HEARTBEAT":
            if int(getattr(message, "autopilot", -1)) == ARDUPILOT_AUTOPILOT:
                self._encoding[slot] = "c_cast"
            return

        if message_type != "PARAM_VALUE":
            return

        param_id = _normalize_param_id(message.param_id)
        if not param_id:
            return
        param_type = int(message.param_type)
        param_index = int(message.param_index)
        param_count = max(0, int(message.param_count))
        decoded_value = decode_param_value(
            float(message.param_value),
            param_type,
            self._encoding[slot],
        )
        parameter = ParamValue(
            param_id=param_id,
            type=param_type,
            type_name=_param_type_name(param_type),
            value=decoded_value,
            index=param_index,
            count=param_count,
        )
        self._params_by_id[slot][param_id] = parameter
        if 0 <= param_index < param_count:
            self._params_by_index[slot][param_index] = parameter
        if param_count > self._total[slot]:
            self._total[slot] = param_count
        self._events[slot].set()

        if self._status[slot] in {"fetching", "retrying"}:
            now = time.monotonic()
            if (
                now - self._last_progress_emit[slot] >= 0.1
                or self._received_count(slot) >= self._total[slot] > 0
            ):
                self._last_progress_emit[slot] = now
                self._schedule_emit(
                    slot,
                    event_type="param_fetch_progress",
                )

    def start_fetch(self, slot: int) -> ParamSnapshot:
        """Start a full PARAM_REQUEST_LIST synchronization in the background."""
        self._require_master(slot)
        task = self._tasks.get(slot)
        if task is not None and not task.done():
            return self.snapshot(slot)
        self._tasks[slot] = asyncio.create_task(
            self._fetch_all(slot),
            name=f"param-fetch-slot-{slot}",
        )
        return self.snapshot(slot)

    def start_retry_missing(self, slot: int) -> ParamSnapshot:
        """Start one PARAM_REQUEST_READ transaction for every missing index."""
        self._require_master(slot)
        task = self._tasks.get(slot)
        if task is not None and not task.done():
            return self.snapshot(slot)
        if not self._missing_indices(slot):
            return self.snapshot(slot)
        self._tasks[slot] = asyncio.create_task(
            self._retry_missing(slot),
            name=f"param-retry-slot-{slot}",
        )
        return self.snapshot(slot)

    async def set_parameter(
        self,
        slot: int,
        param_id: str,
        value: float,
        requested_type: Optional[int] = None,
    ) -> ParamSetResponse:
        """Send PARAM_SET and confirm the result through a routed PARAM_VALUE."""
        if not math.isfinite(value):
            raise ValueError("Parameter value must be finite")
        master = self._require_master(slot)
        normalized_id = _normalize_param_id(param_id)
        if not normalized_id or len(normalized_id) > 16:
            raise ValueError("Parameter id must contain 1 to 16 ASCII characters")

        known = self._params_by_id[slot].get(normalized_id)
        param_type = (
            int(requested_type)
            if requested_type is not None
            else known.type if known is not None else REAL32
        )
        old_value = known.value if known is not None else None
        encoded_value = encode_param_value(
            value,
            param_type,
            self._encoding[slot],
        )

        async with self._router.transaction_lock(slot):
            acknowledgement = await self._set_and_confirm(
                slot,
                master,
                normalized_id,
                encoded_value,
                param_type,
            )

        confirmed_value = decode_param_value(
            float(acknowledgement.param_value),
            int(acknowledgement.param_type),
            self._encoding[slot],
        )
        confirmed_type = int(acknowledgement.param_type)
        confirmed = ParamValue(
            param_id=normalized_id,
            type=confirmed_type,
            type_name=_param_type_name(confirmed_type),
            value=confirmed_value,
            index=int(acknowledgement.param_index),
            count=max(0, int(acknowledgement.param_count)),
        )
        self._params_by_id[slot][normalized_id] = confirmed
        if 0 <= confirmed.index < confirmed.count:
            self._params_by_index[slot][confirmed.index] = confirmed

        requested_value: int | float = (
            int(round(value)) if param_type in INTEGER_TYPES else float(value)
        )
        success = self._values_match(requested_value, confirmed_value)
        response = ParamSetResponse(
            slot=slot,
            success=success,
            param_id=normalized_id,
            old_value=old_value,
            requested_value=requested_value,
            confirmed_value=confirmed_value,
            type=confirmed_type,
            type_name=_param_type_name(confirmed_type),
            message=(
                f"{normalized_id} confirmed at {confirmed_value}"
                if success
                else (
                    f"{normalized_id} returned {confirmed_value}, requested "
                    f"{requested_value}"
                )
            ),
        )
        await self._ws.broadcast_control(
            slot,
            json.dumps(
                {
                    **response.model_dump(exclude={"type"}),
                    "type": "param_set_result",
                    "param_type": response.type,
                },
            ),
        )
        return response

    def snapshot(self, slot: int) -> ParamSnapshot:
        """Return a stable, sorted copy of one slot's parameter cache."""
        if slot not in self._status:
            raise ValueError(f"Unknown UAV slot {slot}")
        parameters = sorted(
            self._params_by_id[slot].values(),
            key=lambda parameter: (
                parameter.index < 0,
                parameter.index,
                parameter.param_id,
            ),
        )
        return ParamSnapshot(
            slot=slot,
            status=self._status[slot],
            received=self._received_count(slot),
            total=self._total[slot],
            missing_indices=self._missing_indices(slot),
            parameters=parameters,
            message=self._messages[slot],
        )

    async def stop(self) -> None:
        """Cancel background parameter operations and pending broadcasts."""
        tasks = [
            task
            for task in self._tasks.values()
            if task is not None and not task.done()
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        broadcasts = list(self._broadcast_tasks)
        if broadcasts:
            await asyncio.gather(*broadcasts, return_exceptions=True)
        self._broadcast_tasks.clear()

    async def _fetch_all(self, slot: int) -> None:
        master = self._require_master(slot)
        self._params_by_id[slot].clear()
        self._params_by_index[slot].clear()
        self._total[slot] = 0
        self._status[slot] = "fetching"
        self._messages[slot] = "Requesting all parameters"
        self._events[slot].clear()
        await self._emit_progress(slot, "param_fetch_progress")

        try:
            async with self._router.transaction_lock(slot):
                received_any = False
                for request_attempt in range(2):
                    self._events[slot].clear()
                    master.mav.param_request_list_send(
                        master.target_system,
                        master.target_component,
                    )
                    while True:
                        if self._is_complete(slot):
                            break
                        try:
                            await asyncio.wait_for(
                                self._events[slot].wait(),
                                timeout=2.0,
                            )
                            received_any = True
                            self._events[slot].clear()
                        except asyncio.TimeoutError:
                            break
                    if self._is_complete(slot) or received_any:
                        break

            if self._is_complete(slot):
                self._status[slot] = "complete"
                self._messages[slot] = (
                    f"Received all {self._total[slot]} parameters"
                )
            elif self._params_by_id[slot]:
                missing_count = len(self._missing_indices(slot))
                self._status[slot] = "incomplete"
                self._messages[slot] = (
                    f"{missing_count} parameters were not received"
                )
            else:
                self._status[slot] = "error"
                self._messages[slot] = (
                    "No PARAM_VALUE messages were received"
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Parameter fetch failed for slot %d", slot)
            self._status[slot] = "error"
            self._messages[slot] = str(exc)
        finally:
            await self._emit_progress(slot, "param_fetch_complete")

    async def _retry_missing(self, slot: int) -> None:
        master = self._require_master(slot)
        self._status[slot] = "retrying"
        self._messages[slot] = "Retrying missing parameter indices"
        await self._emit_progress(slot, "param_fetch_progress")

        try:
            async with self._router.transaction_lock(slot):
                for index in list(self._missing_indices(slot)):
                    for attempt in range(2):
                        response_future = self._router.expect(
                            slot,
                            {"PARAM_VALUE"},
                            lambda message, expected=index: (
                                int(message.param_index) == expected
                            ),
                        )
                        master.mav.param_request_read_send(
                            master.target_system,
                            master.target_component,
                            b"",
                            index,
                        )
                        try:
                            await asyncio.wait_for(
                                response_future,
                                timeout=1.5,
                            )
                            break
                        except asyncio.TimeoutError:
                            if attempt == 1:
                                logger.warning(
                                    "Parameter index %d still missing on slot %d",
                                    index,
                                    slot,
                                )

            if self._is_complete(slot):
                self._status[slot] = "complete"
                self._messages[slot] = (
                    f"Received all {self._total[slot]} parameters"
                )
            else:
                missing_count = len(self._missing_indices(slot))
                self._status[slot] = "incomplete"
                self._messages[slot] = (
                    f"{missing_count} parameters are still missing"
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Parameter retry failed for slot %d", slot)
            self._status[slot] = "error"
            self._messages[slot] = str(exc)
        finally:
            await self._emit_progress(slot, "param_fetch_complete")

    async def _set_and_confirm(
        self,
        slot: int,
        master: Any,
        param_id: str,
        encoded_value: float,
        param_type: int,
    ) -> Any:
        predicate = lambda message: (
            _normalize_param_id(message.param_id) == param_id
        )
        acknowledgement_future = self._router.expect(
            slot,
            {"PARAM_VALUE"},
            predicate,
        )
        master.mav.param_set_send(
            master.target_system,
            master.target_component,
            param_id.encode("ascii"),
            encoded_value,
            param_type,
        )
        try:
            return await asyncio.wait_for(
                acknowledgement_future,
                timeout=2.0,
            )
        except asyncio.TimeoutError:
            read_future = self._router.expect(
                slot,
                {"PARAM_VALUE"},
                predicate,
            )
            master.mav.param_request_read_send(
                master.target_system,
                master.target_component,
                param_id.encode("ascii"),
                -1,
            )
            return await asyncio.wait_for(read_future, timeout=2.0)

    def _require_master(self, slot: int) -> Any:
        connection = self._router.get_connection(slot)
        master = getattr(connection, "master", None)
        if master is None:
            raise MavlinkNotConnectedError(
                f"UAV slot {slot} has no native pymavlink connection",
            )
        return master

    def _received_count(self, slot: int) -> int:
        total = self._total[slot]
        if total > 0:
            return len(self._params_by_index[slot])
        return len(self._params_by_id[slot])

    def _missing_indices(self, slot: int) -> list[int]:
        total = self._total[slot]
        if total <= 0:
            return []
        received = self._params_by_index[slot]
        return [index for index in range(total) if index not in received]

    def _is_complete(self, slot: int) -> bool:
        total = self._total[slot]
        return total > 0 and self._received_count(slot) >= total

    def _schedule_emit(self, slot: int, event_type: str) -> None:
        task = asyncio.create_task(self._emit_progress(slot, event_type))
        self._broadcast_tasks.add(task)
        task.add_done_callback(self._broadcast_tasks.discard)

    async def _emit_progress(self, slot: int, event_type: str) -> None:
        progress = ParamFetchProgress(
            slot=slot,
            status=self._status[slot],
            received=self._received_count(slot),
            total=self._total[slot],
            missing_indices=self._missing_indices(slot),
            message=self._messages[slot],
        )
        await self._ws.broadcast_control(
            slot,
            json.dumps(
                {
                    "type": event_type,
                    **progress.model_dump(),
                },
            ),
        )

    @staticmethod
    def _values_match(
        requested: int | float,
        confirmed: int | float,
    ) -> bool:
        if isinstance(requested, int):
            return int(confirmed) == requested
        tolerance = max(1e-5, abs(float(requested)) * 1e-6)
        return math.isclose(
            float(requested),
            float(confirmed),
            rel_tol=0.0,
            abs_tol=tolerance,
        )

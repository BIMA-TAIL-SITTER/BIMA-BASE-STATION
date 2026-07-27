"""Protocol-level tests for the mission and parameter control services."""

from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace
from typing import Any

from pymavlink import mavutil

from app.services.mavlink.command_bridge import MavlinkCommandBridge
from app.services.mavlink.interfaces import MissionItem
from app.services.mavlink.message_router import MavlinkMessageRouter
from app.services.mavlink.param_bridge import (
    MavlinkParamBridge,
    decode_param_value,
    encode_param_value,
)


class FakeMessage(SimpleNamespace):
    """Minimal pymavlink-like message used by the router tests."""

    def __init__(self, message_type: str, **values: Any) -> None:
        super().__init__(**values)
        self._message_type = message_type

    def get_type(self) -> str:
        return self._message_type

    def __copy__(self) -> "FakeMessage":
        values = {
            key: value
            for key, value in vars(self).items()
            if key != "_message_type"
        }
        return FakeMessage(self._message_type, **values)


class FakeWebSocketManager:
    def __init__(self) -> None:
        self.messages: list[tuple[int, dict[str, Any]]] = []

    async def broadcast_control(self, slot: int, message: str) -> None:
        self.messages.append((slot, json.loads(message)))


class FakeMav:
    def __init__(self, router: MavlinkMessageRouter) -> None:
        self.router = router
        self.sent_items: list[FakeMessage] = []
        self.counts: list[int] = []
        self.parameter_sets: list[tuple[bytes, float, int]] = []

    def _dispatch_soon(self, message: FakeMessage) -> None:
        loop = asyncio.get_running_loop()
        loop.call_soon(
            asyncio.create_task,
            self.router.dispatch(1, message),
        )

    def mission_item_int_encode(self, *values: Any) -> FakeMessage:
        return FakeMessage(
            "MISSION_ITEM_INT",
            target_system=values[0],
            target_component=values[1],
            seq=values[2],
            frame=values[3],
            command=values[4],
            current=values[5],
            autocontinue=values[6],
            param1=values[7],
            param2=values[8],
            param3=values[9],
            param4=values[10],
            x=values[11],
            y=values[12],
            z=values[13],
            mission_type=values[14],
        )

    def mission_count_send(
        self,
        _target_system: int,
        _target_component: int,
        count: int,
        mission_type: int,
    ) -> None:
        self.counts.append(count)
        if count:
            self._dispatch_soon(
                FakeMessage(
                    "MISSION_REQUEST_INT",
                    seq=0,
                    mission_type=mission_type,
                ),
            )
        else:
            self._dispatch_soon(
                FakeMessage(
                    "MISSION_ACK",
                    type=mavutil.mavlink.MAV_MISSION_ACCEPTED,
                    mission_type=mission_type,
                ),
            )

    def send(self, message: FakeMessage) -> None:
        self.sent_items.append(message)
        next_sequence = int(message.seq) + 1
        if next_sequence < self.counts[-1]:
            self._dispatch_soon(
                FakeMessage(
                    "MISSION_REQUEST_INT",
                    seq=next_sequence,
                    mission_type=message.mission_type,
                ),
            )
        else:
            self._dispatch_soon(
                FakeMessage(
                    "MISSION_ACK",
                    type=mavutil.mavlink.MAV_MISSION_ACCEPTED,
                    mission_type=message.mission_type,
                ),
            )

    def mission_ack_send(self, *_values: Any) -> None:
        return None

    def param_set_send(
        self,
        _target_system: int,
        _target_component: int,
        param_id: bytes,
        param_value: float,
        param_type: int,
    ) -> None:
        self.parameter_sets.append((param_id, param_value, param_type))
        self._dispatch_soon(
            FakeMessage(
                "PARAM_VALUE",
                param_id=param_id,
                param_value=param_value,
                param_type=param_type,
                param_index=0,
                param_count=1,
            ),
        )

    def param_request_read_send(self, *_values: Any) -> None:
        return None


class FakeConnection:
    def __init__(self, router: MavlinkMessageRouter | None = None) -> None:
        self.master = SimpleNamespace(
            target_system=1,
            target_component=1,
            mav=FakeMav(router) if router is not None else None,
        )

    def is_connected(self) -> bool:
        return True


class MessageRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_dispatch_resolves_matching_waiter_and_calls_handler(self) -> None:
        connection = FakeConnection()
        router = MavlinkMessageRouter({1: connection})
        handled: list[tuple[int, int]] = []

        async def handler(slot: int, message: FakeMessage) -> None:
            handled.append((slot, int(message.seq)))

        router.register_handler({"MISSION_REQUEST_INT"}, handler)
        future = router.expect(
            1,
            {"MISSION_REQUEST_INT"},
            lambda message: int(message.seq) == 2,
        )
        message = FakeMessage("MISSION_REQUEST_INT", seq=2)

        await router.dispatch(1, message)

        self.assertIs(await future, message)
        self.assertEqual(handled, [(1, 2)])


class MissionBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_upload_follows_count_request_item_ack_handshake(self) -> None:
        connections: dict[int, FakeConnection | None] = {1: None}
        router = MavlinkMessageRouter(connections)
        connection = FakeConnection(router)
        connections[1] = connection
        websocket = FakeWebSocketManager()
        cached: list[list[dict[str, Any]]] = []
        bridge = MavlinkCommandBridge(
            connections,
            router,
            websocket,  # type: ignore[arg-type]
            lambda _slot, items: cached.append(items),
        )
        items = [
            MissionItem(
                seq=0,
                frame=mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
                command=mavutil.mavlink.MAV_CMD_NAV_WAYPOINT,
                current=True,
                autocontinue=True,
                param1=0,
                param2=2,
                param3=0,
                param4=float("nan"),
                x=-6.2,
                y=106.8,
                z=20,
            ),
            MissionItem(
                seq=1,
                frame=mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
                command=mavutil.mavlink.MAV_CMD_NAV_LAND,
                current=False,
                autocontinue=True,
                param1=0,
                param2=0,
                param3=0,
                param4=0,
                x=-6.201,
                y=106.801,
                z=0,
            ),
        ]

        result = await bridge.upload_mission(1, items)

        self.assertTrue(result.success)
        self.assertEqual(result.transferred, 2)
        self.assertEqual(connection.master.mav.counts, [2])
        self.assertEqual(
            [message.seq for message in connection.master.mav.sent_items],
            [0, 1],
        )
        self.assertEqual(len(cached[0]), 2)
        self.assertEqual(websocket.messages[-1][1]["status"], "complete")


class ParameterBridgeTests(unittest.IsolatedAsyncioTestCase):
    def test_bytewise_integer_encoding_round_trips(self) -> None:
        cases = [
            (mavutil.mavlink.MAV_PARAM_TYPE_UINT8, 255),
            (mavutil.mavlink.MAV_PARAM_TYPE_INT8, -12),
            (mavutil.mavlink.MAV_PARAM_TYPE_UINT16, 60000),
            (mavutil.mavlink.MAV_PARAM_TYPE_INT16, -1234),
            (mavutil.mavlink.MAV_PARAM_TYPE_UINT32, 123456789),
            (mavutil.mavlink.MAV_PARAM_TYPE_INT32, -2147483648),
        ]
        for param_type, value in cases:
            with self.subTest(param_type=param_type):
                encoded = encode_param_value(value, param_type, "bytewise")
                decoded = decode_param_value(encoded, param_type, "bytewise")
                self.assertEqual(decoded, value)

    async def test_param_set_is_confirmed_and_ws_event_keeps_discriminator(
        self,
    ) -> None:
        connections: dict[int, FakeConnection | None] = {1: None}
        router = MavlinkMessageRouter(connections)
        connection = FakeConnection(router)
        connections[1] = connection
        websocket = FakeWebSocketManager()
        bridge = MavlinkParamBridge(
            connections,
            router,
            websocket,  # type: ignore[arg-type]
        )

        response = await bridge.set_parameter(
            1,
            "TEST_GAIN",
            3.5,
            mavutil.mavlink.MAV_PARAM_TYPE_REAL32,
        )

        self.assertTrue(response.success)
        self.assertEqual(response.confirmed_value, 3.5)
        event = websocket.messages[-1][1]
        self.assertEqual(event["type"], "param_set_result")
        self.assertEqual(
            event["param_type"],
            mavutil.mavlink.MAV_PARAM_TYPE_REAL32,
        )


if __name__ == "__main__":
    unittest.main()

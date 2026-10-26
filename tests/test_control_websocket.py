"""Exercise control WebSocket disconnects through Starlette's ASGI transport."""

import asyncio
import json
import unittest
from collections import deque
from unittest.mock import Mock, patch

from fastapi import WebSocket

from app.routers import control
from app.services.websocket.manager import WebSocketManager


class ControlWebSocketTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.manager = WebSocketManager()
        self.params = Mock()
        self.params.snapshot.return_value.model_dump.return_value = {"slot": 1}
        self.enterContext(patch.object(control, "ws_manager_instance", self.manager))
        self.enterContext(patch.object(control, "param_bridge_instance", self.params))

    def websocket(self, *, fail_snapshot=False, receive=None) -> WebSocket:
        events = deque([
            {"type": "websocket.connect"},
            {"type": "websocket.disconnect", "code": 1000},
        ])

        async def receive_event():
            return events.popleft()

        async def send_event(message):
            if message["type"] == "websocket.send":
                self.assertEqual(json.loads(message["text"])["type"], "param_snapshot")
                if fail_snapshot:
                    # Uvicorn ClientDisconnected is an OSError; Starlette maps it
                    # to WebSocketDisconnect(1006), as in the reported traceback.
                    raise OSError("browser disconnected without a close frame")

        return WebSocket({"type": "websocket"}, receive or receive_event, send_event)

    async def test_abrupt_disconnect_during_snapshot_does_not_leak_clients(self):
        other = self.websocket()
        await self.manager.connect_control(other, 1)

        for _ in range(3):
            await control.control_ws(self.websocket(fail_snapshot=True), 1)
            self.assertEqual(self.manager.client_count()["control"], {1: 1})
            self.assertEqual(self.manager._control_clients[1], {other})

        self.manager.disconnect_control(other, 1)
        self.assertFalse(self.manager.has_control_clients(1))

    async def test_normal_disconnect_after_snapshot_cleans_up(self):
        await control.control_ws(self.websocket(), 1)
        self.params.snapshot.assert_called_once_with(1)
        self.assertEqual(self.manager.client_count()["control"], {})

    async def test_snapshot_failure_still_cleans_up_and_propagates(self):
        self.params.snapshot.side_effect = ValueError("invalid snapshot")
        with self.assertRaisesRegex(ValueError, "invalid snapshot"):
            await control.control_ws(self.websocket(), 1)
        self.assertFalse(self.manager.has_control_clients(1))

    async def test_cancelled_handler_cleans_up(self):
        waiting = asyncio.Event()
        accepted = False

        async def receive():
            nonlocal accepted
            if not accepted:
                accepted = True
                return {"type": "websocket.connect"}
            waiting.set()
            await asyncio.Future()

        task = asyncio.create_task(control.control_ws(self.websocket(receive=receive), 1))
        try:
            await asyncio.wait_for(waiting.wait(), 1)
            self.assertTrue(self.manager.has_control_clients(1))
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertFalse(self.manager.has_control_clients(1))


if __name__ == "__main__":
    unittest.main()

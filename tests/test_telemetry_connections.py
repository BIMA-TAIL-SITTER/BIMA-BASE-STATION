"""Connection lifecycle regressions: duplicate requests must preserve live links."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from app.routers import telemetry
from app.services.mavlink.connection import MavlinkTCPConnection
from app.services.mavlink.telemetry_bridge import MavlinkTelemetryBridge


def fake_connection(ip: str = "100.95.70.29", port: int = 14550) -> Mock:
    connection = Mock(spec=MavlinkTCPConnection)
    connection.ip = ip
    connection.port = port
    connection.is_connected.return_value = True
    connection.connect = AsyncMock()
    connection.disconnect = AsyncMock()
    return connection


class TelemetryConnectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.bridge = MavlinkTelemetryBridge(Mock())
        self.connection = fake_connection()
        self.factory = self.enterContext(patch(
            "app.services.mavlink.telemetry_bridge.MavlinkTCPConnection",
            return_value=self.connection,
        ))

    async def test_duplicate_api_requests_preserve_active_swarm_link(self) -> None:
        self.bridge.connections[3] = self.connection
        self.enterContext(patch.object(
            telemetry, "telemetry_generator_instance", self.bridge,
        ))
        request = telemetry.ConnectRequest(slot=3, ip="100.95.70.29", port=14550)

        for _ in range(3):
            self.assertEqual(await telemetry.connect_mavlink(request), {"success": True})

        self.assertIs(self.bridge.connections[3], self.connection)
        self.assertTrue(self.bridge.get_status()[3])
        self.connection.disconnect.assert_not_awaited()
        self.factory.assert_not_called()

    async def test_duplicate_requests_during_handshake_share_connection(self) -> None:
        started, release = asyncio.Event(), asyncio.Event()

        async def handshake() -> None:
            started.set()
            await release.wait()

        self.connection.connect.side_effect = handshake
        first = asyncio.create_task(self.bridge.connect_slot(3, "100.95.70.29", 14550))
        await asyncio.wait_for(started.wait(), 1)
        duplicate = asyncio.create_task(self.bridge.connect_slot(3, "100.95.70.29", 14550))
        await asyncio.sleep(0)
        release.set()

        self.assertEqual(await asyncio.gather(first, duplicate), [True, True])
        self.factory.assert_called_once()
        self.connection.connect.assert_awaited_once()
        self.connection.disconnect.assert_not_awaited()

    async def test_disconnect_invalidates_inflight_and_queued_connects(self) -> None:
        started, release = asyncio.Event(), asyncio.Event()

        async def handshake() -> None:
            started.set()
            await release.wait()

        self.connection.connect.side_effect = handshake
        first = asyncio.create_task(self.bridge.connect_slot(3, "100.95.70.29", 14550))
        await asyncio.wait_for(started.wait(), 1)
        queued = asyncio.create_task(self.bridge.connect_slot(3, "100.95.70.29", 14550))
        await asyncio.sleep(0)
        await self.bridge.disconnect_slot(3)
        release.set()

        self.assertEqual(await asyncio.gather(first, queued), [False, False])
        self.assertIsNone(self.bridge.connections[3])
        self.connection.disconnect.assert_awaited_once()
        self.factory.assert_called_once()

    async def test_other_slots_connect_while_one_handshake_is_pending(self) -> None:
        started, release = asyncio.Event(), asyncio.Event()
        other = fake_connection(port=14560)
        self.factory.side_effect = [self.connection, other]

        async def handshake() -> None:
            started.set()
            await release.wait()

        self.connection.connect.side_effect = handshake
        first = asyncio.create_task(self.bridge.connect_slot(3, "100.95.70.29", 14550))
        await asyncio.wait_for(started.wait(), 1)
        try:
            self.assertTrue(await asyncio.wait_for(
                self.bridge.connect_slot(4, "100.95.70.29", 14560), 1,
            ))
            self.assertIs(self.bridge.connections[4], other)
        finally:
            release.set()
            await first

    async def test_explicit_reconnect_api_replaces_same_endpoint(self) -> None:
        old = fake_connection()
        self.bridge.connections[3] = old
        self.enterContext(patch.object(
            telemetry, "telemetry_generator_instance", self.bridge,
        ))
        result = await telemetry.connect_mavlink(telemetry.ConnectRequest(
            slot=3, ip="100.95.70.29", port=14550, force=True,
        ))

        self.assertEqual(result, {"success": True})
        old.disconnect.assert_awaited_once()
        self.connection.connect.assert_awaited_once()
        self.assertIs(self.bridge.connections[3], self.connection)

    async def test_changed_endpoint_replaces_connection(self) -> None:
        old = fake_connection(port=14560)
        self.bridge.connections[3] = old

        self.assertTrue(await self.bridge.connect_slot(3, "100.95.70.29", 14550))

        old.disconnect.assert_awaited_once()
        self.assertIs(self.bridge.connections[3], self.connection)

    async def test_failed_handshake_is_cleaned_up_and_can_be_retried(self) -> None:
        self.connection.connect.side_effect = TimeoutError("Heartbeat timeout")
        self.assertFalse(await self.bridge.connect_slot(3, "100.95.70.29", 14550))
        self.assertIsNone(self.bridge.connections[3])
        self.connection.disconnect.assert_awaited_once()

        self.connection.connect.side_effect = None
        self.assertTrue(await self.bridge.connect_slot(3, "100.95.70.29", 14550))
        self.assertIs(self.bridge.connections[3], self.connection)

    async def test_inactive_link_is_replaced_without_force(self) -> None:
        old = fake_connection()
        old.is_connected.return_value = False
        self.bridge.connections[3] = old

        self.assertTrue(await self.bridge.connect_slot(3, "100.95.70.29", 14550))
        old.disconnect.assert_awaited_once()
        self.assertIs(self.bridge.connections[3], self.connection)


if __name__ == "__main__":
    unittest.main()

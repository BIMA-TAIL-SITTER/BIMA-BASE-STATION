"""Page subscriptions must not own the backend's UDP receiver lifetime."""

import asyncio
import unittest
from collections import deque
from unittest.mock import Mock, patch

from fastapi import WebSocket

from app.routers import video
from app.services.video.manager import MultiStreamManager
from app.services.websocket.manager import WebSocketManager


class VideoLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.ws_manager = WebSocketManager()
        self.streams = MultiStreamManager(self.ws_manager)
        self.video_factory = self.enterContext(patch(
            "app.services.video.manager.VideoReceiver",
            side_effect=lambda **kwargs: Mock(latest_frame=None),
        ))
        self.telemetry_factory = self.enterContext(patch(
            "app.services.telemetry.udp_telemetry.UdpTelemetryReceiver",
            side_effect=lambda **kwargs: Mock(latest_data={}),
        ))
        self.enterContext(patch.object(video, "ws_manager_instance", self.ws_manager))
        self.enterContext(patch.object(video, "video_manager_instance", self.streams))

    async def asyncTearDown(self):
        tasks = list(self.streams._tasks.values())
        self.streams.stop_all()
        await asyncio.gather(*tasks, return_exceptions=True)

    def websocket(self, *, fail_accept=False):
        events = deque([
            {"type": "websocket.connect"},
            {"type": "websocket.disconnect", "code": 1000},
        ])

        async def receive():
            return events.popleft()

        async def send(message):
            if fail_accept:
                raise OSError("browser left during handshake")

        return WebSocket({"type": "websocket"}, receive, send)

    async def test_navigation_reuses_video_telemetry_and_broadcast_loop(self):
        await video.video_ws(self.websocket(), 5600, 5001)
        receiver = self.streams._receivers[5600]
        telemetry = self.streams._telemetry_receivers[5001]
        task = self.streams._tasks[5600]
        frame = object()
        receiver.latest_frame = frame
        telemetry.latest_data = {"detection": True, "_received_at": 123}

        for _ in range(3):
            # Leaving the page can last arbitrarily long, with no viewers.
            self.assertFalse(self.ws_manager.has_video_clients(5600))
            await video.video_ws(self.websocket(), 5600, 5001)
            self.assertIs(self.streams._receivers[5600], receiver)
            self.assertIs(receiver.latest_frame, frame)
            self.assertIs(self.streams._telemetry_receivers[5001], telemetry)
            self.assertIs(self.streams._tasks[5600], task)
            self.assertFalse(task.cancelling())

        self.video_factory.assert_called_once()
        self.telemetry_factory.assert_called_once()
        receiver.start.assert_called_once()
        telemetry.start.assert_called_once()
        receiver.stop.assert_not_called()
        telemetry.stop.assert_not_called()
        self.assertEqual(self.ws_manager.client_count()["video"], {})

    async def test_no_viewers_skips_encoding_and_broadcasting(self):
        await video.video_ws(self.websocket(), 5600, 5001)
        receiver = self.streams._receivers[5600]
        receiver.latest_frame = Mock()
        with patch.object(self.streams, "_encode_frame") as encode:
            await asyncio.sleep(0)
            encode.assert_not_called()
            receiver.latest_frame.copy.assert_not_called()
        receiver.stop.assert_not_called()

    async def test_leaving_one_page_preserves_other_viewer(self):
        other = self.websocket()
        await self.ws_manager.connect_video(other, 5600)
        await video.video_ws(self.websocket(), 5600, 5001)

        self.assertEqual(self.ws_manager._video_clients[5600], {other})
        self.streams._receivers[5600].stop.assert_not_called()
        self.ws_manager.disconnect_video(other, 5600)

    async def test_shutdown_releases_retained_receivers_and_shared_json_port(self):
        await video.video_ws(self.websocket(), 5600, 5001)
        await video.video_ws(self.websocket(), 5601, 5001)
        receivers = list(self.streams._receivers.values())
        telemetry = self.streams._telemetry_receivers[5001]
        tasks = list(self.streams._tasks.values())

        self.streams.stop_all()
        await asyncio.gather(*tasks, return_exceptions=True)

        for receiver in receivers:
            receiver.stop.assert_called_once()
        telemetry.stop.assert_called_once()
        self.assertEqual(self.streams._receivers, {})
        self.assertEqual(self.streams._telemetry_receivers, {})
        self.assertEqual(self.streams._tasks, {})
        self.assertEqual(self.streams._video_to_telemetry, {})

    async def test_failed_browser_handshake_does_not_start_receivers(self):
        await video.video_ws(self.websocket(fail_accept=True), 5600, 5001)
        self.video_factory.assert_not_called()
        self.telemetry_factory.assert_not_called()
        self.assertFalse(self.ws_manager.has_video_clients(5600))


if __name__ == "__main__":
    unittest.main()

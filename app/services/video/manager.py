"""
VideoManager
────────────
Reads the latest frame from :class:`VideoReceiver`, re-encodes it as JPEG,
and broadcasts the binary payload to all connected WebSocket clients via
:class:`WebSocketManager`.

If a :class:`YOLODetector` is attached, its latest detection result is
also broadcast — as a small JSON text message on the *same* /ws/video
channel, right after the binary JPEG frame it corresponds to. The
frontend (video.js) distinguishes the two by message type (Blob vs text)
and feeds JSON detections into `window.GS_setDetections`.

The broadcast loop is an asyncio coroutine and should be run as a Task.
"""

import asyncio
import json
import logging
import time
from typing import Optional

import cv2
import numpy as np

from app.services.video.receiver import VideoReceiver
from app.services.websocket.manager import WebSocketManager
from app.services.yolo.detector import YOLODetector
from app.config.settings import settings

logger = logging.getLogger(__name__)

# JPEG encode parameters passed to cv2.imencode
_ENCODE_PARAMS = [cv2.IMWRITE_JPEG_QUALITY, settings.VIDEO_JPEG_QUALITY]


class VideoManager:
    """
    Bridges the UDP receiver to the WebSocket layer.

    Only the *latest* available frame is sent; there is no queue, so
    under-performing clients receive a lower effective frame rate but
    never accumulate unbounded backlog.
    """

    def __init__(
        self,
        receiver: VideoReceiver,
        ws_manager: WebSocketManager,
        fps_limit: int = 30,
        detector: Optional[YOLODetector] = None,
    ) -> None:
        self._receiver = receiver
        self._ws = ws_manager
        self._fps_limit = max(1, fps_limit)
        self._frame_interval = 1.0 / self._fps_limit
        self._last_frame_hash: Optional[int] = None
        self._broadcast_count = 0
        self._detector = detector
        self._last_sent_detection_ts: float = 0.0
        logger.info(
            "VideoManager ready (fps_limit=%d, jpeg_quality=%d, yolo=%s)",
            fps_limit,
            settings.VIDEO_JPEG_QUALITY,
            "enabled" if (detector and detector.is_enabled) else "disabled",
        )

    # ─── Public ───────────────────────────────────────────────────

    async def broadcast_loop(self) -> None:
        """
        Coroutine that runs forever, sampling frames at up to `fps_limit` Hz
        and pushing them to all /ws/video clients as raw binary WebSocket messages.
        Detection results (if a detector is attached) ride along as JSON
        text messages on the same channel.
        """
        logger.info("VideoManager broadcast loop started")
        next_send = time.monotonic()

        while True:
            now = time.monotonic()
            sleep_time = next_send - now
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
            next_send = time.monotonic() + self._frame_interval

            # Only broadcast if there are clients
            if not self._ws.has_video_clients():
                await asyncio.sleep(0.1)
                continue

            frame = self._receiver.latest_frame
            if frame is None:
                # No signal — send a "no signal" placeholder at low rate
                if self._broadcast_count % (self._fps_limit * 2) == 0:
                    placeholder = self._make_no_signal_jpeg()
                    if placeholder is not None:
                        await self._ws.broadcast_video(placeholder)
                self._broadcast_count += 1
                continue

            jpeg_bytes = self._encode_frame(frame)
            if jpeg_bytes is None:
                continue

            await self._ws.broadcast_video(jpeg_bytes)
            self._broadcast_count += 1

            await self._maybe_broadcast_detections()

    def get_status(self) -> dict:
        stats = self._receiver.get_stats()
        status = {
            "receiving": self._receiver.is_receiving(),
            "fps": stats["fps"],
            "drops": stats["drop_count"],
            "frames": stats["frame_count"],
            "sender": stats["last_sender"],
            "avg_packet_bytes": stats["avg_packet_size"],
        }
        if self._detector is not None:
            status["yolo_enabled"] = self._detector.is_enabled
        return status

    # ─── Internals ────────────────────────────────────────────────

    async def _maybe_broadcast_detections(self) -> None:
        """Push the latest YOLO detection frame as a JSON text message,
        but only when it's a new result (avoid resending stale data)."""
        if self._detector is None or not self._detector.is_enabled:
            return

        det_frame = self._detector.latest_detections
        if det_frame is None or det_frame.timestamp <= self._last_sent_detection_ts:
            return

        self._last_sent_detection_ts = det_frame.timestamp
        try:
            payload = json.dumps(det_frame.to_dict())
            await self._ws.broadcast_video_text(payload)
        except Exception as exc:
            logger.debug("Detection broadcast error: %s", exc)

    @staticmethod
    def _encode_frame(frame: np.ndarray) -> Optional[bytes]:
        try:
            ok, buf = cv2.imencode(".jpg", frame, _ENCODE_PARAMS)
            if not ok:
                return None
            return buf.tobytes()
        except Exception as exc:
            logger.debug("JPEG encode error: %s", exc)
            return None

    @staticmethod
    def _make_no_signal_jpeg() -> Optional[bytes]:
        """Generate a small 320×180 'NO SIGNAL' placeholder frame."""
        try:
            img = np.full((180, 320, 3), (15, 10, 10), dtype=np.uint8)
            cx, cy = 160, 90
            cv2.putText(
                img,
                "NO SIGNAL",
                (cx - 70, cy + 6),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (80, 200, 80),
                1,
                cv2.LINE_AA,
            )
            ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 60])
            return buf.tobytes() if ok else None
        except Exception:
            return None
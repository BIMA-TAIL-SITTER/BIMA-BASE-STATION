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


class MultiStreamManager:
    """
    Manages multiple VideoReceivers dynamically based on WebSocket client connections.
    """

    def __init__(
        self,
        ws_manager: WebSocketManager,
        fps_limit: int = 30,
        detector: Optional[YOLODetector] = None,
    ) -> None:
        self._ws = ws_manager
        self._fps_limit = max(1, fps_limit)
        self._frame_interval = 1.0 / self._fps_limit
        self._detector = detector
        
        self._receivers: dict[int, VideoReceiver] = {}
        self._tasks: dict[int, asyncio.Task] = {}
        self._broadcast_counts: dict[int, int] = {}
        self._last_sent_detection_ts: dict[int, float] = {}
        
        self._telemetry_receivers = {} # Dict[int, UdpTelemetryReceiver]
        self._video_to_telemetry = {}  # video_port -> json_port
        
        logger.info(
            "MultiStreamManager ready (fps_limit=%d, jpeg_quality=%d, yolo=%s)",
            fps_limit,
            settings.VIDEO_JPEG_QUALITY,
            "enabled" if (detector and detector.is_enabled) else "disabled",
        )

    # ─── Public ───────────────────────────────────────────────────

    def ensure_stream(self, port: int, json_port: Optional[int] = None) -> None:
        """Ensure a VideoReceiver and broadcast loop are running for the given port."""
        if json_port:
            self._video_to_telemetry[port] = json_port
            if json_port not in self._telemetry_receivers:
                logger.info("Starting new UdpTelemetryReceiver for JSON port %d", json_port)
                from app.services.telemetry.udp_telemetry import UdpTelemetryReceiver
                telem_recv = UdpTelemetryReceiver(host="0.0.0.0", port=json_port)
                telem_recv.start()
                self._telemetry_receivers[json_port] = telem_recv

        if port not in self._receivers:
            logger.info("Starting new VideoReceiver for port %d", port)
            receiver = VideoReceiver(source="udp", host="0.0.0.0", port=port)
            receiver.start()
            self._receivers[port] = receiver
            self._broadcast_counts[port] = 0
            self._last_sent_detection_ts[port] = 0.0
            
            task = asyncio.create_task(self._broadcast_loop(port, receiver))
            self._tasks[port] = task

    def stop_stream(self, port: int) -> None:
        """Stop the VideoReceiver and broadcast loop for the given port."""
        if port in self._receivers:
            logger.info("Stopping VideoReceiver for port %d", port)
            self._receivers[port].stop()
            del self._receivers[port]
        if port in self._tasks:
            self._tasks[port].cancel()
            del self._tasks[port]
        if port in self._broadcast_counts:
            del self._broadcast_counts[port]
        if port in self._last_sent_detection_ts:
            del self._last_sent_detection_ts[port]
            
        json_port = self._video_to_telemetry.pop(port, None)
        if json_port and json_port in self._telemetry_receivers:
            if json_port not in self._video_to_telemetry.values():
                logger.info("Stopping UdpTelemetryReceiver for JSON port %d", json_port)
                self._telemetry_receivers[json_port].stop()
                del self._telemetry_receivers[json_port]

    def stop_all(self) -> None:
        """Stop all streams."""
        ports = list(self._receivers.keys())
        for port in ports:
            self.stop_stream(port)
        for t_recv in self._telemetry_receivers.values():
            t_recv.stop()
        self._telemetry_receivers.clear()
        self._video_to_telemetry.clear()

    async def _broadcast_loop(self, port: int, receiver: VideoReceiver) -> None:
        """
        Coroutine that runs forever for a specific port.
        """
        logger.info("Broadcast loop started for port %d", port)
        next_send = time.monotonic()

        while True:
            now = time.monotonic()
            sleep_time = next_send - now
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
            next_send = time.monotonic() + self._frame_interval

            # Only broadcast if there are clients for this port
            if not self._ws.has_video_clients(port):
                await asyncio.sleep(0.1)
                continue

            frame = receiver.latest_frame
            if frame is None:
                # No signal — send a "no signal" placeholder at low rate
                if self._broadcast_counts[port] % (self._fps_limit * 2) == 0:
                    placeholder = self._make_no_signal_jpeg()
                    if placeholder is not None:
                        await self._ws.broadcast_video(placeholder, port)
                self._broadcast_counts[port] += 1
                continue

            frame = frame.copy()
            
            # --- OVERLAY YOLO FROM UDP TELEMETRY ---
            json_port = self._video_to_telemetry.get(port)
            if json_port and json_port in self._telemetry_receivers:
                telem = self._telemetry_receivers[json_port].latest_data
                if telem and telem.get("detection"):
                    bbox = telem.get("bbox_px")
                    conf = telem.get("conf", 0.0)
                    if bbox and len(bbox) == 4:
                        x1, y1, x2, y2 = [int(v) for v in bbox]
                        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                        
                        text = f"Target {conf*100:.1f}%"
                        cv2.putText(frame, text, (x1, max(y1 - 10, 10)), 
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                
                # Crosshair
                h, w, _ = frame.shape
                cx, cy = w // 2, h // 2
                length = 15
                cv2.line(frame, (cx - length, cy), (cx + length, cy), (0, 0, 255), 2)
                cv2.line(frame, (cx, cy - length), (cx, cy + length), (0, 0, 255), 2)
            # ---------------------------------------

            jpeg_bytes = self._encode_frame(frame)
            if jpeg_bytes is None:
                continue
                
            if self._detector and self._detector.is_enabled:
                self._detector.enqueue(port, frame)

            await self._ws.broadcast_video(jpeg_bytes, port)
            self._broadcast_counts[port] += 1

            await self._maybe_broadcast_detections(port)

    def get_status(self) -> dict:
        status = {"streams": {}}
        for port, receiver in self._receivers.items():
            stats = receiver.get_stats()
            status["streams"][port] = {
                "receiving": receiver.is_receiving(),
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

    async def _maybe_broadcast_detections(self, port: int) -> None:
        """Push the latest UDP telemetry JSON as text message."""
        json_port = self._video_to_telemetry.get(port)
        if not json_port or json_port not in self._telemetry_receivers:
            return

        telem = self._telemetry_receivers[json_port].latest_data
        if not telem:
            return

        timestamp = telem.get("_received_at", 0)
        if timestamp <= self._last_sent_detection_ts.get(port, 0.0):
            return

        self._last_sent_detection_ts[port] = timestamp
        try:
            # We wrap it in a format video.js expects or just send it raw and update video.js
            # Adding type='telemetry' so video.js knows what to do
            telem['type'] = 'telemetry'
            payload = json.dumps(telem)
            await self._ws.broadcast_video_detections(payload, port)
        except Exception as exc:
            logger.debug("Detection broadcast error for port %d: %s", port, exc)

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
"""
VideoReceiver
─────────────
Listens on a UDP socket for JPEG video packets using the existing protocol,
OR captures frames from a local camera (webcam).

    UDP Packet layout:
        [0:4]  uint32 LE  — payload length in bytes
        [4:]   bytes      — raw JPEG data

Thread-safe.  Runs in a daemon thread.  Stores only the latest decoded frame.
All statistics are maintained atomically via threading.Lock.
"""

import logging
import socket
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Literal, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ReceiverStats:
    """Thread-safe counters for the receive loop."""

    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    frame_count: int = 0
    drop_count: int = 0
    byte_count: int = 0
    _fps_frames: int = 0
    _fps_ts: float = field(default_factory=time.monotonic, init=False)
    fps: float = 0.0
    avg_packet_size: float = 0.0
    last_sender: Optional[str] = None

    def record_frame(self, size: int, addr: Tuple[str, int]) -> None:
        with self._lock:
            self.frame_count += 1
            self.byte_count += size
            self._fps_frames += 1
            self.last_sender = f"{addr[0]}:{addr[1]}"
            now = time.monotonic()
            elapsed = now - self._fps_ts
            if elapsed >= 1.0:
                self.fps = self._fps_frames / elapsed
                self.avg_packet_size = (
                    self.byte_count / self.frame_count if self.frame_count else 0
                )
                self._fps_frames = 0
                self._fps_ts = now

    def record_drop(self) -> None:
        with self._lock:
            self.drop_count += 1

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "frame_count": self.frame_count,
                "drop_count": self.drop_count,
                "fps": round(self.fps, 1),
                "avg_packet_size": round(self.avg_packet_size),
                "last_sender": self.last_sender,
                "byte_count": self.byte_count,
            }


class VideoReceiver:
    """
    Video receiver that supports both UDP packets and local Camera input.

    The receiver runs in a background daemon thread.  The latest decoded
    NumPy BGR frame is always available via :py:attr:`latest_frame`.
    """

    def __init__(
        self, 
        source: Literal["udp", "camera"] = "camera",
        host: str = "0.0.0.0", 
        port: int = 5000,
        camera_index: int = 0
    ) -> None:
        self.source = source
        self._host = host
        self._port = port
        self._camera_index = camera_index
        
        self._sock: Optional[socket.socket] = None
        self._cap: Optional[cv2.VideoCapture] = None
        self._thread: Optional[threading.Thread] = None
        
        self._running = threading.Event()
        self._frame_lock = threading.Lock()
        self._latest_frame: Optional[np.ndarray] = None
        self.stats = ReceiverStats()
        
        logger.info("VideoReceiver created (Source: %s)", source.upper())

    # ─── Public API ───────────────────────────────────────────────

    def start(self) -> None:
        """Initialize the chosen source and start the receive thread."""
        if self._running.is_set():
            logger.warning("VideoReceiver already running")
            return

        self._running.set()

        if self.source == "udp":
            self._init_udp()
            target_func = self._receive_loop_udp
        elif self.source == "camera":
            self._init_camera()
            target_func = self._receive_loop_camera
        else:
            raise ValueError(f"Unknown source type: {self.source}")

        self._thread = threading.Thread(
            target=target_func,
            name=f"{self.source}-receiver",
            daemon=True,
        )
        self._thread.start()
        logger.info("VideoReceiver thread started for %s", self.source)

    def stop(self) -> None:
        """Signal the receive thread to exit and release resources."""
        self._running.clear()
        
        # Cleanup UDP Socket
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
            
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
            
        # Cleanup Camera (done after thread join to avoid race conditions)
        if self._cap:
            self._cap.release()
            self._cap = None
            
        logger.info("VideoReceiver stopped")

    @property
    def latest_frame(self) -> Optional[np.ndarray]:
        """Return the most-recently decoded BGR frame (or None)."""
        with self._frame_lock:
            return self._latest_frame

    def get_stats(self) -> dict:
        return self.stats.snapshot()

    def is_receiving(self) -> bool:
        return self._latest_frame is not None and self.stats.fps > 0

    # ─── Internals ────────────────────────────────────────────────

    def _init_udp(self) -> None:
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # Increase receive buffer to reduce kernel-level drops
            self._sock.setsockopt(
                socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024
            )
            self._sock.bind((self._host, self._port))
            self._sock.settimeout(0.5)
            logger.info("VideoReceiver listening on UDP port %d", self._port)
        except OSError as exc:
            logger.error("Failed to bind UDP socket on port %d: %s", self._port, exc)
            self._running.clear()
            raise

    def _init_camera(self) -> None:
        self._cap = cv2.VideoCapture(self._camera_index)
        if not self._cap.isOpened():
            logger.error("Failed to open camera index %d", self._camera_index)
            self._running.clear()
            raise RuntimeError(f"Cannot open camera {self._camera_index}")
        logger.info("VideoReceiver opened camera index %d", self._camera_index)

    def _receive_loop_camera(self) -> None:
        logger.debug("Camera capture loop started")
        addr_mock = ("localhost", self._camera_index)
        
        while self._running.is_set():
            ret, frame = self._cap.read()
            if not ret:
                self.stats.record_drop()
                time.sleep(0.01)  # Prevent busy loop if camera momentarily fails
                continue

            with self._frame_lock:
                self._latest_frame = frame

            # Record stats using the raw byte size of the numpy array
            self.stats.record_frame(frame.nbytes, addr_mock)

        logger.debug("Camera capture loop exited")

    def _receive_loop_udp(self) -> None:
        logger.debug("UDP receive loop started")
        while self._running.is_set():
            try:
                packet, addr = self._sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                # Socket was closed — exit gracefully
                break
            except Exception as exc:
                logger.warning("UDP recv error: %s", exc)
                continue

            # ── Pure JPEG packet (no header) ──────────────────────
            jpeg_data = packet
            declared_size = len(packet)

            # ── Decode JPEG ───────────────────────────────────────
            try:
                arr = np.frombuffer(jpeg_data, dtype=np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            except Exception as exc:
                logger.debug("Frame decode error: %s", exc)
                self.stats.record_drop()
                continue

            if frame is None:
                self.stats.record_drop()
                continue

            with self._frame_lock:
                self._latest_frame = frame

            self.stats.record_frame(declared_size, addr)

        logger.debug("UDP receive loop exited")
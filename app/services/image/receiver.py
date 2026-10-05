#!/usr/bin/env python3
"""
=============================================================================
UDP-Based Image Receiver | receiver.py
=============================================================================

Per-UAV fragmented-UDP listener for geotagged JPEG frames destined for the
stitching service, matching the wire protocol the edge-node sender already
uses (12-byte !III header: frame_id/total_chunks/chunk_idx, then the chunk
payload). Reassembled frames are written to disk as raw bytes -- never
through cv2.imdecode/imwrite, which would strip the EXIF
stitching_service/src/flight_metadata.py depends on.

Threading model matches VideoReceiver deliberately: daemon thread,
blocking socket + settimeout poll loop, threading.Lock for shared state --
no asyncio primitives here, the asyncio handoff happens only at the
hand-off point into the stitching router (see on_received).

=============================================================================
"""

import asyncio
import socket
import struct
import time
import threading
import logging
from typing import Callable, Awaitable, Optional
from pathlib import Path
from collections import defaultdict

logger = logging.getLogger(__name__)
onImageReceived = Callable[[str, Path], Awaitable[None]] 

_HEADER_FMT = "!III"
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)
_UDP_MAX_PACKET = 65535

# =============================================================================
# Frame Reassembler
# =============================================================================
class FrameReassembler:
    """
    Buffers UDP fragments per frame_id, returns the concatenated bytes
    once every chunk has arrived. Also tracks timeouts to drop stale frames.

    header format for each package:
    [4B frame_id][4B total_chunks][4B chunk_idx][data...]
    """

    def __init__(self, timeout_s: float = 5.0) -> None:
        self.timeout_s = timeout_s
        # {frame_id: {"chunks": {idx: bytes}, "total": int, "first_seen": float}}
        self._buffer: dict = defaultdict(
            lambda: {"chunks": {}, "total": 0, "first_seen": time.time()}
        )
        self._lock   = threading.Lock()
        self.total_seen = 0
        self.total_completed = 0
        self.total_dropped = 0

    def feed(self, packet: bytes) -> Optional[bytes]:
        """
        Insert the UDP package to assembler.
        Return bytes if its intact, None otherwise.
        """
        if len(packet) < _HEADER_SIZE:
            return None

        frame_id, total_chunks, chunk_idx = struct.unpack(
            _HEADER_FMT, packet[:_HEADER_SIZE]
        )
        payload = packet[_HEADER_SIZE:]

        with self._lock:
            is_new = frame_id not in self._buffer
            entry = self._buffer[frame_id]
            if is_new:
                self.total_seen += 1
            entry["total"] = total_chunks
            entry["chunks"][chunk_idx] = payload
            if not entry["first_seen"]:
                entry["first_seen"] = time.time()

            # Check if we have all chunks
            if len(entry["chunks"]) == total_chunks:
                # Reassemble in order
                assembled = b"".join(
                    entry["chunks"][i] for i in range(total_chunks)
                )
                self.total_completed += 1
                del self._buffer[frame_id]
                return assembled

        return None

    def cleanup_stale(self):
        """Dropping stale frames (incomplete chunks)."""
        now = time.time()
        with self._lock:
            stale = [
                fid for fid, entry in self._buffer.items()
                if now - entry.get("first_seen", now) > self.timeout_s
            ]
            for fid in stale:
                logger.warning(f"Frame {fid} timeout – dihapus (tidak lengkap)")
                del self._buffer[fid]
            self.total_dropped += len(stale)


# =============================================================================
# Image Receiver
# =============================================================================
class UAVImageReceiver:
    """
    Binds one UDP port, reassembles fragmented JPEG frames, writes each
    complete frame into `dest_folder`, and schedules `on_received(session_id,
    file_path)` onto the owning asyncio loop after each successful write
    """

    def __init__(self, port: int, session_id: str, save_dir: Path, on_received: onImageReceived, loop: asyncio.AbstractEventLoop, 
                 host: str = "0.0.0.0", cleanup_interval: float = 10.0) -> None:
        self._port             = port
        self._session_id       = session_id
        self._save_dir         = save_dir
        self._on_received      = on_received
        self._loop             = loop
        self._host             = host
        self._cleanup_interval = cleanup_interval
        
        self._assembler                          = FrameReassembler()
        self._sock: Optional[socket.socket]      = None
        self._thread: Optional[threading.Thread] = None
        
        self._running    = threading.Event()
        self.img_count   = 0
        self.total_bytes = 0

    def attach(self, session_id: str, save_dir: Path) -> None:
        """
        Swap destination without touching the socket - same port keeps listening
        Only where frames land changes, not the UDP stream itself
        low lisk race on in-flight frames accepted
        """
        self._session_id = session_id
        self._save_dir   = save_dir

    @property
    def current_session_id(self) -> str:
        return self._session_id


    def start(self) -> None:
        self._save_dir.mkdir(parents=True, exist_ok=True)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)  # 4MB buffer
        self._sock.bind((self._host, self._port))
        self._sock.settimeout(1.0)  # 1 second timeout for recv
        
        self._running.set()
        self._thread = threading.Thread(
            target=self._receive_loop,
            name=f"uav-image-receiver-{self._session_id}",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "UavImageReceiver listening on %s:%d for session %s",
            self._host, self._port, self._session_id,
        )

    def stop(self) -> None:
        self._running.clear()
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        logger.info(
            "UavImageReceiver on port %d stopped for session %s", 
            self._port, self._session_id)

    def _receive_loop(self) -> None:
        last_cleanup = time.monotonic()
        while self._running.is_set():
            try:
                packet, _addr = self._sock.recvfrom(_UDP_MAX_PACKET)
            except socket.timeout:
                continue
            except OSError:
                break
            except Exception:
                logger.exception("Image receive error on port %d", self._port)
                continue

            try:
                frame_bytes = self._assembler.feed(packet)
            except Exception:
                logger.exception("Frame reassembly error on port %d", self._port)
                continue

            if frame_bytes is not None:
                self._save_and_notify(frame_bytes)
            if time.monotonic() - last_cleanup > self._cleanup_interval:
                self._assembler.cleanup_stale()
                last_cleanup = time.monotonic()

    def _save_and_notify(self, jpeg_bytes: bytes) -> None:
        file_name = (
            f"{time.strftime('%Y%m%d_%H%M%S')}_"
            f"{int((time.time() % 1) * 1000):03d}_{self.img_count:05d}.jpg"
        )
        file_path = self._save_dir / file_name
        try:
            file_path.write_bytes(jpeg_bytes)
        except OSError:
            logger.exception("Failed writing reassembled frame to %s", file_path)
            return
        self.img_count += 1
        self.total_bytes += len(jpeg_bytes)
        logger.info(
            "Frame #%d saved: %s (%.1f KB)",
            self.img_count, file_name, len(jpeg_bytes) / 1024
        )
        # loop the same way app/routers/stitching.py's schedule_from_thread
        # does, rather than calling an async function directly.
        asyncio.run_coroutine_threadsafe(
            self._on_received(self._session_id, file_path),
            self._loop,
        )
    def get_stats(self) -> dict:
        asm = self._assembler
        loss_pct = (
            (asm.total_dropped / asm.total_seen * 100.0) if asm.total_seen else 0.0
        )
        return {
            "port": self._port,
            "session_id": self._session_id,
            "frames_saved": self.img_count,
            "total_bytes": self.total_bytes,
            "fragments_seen": asm.total_seen,
            "fragments_dropped": asm.total_dropped,
            "loss_pct": round(loss_pct, 1),
        }
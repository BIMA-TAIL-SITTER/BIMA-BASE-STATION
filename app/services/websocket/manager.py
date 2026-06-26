"""
WebSocketManager
────────────────
Central hub for all WebSocket connections.

Channels:
  /ws/video      — binary JPEG frames
  /ws/telemetry  — JSON telemetry packets
  /ws/system     — JSON system events / logs

Thread-safety: asyncio-safe (all operations run in the event loop).
"""

import asyncio
import logging
from typing import Set, Dict

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketManager:
    """Manages sets of connected WebSocket clients per channel."""

    def __init__(self) -> None:
        self._video_clients: Dict[int, Set[WebSocket]] = {}
        self._telemetry_clients: Set[WebSocket] = set()
        self._system_clients: Set[WebSocket] = set()

    # ─── Connection Management ────────────────────────────────────

    async def connect_video(self, ws: WebSocket, port: int) -> None:
        await ws.accept()
        if port not in self._video_clients:
            self._video_clients[port] = set()
        self._video_clients[port].add(ws)
        logger.info(
            "Video client connected to port %d — total for port: %d", 
            port, len(self._video_clients[port])
        )

    async def connect_telemetry(self, ws: WebSocket) -> None:
        await ws.accept()
        self._telemetry_clients.add(ws)
        logger.info(
            "Telemetry client connected — total: %d", len(self._telemetry_clients)
        )

    async def connect_system(self, ws: WebSocket) -> None:
        await ws.accept()
        self._system_clients.add(ws)
        logger.info(
            "System client connected — total: %d", len(self._system_clients)
        )

    def disconnect_video(self, ws: WebSocket, port: int) -> None:
        if port in self._video_clients:
            self._video_clients[port].discard(ws)
            logger.info(
                "Video client disconnected from port %d — remaining for port: %d", 
                port, len(self._video_clients[port])
            )
            # Cleanup empty sets
            if not self._video_clients[port]:
                del self._video_clients[port]

    def disconnect_telemetry(self, ws: WebSocket) -> None:
        self._telemetry_clients.discard(ws)
        logger.info(
            "Telemetry client disconnected — remaining: %d",
            len(self._telemetry_clients),
        )

    def disconnect_system(self, ws: WebSocket) -> None:
        self._system_clients.discard(ws)
        logger.info(
            "System client disconnected — remaining: %d", len(self._system_clients)
        )

    # ─── Broadcast Helpers ────────────────────────────────────────

    async def broadcast_video(self, data: bytes, port: int) -> None:
        """Send a raw binary JPEG payload to all video clients for a specific port."""
        if port in self._video_clients:
            await self._broadcast_bytes(self._video_clients[port], data)

    async def broadcast_telemetry(self, payload: str) -> None:
        """Send a JSON string to all telemetry clients."""
        await self._broadcast_text(self._telemetry_clients, payload)

    async def broadcast_system(self, payload: str) -> None:
        """Send a JSON string to all system-event clients."""
        await self._broadcast_text(self._system_clients, payload)

    async def broadcast_video_detections(self, payload: str, port: int) -> None:
        """Send JSON detections string to all video clients for a specific port."""
        if port in self._video_clients:
            await self._broadcast_text(self._video_clients[port], payload)

    # ─── Status ───────────────────────────────────────────────────

    def has_video_clients(self, port: int) -> bool:
        return port in self._video_clients and bool(self._video_clients[port])

    def has_telemetry_clients(self) -> bool:
        return bool(self._telemetry_clients)

    def has_system_clients(self) -> bool:
        return bool(self._system_clients)

    def client_count(self) -> dict:
        video_counts = {port: len(clients) for port, clients in self._video_clients.items()}
        return {
            "video": video_counts,
            "telemetry": len(self._telemetry_clients),
            "system": len(self._system_clients),
        }

    # ─── Internals ────────────────────────────────────────────────

    async def _broadcast_bytes(
        self, clients: Set[WebSocket], data: bytes
    ) -> None:
        """Broadcast binary data; remove any dead connections."""
        if not clients:
            return
        dead: list[WebSocket] = []
        tasks = []
        for ws in list(clients):
            tasks.append((ws, ws.send_bytes(data)))

        results = await asyncio.gather(
            *[t for _, t in tasks], return_exceptions=True
        )
        for (ws, _), result in zip(tasks, results):
            if isinstance(result, Exception):
                logger.debug("Video send failed (%s) — removing client", result)
                dead.append(ws)
        for ws in dead:
            clients.discard(ws)

    async def _broadcast_text(
        self, clients: Set[WebSocket], payload: str
    ) -> None:
        """Broadcast text data; remove any dead connections."""
        if not clients:
            return
        dead: list[WebSocket] = []
        tasks = [(ws, ws.send_text(payload)) for ws in list(clients)]

        results = await asyncio.gather(
            *[t for _, t in tasks], return_exceptions=True
        )
        for (ws, _), result in zip(tasks, results):
            if isinstance(result, Exception):
                logger.debug("Text send failed (%s) — removing client", result)
                dead.append(ws)
        for ws in dead:
            clients.discard(ws)

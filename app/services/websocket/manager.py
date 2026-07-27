"""Central asyncio-safe hub for all WebSocket channels."""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketManager:
    """Manage video, telemetry, system, and per-slot control clients."""

    def __init__(self) -> None:
        self._video_clients: Dict[int, Set[WebSocket]] = {}
        self._telemetry_clients: Set[WebSocket] = set()
        self._system_clients: Set[WebSocket] = set()
        self._control_clients: Dict[int, Set[WebSocket]] = {}

    async def connect_video(self, ws: WebSocket, port: int) -> None:
        await ws.accept()
        self._video_clients.setdefault(port, set()).add(ws)
        logger.info(
            "Video client connected to port %d - total: %d",
            port,
            len(self._video_clients[port]),
        )

    async def connect_telemetry(self, ws: WebSocket) -> None:
        await ws.accept()
        self._telemetry_clients.add(ws)
        logger.info(
            "Telemetry client connected - total: %d",
            len(self._telemetry_clients),
        )

    async def connect_system(self, ws: WebSocket) -> None:
        await ws.accept()
        self._system_clients.add(ws)
        logger.info(
            "System client connected - total: %d",
            len(self._system_clients),
        )

    async def connect_control(self, ws: WebSocket, slot: int) -> None:
        await ws.accept()
        self._control_clients.setdefault(slot, set()).add(ws)
        logger.info(
            "Control client connected to slot %d - total: %d",
            slot,
            len(self._control_clients[slot]),
        )

    def disconnect_video(self, ws: WebSocket, port: int) -> None:
        clients = self._video_clients.get(port)
        if clients is None:
            return
        clients.discard(ws)
        if not clients:
            del self._video_clients[port]
        logger.info(
            "Video client disconnected from port %d - remaining: %d",
            port,
            len(self._video_clients.get(port, set())),
        )

    def disconnect_telemetry(self, ws: WebSocket) -> None:
        self._telemetry_clients.discard(ws)
        logger.info(
            "Telemetry client disconnected - remaining: %d",
            len(self._telemetry_clients),
        )

    def disconnect_system(self, ws: WebSocket) -> None:
        self._system_clients.discard(ws)
        logger.info(
            "System client disconnected - remaining: %d",
            len(self._system_clients),
        )

    def disconnect_control(self, ws: WebSocket, slot: int) -> None:
        clients = self._control_clients.get(slot)
        if clients is None:
            return
        clients.discard(ws)
        if not clients:
            del self._control_clients[slot]
        logger.info(
            "Control client disconnected from slot %d - remaining: %d",
            slot,
            len(self._control_clients.get(slot, set())),
        )

    async def broadcast_video(self, data: bytes, port: int) -> None:
        """Send raw JPEG data to all viewers of one video port."""
        clients = self._video_clients.get(port)
        if clients:
            await self._broadcast_bytes(clients, data)

    async def broadcast_telemetry(self, payload: str) -> None:
        """Send JSON telemetry to all telemetry clients."""
        await self._broadcast_text(self._telemetry_clients, payload)

    async def broadcast_system(self, payload: str) -> None:
        """Send JSON system events to all system clients."""
        await self._broadcast_text(self._system_clients, payload)

    async def broadcast_video_detections(
        self,
        payload: str,
        port: int,
    ) -> None:
        """Send JSON detections to all viewers of one video port."""
        clients = self._video_clients.get(port)
        if clients:
            await self._broadcast_text(clients, payload)

    async def broadcast_control(self, slot: int, payload: str) -> None:
        """Send JSON mission or parameter events to one slot's clients."""
        clients = self._control_clients.get(slot)
        if clients:
            await self._broadcast_text(clients, payload)

    def has_video_clients(self, port: int) -> bool:
        return bool(self._video_clients.get(port))

    def has_telemetry_clients(self) -> bool:
        return bool(self._telemetry_clients)

    def has_system_clients(self) -> bool:
        return bool(self._system_clients)

    def has_control_clients(self, slot: int) -> bool:
        return bool(self._control_clients.get(slot))

    def client_count(self) -> dict:
        return {
            "video": {
                port: len(clients)
                for port, clients in self._video_clients.items()
            },
            "telemetry": len(self._telemetry_clients),
            "system": len(self._system_clients),
            "control": {
                slot: len(clients)
                for slot, clients in self._control_clients.items()
            },
        }

    async def _broadcast_bytes(
        self,
        clients: Set[WebSocket],
        data: bytes,
    ) -> None:
        if not clients:
            return
        tasks = [(ws, ws.send_bytes(data)) for ws in list(clients)]
        results = await asyncio.gather(
            *(task for _, task in tasks),
            return_exceptions=True,
        )
        for (ws, _), result in zip(tasks, results):
            if isinstance(result, Exception):
                logger.debug("Binary WebSocket send failed: %s", result)
                clients.discard(ws)

    async def _broadcast_text(
        self,
        clients: Set[WebSocket],
        payload: str,
    ) -> None:
        if not clients:
            return
        tasks = [(ws, ws.send_text(payload)) for ws in list(clients)]
        results = await asyncio.gather(
            *(task for _, task in tasks),
            return_exceptions=True,
        )
        for (ws, _), result in zip(tasks, results):
            if isinstance(result, Exception):
                logger.debug("Text WebSocket send failed: %s", result)
                clients.discard(ws)

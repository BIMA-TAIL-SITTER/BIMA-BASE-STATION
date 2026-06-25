"""
System Router
──────────────
Handles /ws/system WebSocket endpoint for log events and system messages,
plus /api/system/* REST endpoints.

ws_manager_instance is injected by main.py.
"""

import json
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["system"])

# Injected by main.py lifespan
ws_manager_instance = None

# In-memory ring buffer of the last 200 log events
_EVENT_BUFFER: list[dict] = []
_MAX_EVENTS = 200


def _add_event(level: str, message: str, category: str = "system") -> None:
    """Add an event to the buffer and broadcast to connected system clients."""
    event = {
        "ts": time.time(),
        "level": level,
        "category": category,
        "message": message,
    }
    _EVENT_BUFFER.append(event)
    if len(_EVENT_BUFFER) > _MAX_EVENTS:
        _EVENT_BUFFER.pop(0)
    # Broadcast is fire-and-forget (best effort, no await here)
    return event


@router.websocket("/system")
async def system_ws(websocket: WebSocket):
    """
    JSON WebSocket stream of system events, warnings, and log messages.

    On connection, the client receives the last 50 buffered events,
    then continues receiving live events.
    """
    if ws_manager_instance is None:
        await websocket.close(code=1011)
        return

    await ws_manager_instance.connect_system(websocket)

    # Replay recent history to newly connected client
    try:
        history = _EVENT_BUFFER[-50:]
        for event in history:
            await websocket.send_text(json.dumps(event))
    except Exception:
        pass

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("System WebSocket error: %s", exc)
    finally:
        ws_manager_instance.disconnect_system(websocket)


# ─── REST ─────────────────────────────────────────────────────────
api_router = APIRouter(prefix="/api/system", tags=["system"])


@api_router.get("/events")
async def get_events(limit: int = 100):
    """Return the last N system events."""
    safe_limit = min(limit, _MAX_EVENTS)
    return {"events": _EVENT_BUFFER[-safe_limit:]}


@api_router.get("/info")
async def system_info():
    """Return basic system information."""
    import platform
    import sys
    import os

    return {
        "python_version": sys.version,
        "platform": platform.system(),
        "platform_version": platform.version(),
        "pid": os.getpid(),
        "uptime_hint": "see /health",
    }

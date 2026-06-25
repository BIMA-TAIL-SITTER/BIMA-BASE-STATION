"""
Telemetry Router
─────────────────
Handles /ws/telemetry WebSocket endpoint and /api/telemetry REST endpoint.

telemetry_generator_instance and ws_manager_instance are injected by main.py.
"""

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["telemetry"])

# Injected by main.py lifespan
telemetry_generator_instance = None
ws_manager_instance = None


@router.websocket("/telemetry")
async def telemetry_ws(websocket: WebSocket):
    """
    JSON WebSocket stream of telemetry packets at 5 Hz.

    The client receives a JSON string on each message.
    """
    if ws_manager_instance is None:
        await websocket.close(code=1011)
        return

    await ws_manager_instance.connect_telemetry(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("Telemetry WebSocket error: %s", exc)
    finally:
        ws_manager_instance.disconnect_telemetry(websocket)


# ─── REST ─────────────────────────────────────────────────────────
api_router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])


@api_router.get("/latest")
async def latest_telemetry():
    """Return the most-recent telemetry snapshot as JSON."""
    if telemetry_generator_instance is None:
        return {"error": "not initialised"}
    data = telemetry_generator_instance.get_latest()
    if data is None:
        return {"error": "no data yet"}
    return data

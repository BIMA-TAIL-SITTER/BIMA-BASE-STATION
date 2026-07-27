"""
Telemetry Router
─────────────────
Handles /ws/telemetry WebSocket endpoint and /api/telemetry REST endpoint.

telemetry_generator_instance and ws_manager_instance are injected by main.py.
"""

import logging

from fastapi import APIRouter, Path, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["telemetry"])

# Injected by main.py lifespan
telemetry_generator_instance = None
ws_manager_instance = None
mission_manager_instance = None


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

@api_router.get("/sources")
async def get_sources():
    """Return available MAVLink IPs from settings."""
    from app.config.settings import settings
    return {
        "hosts": settings.mavlink_host_list,
        "default_port": settings.MAVLINK_DEFAULT_PORT
    }

class ConnectRequest(BaseModel):
    slot: int = Field(ge=1, le=4)
    ip: str
    port: int

@api_router.post("/connect")
async def connect_mavlink(req: ConnectRequest):
    if telemetry_generator_instance is None:
        return {"error": "not initialised"}
    success = await telemetry_generator_instance.connect_slot(req.slot, req.ip, req.port)
    return {"success": success}

class DisconnectRequest(BaseModel):
    slot: int = Field(ge=1, le=4)

@api_router.post("/disconnect")
async def disconnect_mavlink(req: DisconnectRequest):
    if telemetry_generator_instance is None:
        return {"error": "not initialised"}
    await telemetry_generator_instance.disconnect_slot(req.slot)
    return {"success": True}

@api_router.get("/status")
async def get_status():
    if telemetry_generator_instance is None:
        return {"error": "not initialised"}
    return telemetry_generator_instance.get_status()


@api_router.get("/udp_status")
async def get_udp_status():
    """Return latest JSON data received across all active UdpTelemetryReceivers (e.g. port 1001)."""
    from app.routers.video import video_manager_instance
    if video_manager_instance is None:
        return {"error": "video_manager not initialised"}
    status = {}
    for json_port, telem_recv in video_manager_instance._telemetry_receivers.items():
        status[str(json_port)] = {
            "listening": telem_recv._running.is_set(),
            "has_data": bool(telem_recv.latest_data),
            "latest_data": telem_recv.latest_data,
        }
    return {"udp_telemetry_receivers": status}


@api_router.get("/mission/{slot}")
async def get_mission(slot: int = Path(ge=1, le=4)):
    """Download and return the flight mission waypoints for the given slot."""
    if mission_manager_instance is None:
        return {"error": "mission manager not initialised"}
    try:
        waypoints = await mission_manager_instance.download_mission(slot)
        return {"waypoints": waypoints}
    except Exception as exc:
        logger.error("Mission download failed for slot %d: %s", slot, exc)
        return {"error": str(exc), "waypoints": []}


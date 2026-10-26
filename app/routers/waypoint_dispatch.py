"""Authenticated mission mutations and read-only live snapshots."""
import asyncio
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, WebSocket, WebSocketDisconnect

from app.config.settings import settings
from app.schemas.waypoint_dispatch import AppendWaypoints, DispatchAction, DispatchPlan, GeofenceUpdate
from app.services.mission.waypoint_scheduler import MissionConflict

router = APIRouter(tags=["swarm-dispatch"])
scheduler_instance = None


def require_scheduler():
    if scheduler_instance is None:
        raise HTTPException(503, "Swarm dispatcher not initialized")
    return scheduler_instance


def operator(authorization: str = Header(default="")):
    if not settings.SWARM_OPERATOR_TOKEN:
        raise HTTPException(503, "Configure SWARM_OPERATOR_TOKEN before mission operations")
    if not secrets.compare_digest(authorization, "Bearer " + settings.SWARM_OPERATOR_TOKEN):
        raise HTTPException(401, "Operator authorization required")


@router.get("/api/swarm/state")
async def state():
    return require_scheduler().snapshot()


@router.post("/api/swarm/missions", dependencies=[Depends(operator)])
async def save_mission(plan: DispatchPlan):
    try:
        return await require_scheduler().save_plan(plan.model_dump(mode="json"))
    except MissionConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.put("/api/swarm/geofence", dependencies=[Depends(operator)])
async def update_geofence(request: GeofenceUpdate):
    try:
        return await require_scheduler().update_geofence(request.center_lat, request.center_lon, request.radius_m)
    except MissionConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/api/swarm/missions/{mission_id}/append", dependencies=[Depends(operator)])
async def append_waypoints(mission_id: str, request: AppendWaypoints):
    try:
        return await require_scheduler().append_waypoints(
            mission_id, request.version, [w.model_dump(mode="json") for w in request.waypoints])
    except MissionConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/api/swarm/missions/{mission_id}/{action}", dependencies=[Depends(operator)])
async def mission_action(mission_id: str, action: str, request: DispatchAction):
    if action not in ("upload", "start", "hold", "resume", "abort"):
        raise HTTPException(404, "Unknown mission action")
    try:
        return await require_scheduler().action(mission_id, request.version, action, request.confirmation)
    except MissionConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.websocket("/ws/swarm")
async def swarm_ws(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(require_scheduler().snapshot())
            await asyncio.sleep(0.5)
    except (WebSocketDisconnect, RuntimeError, OSError):
        pass

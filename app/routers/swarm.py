"""Swarm orchestration API endpoints for dual-copter operations."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status

from app.schemas.swarm import (
    MissionBatchUploadRequest,
    MissionBatchUploadResponse,
    SwarmAbortRequest,
    SwarmAbortResponse,
    SwarmStartRequest,
    SwarmStartResponse,
    SwarmStatusResponse,
)
from app.schemas.swarm_mission import (
    SurveyParameters,
    MissionBatchResponse,
    GeneratedRoute
)
from app.schemas.control import MissionItem
from app.services.mavlink.interfaces import MissionItem as InternalMissionItem
from app.services.mission.survey_generator import generate_dual_survey_path_latlon, calculate_path_distance
from app.services.mission.conflict_checker import check_conflicts

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/swarm", tags=["swarm"])

# Injected by app.main during application startup.
swarm_coordinator_instance = None
dispatcher_instance = None


def _require_legacy():
    from app.config.settings import settings
    if not settings.SWARM_LEGACY_ENABLED:
        raise HTTPException(409, "Legacy swarm is disabled by configuration")
    if dispatcher_instance and dispatcher_instance.owns_copters():
        raise HTTPException(409, "Nearest-waypoint mission owns the copters; use dashboard mission controls")
    return _require_coordinator()


def _require_coordinator():
    if swarm_coordinator_instance is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Swarm coordinator is not initialized",
        )
    return swarm_coordinator_instance


# ─── Status ──────────────────────────────────────────────────────

@router.get("/status", response_model=SwarmStatusResponse)
async def get_swarm_status() -> SwarmStatusResponse:
    """Return full swarm status snapshot."""
    coord = _require_coordinator()
    return coord.status()


# ─── Batch Upload ─────────────────────────────────────────────────

@router.post("/upload", response_model=MissionBatchUploadResponse)
async def upload_batch(
    request: MissionBatchUploadRequest,
) -> MissionBatchUploadResponse:
    """
    Upload missions to both copters (UAV-3 and UAV-4) in one action.

    Each UAV's upload runs as an independent transaction with its own
    timeout, retry, and ACK tracking.
    """
    coord = _require_legacy()

    # Convert schema MissionItems to internal MissionItems
    items_a = [
        InternalMissionItem(
            seq=index,
            frame=item.frame,
            command=item.command,
            current=item.current,
            autocontinue=item.autocontinue,
            param1=item.param1,
            param2=item.param2,
            param3=item.param3,
            param4=item.param4,
            x=item.lat,
            y=item.lon,
            z=item.alt,
        )
        for index, item in enumerate(request.mission_uav_3)
    ]
    items_b = [
        InternalMissionItem(
            seq=index,
            frame=item.frame,
            command=item.command,
            current=item.current,
            autocontinue=item.autocontinue,
            param1=item.param1,
            param2=item.param2,
            param3=item.param3,
            param4=item.param4,
            x=item.lat,
            y=item.lon,
            z=item.alt,
        )
        for index, item in enumerate(request.mission_uav_4)
    ]

    return await coord.upload_batch(
        items_a=items_a, 
        items_b=items_b,
        ip_3=request.ip_3,
        port_3=request.port_3,
        ip_4=request.ip_4,
        port_4=request.port_4
    )


# ─── Coordinated Start ───────────────────────────────────────────

@router.post("/start", response_model=SwarmStartResponse)
async def start_mission(
    request: SwarmStartRequest,
) -> SwarmStartResponse:
    """
    Start coordinated mission on both copters.

    Requires:
      - Phase is READY_TO_START
      - All safety interlocks pass
      - confirmation == "CONFIRM_START" (double-click protection)
    """
    coord = _require_legacy()
    return await coord.start_mission(
        request.confirmation,
        ip_3=request.ip_3,
        port_3=request.port_3,
        ip_4=request.ip_4,
        port_4=request.port_4
    )


# ─── Abort / Emergency ───────────────────────────────────────────

@router.post("/abort", response_model=SwarmAbortResponse)
async def abort_mission(
    request: SwarmAbortRequest,
) -> SwarmAbortResponse:
    """
    Emergency abort for both copters.

    If airborne: switches to LOITER (never disarms in flight).
    If on ground: disarms.
    """
    coord = _require_legacy()
    return await coord.abort(request.reason)


# ─── Reset ────────────────────────────────────────────────────────

@router.post("/reset", response_model=SwarmStatusResponse)
async def reset_swarm() -> SwarmStatusResponse:
    """Reset swarm state to IDLE for a fresh operation cycle."""
    coord = _require_legacy()
    return await coord.reset()


# ─── Mission Auto-Generation ──────────────────────────────────────

@router.post("/generate", response_model=MissionBatchResponse)
async def generate_mission(params: SurveyParameters) -> MissionBatchResponse:
    """Generate boustrophedon mission paths for two UAVs from a single polygon."""
    try:
        path1, path2 = generate_dual_survey_path_latlon(
            latlon_polygon=params.area.vertices,
            spacing_m=params.lane_spacing_m,
            sweep_angle_deg=params.sweep_angle_deg,
            margin_m=params.safety_margin_m
        )
    except Exception as exc:
        logger.error(f"Survey generation failed: {exc}")
        return MissionBatchResponse(success=False, message="Generation failed", error=str(exc))
        
    def build_mission_items(path, alt):
        items = [
            MissionItem(
                seq=0,
                command=22, # MAV_CMD_NAV_TAKEOFF
                frame=3,
                lat=0.0,
                lon=0.0,
                alt=alt,
                autocontinue=True
            )
        ]
        for i, (lat, lon) in enumerate(path, start=1):
            items.append(MissionItem(
                seq=i,
                command=16, # MAV_CMD_NAV_WAYPOINT
                frame=3,
                lat=lat,
                lon=lon,
                alt=alt,
                autocontinue=True
            ))
        return items

    dist1 = calculate_path_distance(path1) if path1 else 0.0
    dist2 = calculate_path_distance(path2) if path2 else 0.0
    
    workload_diff = 0.0
    if dist1 + dist2 > 0:
        workload_diff = abs(dist1 - dist2) / ((dist1 + dist2) / 2) * 100.0
        
    route1 = GeneratedRoute(
        slot=3,
        mission_items=build_mission_items(path1, params.altitude_m),
        route_distance_m=dist1,
        estimated_time_s=dist1 / params.speed_ms if params.speed_ms > 0 else 0,
        lane_count=len(path1) // 2
    )
    
    route2 = GeneratedRoute(
        slot=4,
        mission_items=build_mission_items(path2, params.altitude_m),
        route_distance_m=dist2,
        estimated_time_s=dist2 / params.speed_ms if params.speed_ms > 0 else 0,
        lane_count=len(path2) // 2
    )
    
    conflicts = check_conflicts(path1, path2, params.speed_ms, params.min_horizontal_sep_m)
    min_sep = params.min_horizontal_sep_m
    if conflicts:
        min_sep = min(c.horizontal_sep_m for c in conflicts)
        
    return MissionBatchResponse(
        success=True,
        uav_3_route=route1,
        uav_4_route=route2,
        workload_difference_pct=workload_diff,
        predicted_conflicts=conflicts,
        min_horizontal_sep_m=min_sep,
        message="Generation successful." if not conflicts else f"Generated with {len(conflicts)} predicted conflicts!"
    )

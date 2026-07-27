"""Mission and parameter control API for the four UAV slots."""

from __future__ import annotations

from fastapi import (
    APIRouter,
    HTTPException,
    Path,
    WebSocket,
    WebSocketDisconnect,
    status,
)

from app.schemas.control import (
    ArmDisarmRequest,
    CommandAckResponse,
    GotoRequest,
    MissionUploadRequest,
    MissionUploadResponse,
    ModeChangeRequest,
    ParamSetRequest,
    ParamSetResponse,
    ParamSnapshot,
    TakeoffRequest,
)
from app.services.mavlink.interfaces import MissionItem
from app.services.mavlink.message_router import MavlinkNotConnectedError

router = APIRouter(prefix="/ws/control", tags=["control"])
api_router = APIRouter(prefix="/api/control", tags=["control"])

# Injected by app.main during application startup.
command_bridge_instance = None
param_bridge_instance = None
ws_manager_instance = None


def _service_unavailable(service_name: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=f"{service_name} is not initialized",
    )


@api_router.post("/{slot}/arm", response_model=CommandAckResponse)
async def arm(
    request: ArmDisarmRequest,
    slot: int = Path(ge=1, le=4),
) -> CommandAckResponse:
    """Reserved for the future arm-control implementation."""
    raise NotImplementedError("TODO: implement in control feature task")


@api_router.post("/{slot}/disarm", response_model=CommandAckResponse)
async def disarm(
    request: ArmDisarmRequest,
    slot: int = Path(ge=1, le=4),
) -> CommandAckResponse:
    """Reserved for the future disarm-control implementation."""
    raise NotImplementedError("TODO: implement in control feature task")


@api_router.post("/{slot}/mode", response_model=CommandAckResponse)
async def set_mode(
    request: ModeChangeRequest,
    slot: int = Path(ge=1, le=4),
) -> CommandAckResponse:
    """Reserved for the future flight-mode implementation."""
    raise NotImplementedError("TODO: implement in control feature task")


@api_router.post("/{slot}/rtl", response_model=CommandAckResponse)
async def return_to_launch(
    slot: int = Path(ge=1, le=4),
) -> CommandAckResponse:
    """Reserved for the future return-to-launch implementation."""
    raise NotImplementedError("TODO: implement in control feature task")


@api_router.post("/{slot}/takeoff", response_model=CommandAckResponse)
async def takeoff(
    request: TakeoffRequest,
    slot: int = Path(ge=1, le=4),
) -> CommandAckResponse:
    """Reserved for the future takeoff implementation."""
    raise NotImplementedError("TODO: implement in control feature task")


@api_router.post("/{slot}/goto", response_model=CommandAckResponse)
async def guided_goto(
    request: GotoRequest,
    slot: int = Path(ge=1, le=4),
) -> CommandAckResponse:
    """Reserved for the future guided/goto implementation."""
    raise NotImplementedError("TODO: implement in control feature task")


@api_router.post(
    "/{slot}/mission/upload",
    response_model=MissionUploadResponse,
)
async def upload_mission(
    request: MissionUploadRequest,
    slot: int = Path(ge=1, le=4),
) -> MissionUploadResponse:
    """Upload an ordered mission with the full MAVLink mission protocol."""
    if command_bridge_instance is None:
        raise _service_unavailable("MAVLink command bridge")

    items = [
        MissionItem(
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
        for index, item in enumerate(request.items)
    ]
    try:
        result = await command_bridge_instance.upload_mission(slot, items)
    except MavlinkNotConnectedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    return MissionUploadResponse(
        slot=slot,
        success=result.success,
        total=result.total,
        sent=result.transferred,
        result_code=result.result_code,
        result_label=result.result_label,
        message=result.message,
    )


@api_router.get("/{slot}/params", response_model=ParamSnapshot)
async def get_parameters(
    slot: int = Path(ge=1, le=4),
) -> ParamSnapshot:
    """Return the current parameter cache and synchronization status."""
    if param_bridge_instance is None:
        raise _service_unavailable("MAVLink parameter bridge")
    return param_bridge_instance.snapshot(slot)


@api_router.post(
    "/{slot}/params/fetch",
    response_model=ParamSnapshot,
    status_code=status.HTTP_202_ACCEPTED,
)
async def fetch_parameters(
    slot: int = Path(ge=1, le=4),
) -> ParamSnapshot:
    """Start a complete PARAM_REQUEST_LIST synchronization."""
    if param_bridge_instance is None:
        raise _service_unavailable("MAVLink parameter bridge")
    try:
        return param_bridge_instance.start_fetch(slot)
    except MavlinkNotConnectedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@api_router.post(
    "/{slot}/params/retry-missing",
    response_model=ParamSnapshot,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_missing_parameters(
    slot: int = Path(ge=1, le=4),
) -> ParamSnapshot:
    """Request every missing parameter index individually."""
    if param_bridge_instance is None:
        raise _service_unavailable("MAVLink parameter bridge")
    try:
        return param_bridge_instance.start_retry_missing(slot)
    except MavlinkNotConnectedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@api_router.post(
    "/{slot}/params/{param_id}",
    response_model=ParamSetResponse,
)
async def set_parameter(
    request: ParamSetRequest,
    slot: int = Path(ge=1, le=4),
    param_id: str = Path(min_length=1, max_length=16),
) -> ParamSetResponse:
    """Set one parameter and wait for its PARAM_VALUE confirmation."""
    if param_bridge_instance is None:
        raise _service_unavailable("MAVLink parameter bridge")
    try:
        return await param_bridge_instance.set_parameter(
            slot,
            param_id,
            request.value,
            request.param_type,
        )
    except MavlinkNotConnectedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Autopilot did not confirm the parameter value",
        ) from exc


@router.websocket("/{slot}")
async def control_ws(
    websocket: WebSocket,
    slot: int = Path(ge=1, le=4),
) -> None:
    """Stream mission and parameter progress for one UAV slot."""
    if ws_manager_instance is None:
        await websocket.close(code=1011)
        return

    await ws_manager_instance.connect_control(websocket, slot)
    if param_bridge_instance is not None:
        snapshot = param_bridge_instance.snapshot(slot)
        await websocket.send_json(
            {
                "type": "param_snapshot",
                **snapshot.model_dump(),
            },
        )
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        ws_manager_instance.disconnect_control(websocket, slot)

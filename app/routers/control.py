"""Mission and parameter control API for the four UAV slots."""

from __future__ import annotations

import json
import logging
from pathlib import Path as FilePath

from fastapi import (
    APIRouter,
    HTTPException,
    Path,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from pydantic import BaseModel, Field

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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws/control", tags=["control"])
api_router = APIRouter(prefix="/api/control", tags=["control"])

# Path to the shared mission config file read by standalone Python scripts
_MISSION_CONFIG_PATH = FilePath("mission_config.json")


class MissionConfigRequest(BaseModel):
    """Payload from Edit Connection modal for mission port configuration."""
    slot: int = Field(ge=1, le=4)
    raspi_ip: str
    mission_udp_port: int = Field(ge=1, le=65535)


@api_router.get("/mission-config")
async def get_mission_config():
    """Return current mission_config.json contents."""
    try:
        return json.loads(_MISSION_CONFIG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"error": "mission_config.json not found"}
    except json.JSONDecodeError:
        return {"error": "mission_config.json is malformed"}


@api_router.post("/mission-config")
async def save_mission_config(req: MissionConfigRequest):
    """
    Save mission port config to mission_config.json.

    This file is read by the standalone gcs_mission_client.py 
    so it picks up port changes made from the web UI Edit Connection page.
    """
    # Read existing config or create defaults
    try:
        config = json.loads(_MISSION_CONFIG_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        config = {
            "gcs": {},
        }

    # Update GCS section
    config["gcs"] = {
        "raspi_ip": req.raspi_ip,
        "mission_udp_port": req.mission_udp_port,
    }

    # Write back
    _MISSION_CONFIG_PATH.write_text(
        json.dumps(config, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    logger.info(
        "Mission config updated: slot=%d ip=%s port=%d",
        req.slot, req.raspi_ip, req.mission_udp_port,
    )
    return {"success": True, "config": config}

import subprocess
import os
import sys
import asyncio

class CompanionActionRequest(BaseModel):
    ip: str
    port: int

def run_subprocess_and_stream(cmd, cwd):
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=cwd,
        env=env,
        text=True,
        bufsize=1
    )
    
    output = []
    for line in process.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
        output.append(line)
        
    process.wait()
    return process.returncode, "".join(output)

@api_router.post("/companion/upload")
async def companion_upload(req: CompanionActionRequest):
    """Trigger gcs_mission_client.py to upload mission via UDP for specific IP and port."""
    try:
        script_path = FilePath("mission_scripts/gcs_mission_client.py").absolute()
        print(f"\n[*] === Menjalankan Upload Mission (IP: {req.ip}, Port: {req.port}) ===", flush=True)
        
        loop = asyncio.get_running_loop()
        cmd = [sys.executable, str(script_path), "--action", "upload", "--ip", req.ip, "--port", str(req.port)]
        returncode, full_output = await loop.run_in_executor(
            None, run_subprocess_and_stream, cmd, str(script_path.parent)
        )
        
        print("[*] ==============================================================\n", flush=True)
        
        if returncode == 0:
            return {"success": True, "message": "Mission uploaded successfully.", "output": full_output}
        else:
            return {"success": False, "message": "Upload failed.", "output": full_output}
    except Exception as e:
        return {"success": False, "message": f"Error: {str(e)}"}

@api_router.post("/companion/start")
async def companion_start(req: CompanionActionRequest):
    """Trigger gcs_mission_client.py to start mission via UDP for specific IP and port."""
    try:
        script_path = FilePath("mission_scripts/gcs_mission_client.py").absolute()
        print(f"\n[*] === Menjalankan Start Mission (IP: {req.ip}, Port: {req.port}) ===", flush=True)
        
        loop = asyncio.get_running_loop()
        cmd = [sys.executable, str(script_path), "--action", "start", "--ip", req.ip, "--port", str(req.port)]
        returncode, full_output = await loop.run_in_executor(
            None, run_subprocess_and_stream, cmd, str(script_path.parent)
        )
        
        print("[*] ==============================================================\n", flush=True)
        
        if returncode == 0:
            return {"success": True, "message": "Mission started successfully.", "output": full_output}
        else:
            return {"success": False, "message": "Start failed.", "output": full_output}
    except Exception as e:
        return {"success": False, "message": f"Error: {str(e)}"}

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
    """Send MAV_CMD_COMPONENT_ARM_DISARM (arm) to one UAV."""
    if command_bridge_instance is None:
        raise _service_unavailable("MAVLink command bridge")

    try:
        accepted = await command_bridge_instance.arm(
            slot, force=bool(request.force),
        )
    except MavlinkNotConnectedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Autopilot did not acknowledge the ARM command",
        ) from exc

    from pymavlink import mavutil as _mav
    cmd_id = _mav.mavlink.MAV_CMD_COMPONENT_ARM_DISARM
    result_code = 0 if accepted else 4  # ACCEPTED or FAILED
    result_label = "MAV_RESULT_ACCEPTED" if accepted else "MAV_RESULT_FAILED"

    return CommandAckResponse(
        slot=slot,
        command_id=cmd_id,
        result_code=result_code,
        result_label=result_label,
        accepted=accepted,
        message=f"ARM {'accepted' if accepted else 'rejected'} (force={request.force})",
    )


@api_router.post("/{slot}/disarm", response_model=CommandAckResponse)
async def disarm(
    request: ArmDisarmRequest,
    slot: int = Path(ge=1, le=4),
) -> CommandAckResponse:
    """Send MAV_CMD_COMPONENT_ARM_DISARM (disarm) to one UAV."""
    if command_bridge_instance is None:
        raise _service_unavailable("MAVLink command bridge")

    try:
        accepted = await command_bridge_instance.disarm(
            slot, force=bool(request.force),
        )
    except MavlinkNotConnectedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Autopilot did not acknowledge the DISARM command",
        ) from exc

    from pymavlink import mavutil as _mav
    cmd_id = _mav.mavlink.MAV_CMD_COMPONENT_ARM_DISARM
    result_code = 0 if accepted else 4  # ACCEPTED or FAILED
    result_label = "MAV_RESULT_ACCEPTED" if accepted else "MAV_RESULT_FAILED"

    return CommandAckResponse(
        slot=slot,
        command_id=cmd_id,
        result_code=result_code,
        result_label=result_label,
        accepted=accepted,
        message=f"DISARM {'accepted' if accepted else 'rejected'} (force={request.force})",
    )


@api_router.post("/{slot}/mode", response_model=CommandAckResponse)
async def set_mode(
    request: ModeChangeRequest,
    slot: int = Path(ge=1, le=4),
) -> CommandAckResponse:
    """Send MAV_CMD_DO_SET_MODE to one UAV."""
    if command_bridge_instance is None:
        raise _service_unavailable("MAVLink command bridge")

    try:
        accepted = await command_bridge_instance.set_mode(
            slot, request.mode,
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
            detail="Autopilot did not acknowledge the SET_MODE command",
        ) from exc

    from pymavlink import mavutil as _mav
    cmd_id = _mav.mavlink.MAV_CMD_DO_SET_MODE
    result_code = 0 if accepted else 4
    result_label = "MAV_RESULT_ACCEPTED" if accepted else "MAV_RESULT_FAILED"

    return CommandAckResponse(
        slot=slot,
        command_id=cmd_id,
        result_code=result_code,
        result_label=result_label,
        accepted=accepted,
        message=f"SET_MODE {request.mode} {'accepted' if accepted else 'rejected'}",
    )


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

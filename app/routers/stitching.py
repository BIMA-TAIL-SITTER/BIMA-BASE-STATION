"""Integrated live image stitching routes for the main Ground Station backend."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import re
import sys
import threading
import time
from typing import Any, Coroutine, Dict, List

import cv2
from fastapi import APIRouter, File, HTTPException, UploadFile, WebSocket
from fastapi.responses import FileResponse
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


REPO_ROOT = Path(__file__).resolve().parents[2]
STITCHING_ROOT = REPO_ROOT / "stitching_service"
SESSIONS_ROOT = Path(
    os.getenv("STITCH_SESSIONS_DIR", str(STITCHING_ROOT / "sessions"))
).expanduser().resolve()
DEFAULT_AUTO_THRESHOLD = max(1, int(os.getenv("STITCH_AUTO_THRESHOLD", "5")))
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
INTERMEDIATE_PATTERN = re.compile(r"^intermediateResult_[0-9]+\.png$")
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}

# VISION-LIVESTITCH keeps package imports and src-local imports mixed. The
# integrated backend still loads the same engine, but it now runs inside the
# main FastAPI process.
sys.path.insert(0, str(STITCHING_ROOT))
sys.path.insert(0, str(STITCHING_ROOT / "src"))
from src import Combiner  # noqa: E402
from src import utilities as util  # noqa: E402


cv2.ocl.setUseOpenCL(False)

router = APIRouter(prefix="/ws/stitching", tags=["stitching"])
api_router = APIRouter(prefix="/api/stitching", tags=["stitching"])

# Injected by app.main during lifespan startup.
video_manager_instance: Any | None = None


class StitchConfig(BaseModel):
    sessionId: str = Field(min_length=1, max_length=64)
    auto_stitch_threshold: int = Field(
        default=DEFAULT_AUTO_THRESHOLD,
        ge=1,
        le=10_000,
    )
    auto_stitch_enabled: bool = False
    folder_monitoring_enabled: bool = False
    output_name: str = "finalResult.png"

    @field_validator("sessionId")
    @classmethod
    def validate_session_id(cls, value: str) -> str:
        if not SESSION_ID_PATTERN.fullmatch(value):
            raise ValueError(
                "sessionId must use 1-64 letters, numbers, underscores, or hyphens"
            )
        return value

    @field_validator("output_name")
    @classmethod
    def validate_output_name(cls, value: str) -> str:
        if Path(value).name != value or Path(value).suffix.lower() != ".png":
            raise ValueError("output_name must be a PNG filename without a path")
        return value


class StreamCaptureRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    stream_port: int = Field(alias="streamPort", ge=1, le=65_535)
    json_port: int | None = Field(default=None, alias="jsonPort", ge=1, le=65_535)
    uav_id: int | None = Field(default=None, alias="uavId", ge=1, le=4)
    jpeg_quality: int = Field(default=95, alias="jpegQuality", ge=1, le=100)


class StitchingSession:
    def __init__(self, session_id: str, config: StitchConfig):
        self.session_id = session_id
        self.config = config
        self.image_folder = SESSIONS_ROOT / session_id / "images"
        self.output_folder = SESSIONS_ROOT / session_id / "output"
        self.image_folder.mkdir(parents=True, exist_ok=True)
        self.output_folder.mkdir(parents=True, exist_ok=True)

        self.image_count = self.count_images()
        self.is_stitching = False
        self.ws_clients: set[WebSocket] = set()
        self.last_stitch_count = 0
        self.observer: Observer | None = None
        self._state_lock = threading.Lock()

    def count_images(self) -> int:
        return sum(
            1
            for path in self.image_folder.iterdir()
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
        )

    def refresh_image_count(self) -> int:
        self.image_count = self.count_images()
        return self.image_count

    def claim_stitch(self) -> bool:
        with self._state_lock:
            if self.is_stitching:
                return False
            self.refresh_image_count()
            self.is_stitching = True
            self.last_stitch_count = self.image_count
            return True

    def finish_stitch(self) -> None:
        with self._state_lock:
            self.is_stitching = False


sessions: Dict[str, StitchingSession] = {}
observers: Dict[str, Observer] = {}
stitch_tasks: set[asyncio.Task[None]] = set()
service_loop: asyncio.AbstractEventLoop | None = None


def schedule_from_thread(coroutine: Coroutine[object, object, object]) -> None:
    """Schedule WebSocket and stitching work on FastAPI's owning event loop."""
    if service_loop is None or not service_loop.is_running():
        coroutine.close()
        return
    asyncio.run_coroutine_threadsafe(coroutine, service_loop)


async def notify_clients(session: StitchingSession, payload: dict) -> None:
    disconnected: list[WebSocket] = []
    for websocket in tuple(session.ws_clients):
        try:
            await websocket.send_json(payload)
        except Exception:
            disconnected.append(websocket)
    for websocket in disconnected:
        session.ws_clients.discard(websocket)


async def record_new_images(
    session: StitchingSession,
    file_names: list[str],
) -> None:
    session.refresh_image_count()
    if not session.config.folder_monitoring_enabled:
        for file_name in file_names:
            await notify_clients(
                session,
                {
                    "type": "file_detected",
                    "file": file_name,
                    "total_images": session.image_count,
                },
            )

    images_since_last_stitch = session.image_count - session.last_stitch_count
    if (
        session.config.auto_stitch_enabled
        and images_since_last_stitch >= session.config.auto_stitch_threshold
        and session.claim_stitch()
    ):
        launch_stitch(session.session_id, claimed=True)


class SessionFolderHandler(FileSystemEventHandler):
    def __init__(
        self,
        session_id: str,
        debounce_s: float = 1.0,
        stable_wait: float = 0.5,
        stable_tries: int = 6,
    ):
        self.session_id = session_id
        self.debounce_s = debounce_s
        self.stable_wait = stable_wait
        self.stable_tries = stable_tries
        self.last_called: dict[str, float] = {}

    def _should_call(self, path: str) -> bool:
        now = time.time()
        last = self.last_called.get(path, 0)
        if now - last < self.debounce_s:
            return False
        self.last_called[path] = now
        return True

    def _wait_until_stable(self, path: str) -> bool:
        previous_size = -1
        for _ in range(self.stable_tries):
            if not os.path.exists(path):
                return False
            size = os.path.getsize(path)
            if size == previous_size and size > 0:
                return True
            previous_size = size
            time.sleep(self.stable_wait)
        return False

    def on_created(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.is_directory:
            return
        file_path = str(event.src_path)
        if Path(file_path).suffix.lower() not in IMAGE_SUFFIXES:
            return
        if not self._should_call(file_path) or not self._wait_until_stable(file_path):
            return

        session = sessions.get(self.session_id)
        if session is None:
            return

        session.refresh_image_count()
        schedule_from_thread(
            notify_clients(
                session,
                {
                    "type": "file_detected",
                    "file": Path(file_path).name,
                    "total_images": session.image_count,
                },
            )
        )

        images_since_last_stitch = session.image_count - session.last_stitch_count
        if (
            session.config.auto_stitch_enabled
            and images_since_last_stitch >= session.config.auto_stitch_threshold
            and session.claim_stitch()
        ):
            schedule_from_thread(run_stitching(session.session_id, claimed=True))


def start_folder_monitoring(session_id: str) -> bool:
    session = sessions.get(session_id)
    if session is None:
        return False
    stop_folder_monitoring(session_id)

    observer = Observer()
    observer.schedule(
        SessionFolderHandler(session_id),
        str(session.image_folder),
        recursive=False,
    )
    observer.start()
    observers[session_id] = observer
    session.observer = observer
    return True


def stop_folder_monitoring(session_id: str) -> bool:
    observer = observers.pop(session_id, None)
    if observer is None:
        return False
    observer.stop()
    observer.join()
    session = sessions.get(session_id)
    if session is not None:
        session.observer = None
    return True


def discover_existing_sessions() -> int:
    """Discover receiver-created sessions without replacing active state."""
    SESSIONS_ROOT.mkdir(parents=True, exist_ok=True)
    discovered = 0
    for session_dir in SESSIONS_ROOT.iterdir():
        if not session_dir.is_dir() or not SESSION_ID_PATTERN.fullmatch(session_dir.name):
            continue
        if not (session_dir / "images").exists():
            continue
        existing = sessions.get(session_dir.name)
        if existing is not None:
            existing.refresh_image_count()
            continue
        config = StitchConfig(sessionId=session_dir.name)
        sessions[session_dir.name] = StitchingSession(session_dir.name, config)
        discovered += 1
    return discovered


def require_session(session_id: str) -> StitchingSession:
    if not SESSION_ID_PATTERN.fullmatch(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    session = sessions.get(session_id)
    if session is None:
        discover_existing_sessions()
        session = sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def create_mosaic(session: StitchingSession) -> Path:
    all_images, gps_data = util.importData(
        str(session.image_folder),
        return_as_dict=True,
    )
    if not all_images:
        raise RuntimeError("No images found")

    data_matrix = np.zeros((len(gps_data), 6))
    origin_lat = float(gps_data[0].get("latitude", 0.0))
    origin_lon = float(gps_data[0].get("longitude", 0.0))

    for index, gps in enumerate(gps_data):
        latitude = float(gps.get("latitude", 0.0))
        longitude = float(gps.get("longitude", 0.0))
        data_matrix[index, 0] = (
            (longitude - origin_lon)
            * 111_320
            * np.cos(np.radians(origin_lat))
        )
        data_matrix[index, 1] = (latitude - origin_lat) * 110_540
        data_matrix[index, 2] = float(gps.get("altitude", 0.0))

    combiner = Combiner.Combiner(
        all_images,
        data_matrix,
        str(session.output_folder),
    )
    result = combiner.create_mosaic()
    if result is None:
        raise RuntimeError("Stitching failed")

    output_path = session.output_folder / session.config.output_name
    if not cv2.imwrite(str(output_path), result):
        raise RuntimeError("Unable to write stitched result")
    return output_path


async def run_stitching(session_id: str, claimed: bool = False) -> None:
    session = sessions.get(session_id)
    if session is None or (not claimed and not session.claim_stitch()):
        return

    await notify_clients(
        session,
        {"type": "stitching_started", "image_count": session.image_count},
    )
    start_time = time.monotonic()
    success = False
    error_message: str | None = None

    try:
        await asyncio.to_thread(create_mosaic, session)
        success = True
    except Exception as error:
        error_message = str(error)
        print(f"[STITCH] Session {session_id} failed: {error}", flush=True)
    finally:
        elapsed_time = time.monotonic() - start_time
        session.finish_stitch()

    await notify_clients(
        session,
        {
            "type": "stitching_completed",
            "success": success,
            "elapsed_time": elapsed_time,
            "error_message": error_message,
            "output_file": (
                f"/api/stitching/session/{session_id}/result"
                if success
                else None
            ),
        },
    )


def launch_stitch(session_id: str, claimed: bool = False) -> None:
    task = asyncio.create_task(run_stitching(session_id, claimed=claimed))
    stitch_tasks.add(task)
    task.add_done_callback(stitch_tasks.discard)


async def startup() -> None:
    global service_loop
    service_loop = asyncio.get_running_loop()
    discover_existing_sessions()
    print(f"[STARTUP] Stitch sessions: {SESSIONS_ROOT}", flush=True)


async def shutdown() -> None:
    global service_loop
    for session_id in list(observers):
        stop_folder_monitoring(session_id)
    for task in tuple(stitch_tasks):
        task.cancel()
    if stitch_tasks:
        await asyncio.gather(*stitch_tasks, return_exceptions=True)
    service_loop = None


@api_router.get("/")
async def root():
    return {
        "service": "BIMA Integrated Orthomosaic Stitcher",
        "version": "1.0",
        "active_sessions": len(sessions),
        "monitoring": len(observers),
        "image_source": "base_station_stream_port",
    }


@api_router.get("/health")
async def health():
    return {"status": "ok"}


@api_router.get("/sessions")
async def list_sessions():
    discover_existing_sessions()
    return {
        "sessions": [
            {
                "session_id": session.session_id,
                "image_count": session.refresh_image_count(),
                "is_stitching": session.is_stitching,
                "monitoring": session.config.folder_monitoring_enabled,
                "auto_stitch": session.config.auto_stitch_enabled,
            }
            for session in sorted(sessions.values(), key=lambda item: item.session_id)
        ]
    }


@api_router.post("/session/create")
async def create_session(config: StitchConfig):
    if config.sessionId in sessions:
        session = sessions[config.sessionId]
        session.refresh_image_count()
        return {
            "status": "Session already exists",
            "session_id": config.sessionId,
            "image_count": session.image_count,
            "folder_monitoring": session.config.folder_monitoring_enabled,
        }

    session = StitchingSession(config.sessionId, config)
    sessions[config.sessionId] = session
    if config.folder_monitoring_enabled:
        start_folder_monitoring(config.sessionId)
    return {
        "status": "Session created",
        "session_id": config.sessionId,
        "image_count": session.image_count,
        "folder_monitoring": config.folder_monitoring_enabled,
    }


@api_router.post("/session/{session_id}/toggle-monitoring")
async def toggle_monitoring(session_id: str, enable: bool):
    session = require_session(session_id)
    session.config.folder_monitoring_enabled = enable
    if enable:
        start_folder_monitoring(session_id)
    else:
        stop_folder_monitoring(session_id)
    return {"status": "Monitoring enabled" if enable else "Monitoring disabled"}


@api_router.post("/session/{session_id}/toggle-auto-stitch")
async def toggle_auto_stitch(session_id: str, enable: bool):
    session = require_session(session_id)
    session.config.auto_stitch_enabled = enable
    return {
        "status": "Auto-stitch enabled" if enable else "Auto-stitch disabled",
        "threshold": session.config.auto_stitch_threshold,
    }


@api_router.post("/session/{session_id}/upload")
async def upload_images(
    session_id: str,
    files: List[UploadFile] = File(...),
):
    session = require_session(session_id)
    uploaded_names: list[str] = []

    for upload in files:
        file_name = Path(upload.filename or "").name
        if not file_name or Path(file_name).suffix.lower() not in IMAGE_SUFFIXES:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported image file: {file_name or 'unnamed file'}",
            )
        target = session.image_folder / file_name
        with target.open("wb") as output:
            while chunk := await upload.read(1024 * 1024):
                output.write(chunk)
        await upload.close()
        uploaded_names.append(file_name)

    await record_new_images(session, uploaded_names)
    return {
        "uploaded": len(uploaded_names),
        "total": session.image_count,
        "session_id": session_id,
    }


def write_stream_frame(
    session: StitchingSession,
    frame: np.ndarray,
    request: StreamCaptureRequest,
) -> str:
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    milliseconds = int((time.time() % 1) * 1000)
    unique_id = time.time_ns() % 1_000_000_000
    source_name = f"uav{request.uav_id}" if request.uav_id else "stream"
    file_name = (
        f"{timestamp}_{milliseconds:03d}_{unique_id:09d}_{source_name}_"
        f"{request.stream_port}.jpg"
    )
    target = session.image_folder / file_name
    ok = cv2.imwrite(
        str(target),
        frame,
        [cv2.IMWRITE_JPEG_QUALITY, request.jpeg_quality],
    )
    if not ok:
        raise RuntimeError("Unable to write stream frame")
    return file_name


async def wait_for_stream_frame(stream_port: int, timeout_s: float = 2.0) -> np.ndarray | None:
    if video_manager_instance is None:
        return None

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        frame = video_manager_instance.get_latest_frame(stream_port)
        if frame is not None:
            return frame
        await asyncio.sleep(0.05)
    return None


@api_router.post("/session/{session_id}/capture-stream")
async def capture_stream_frame(
    session_id: str,
    request: StreamCaptureRequest,
):
    if video_manager_instance is None:
        raise HTTPException(status_code=503, detail="Video manager is not initialised")

    session = require_session(session_id)
    video_manager_instance.ensure_stream(request.stream_port, request.json_port)
    frame = await wait_for_stream_frame(request.stream_port)
    if frame is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "No frame has been received on stream port "
                f"{request.stream_port} yet"
            ),
        )

    try:
        file_name = await asyncio.to_thread(write_stream_frame, session, frame, request)
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error)) from error

    await record_new_images(session, [file_name])
    return {
        "captured": 1,
        "file": file_name,
        "total": session.image_count,
        "session_id": session_id,
        "stream_port": request.stream_port,
        "json_port": request.json_port,
        "uav_id": request.uav_id,
    }


@api_router.post("/session/{session_id}/stitch")
async def trigger_stitch(session_id: str):
    session = require_session(session_id)
    if not session.claim_stitch():
        return {"status": "Stitching already in progress"}
    launch_stitch(session_id, claimed=True)
    return {"status": "Stitching started", "image_count": session.image_count}


@api_router.get("/session/{session_id}/result")
async def get_result_image(session_id: str):
    session = require_session(session_id)
    output_file = session.output_folder / session.config.output_name
    if not output_file.exists():
        intermediates = list(session.output_folder.glob("intermediateResult_*.png"))
        if not intermediates:
            raise HTTPException(status_code=404, detail="No result image found")
        output_file = max(intermediates, key=lambda path: path.stat().st_mtime)
    return FileResponse(output_file, headers={"Cache-Control": "no-store"})


@api_router.get("/session/{session_id}/intermediates")
async def list_intermediate_results(session_id: str):
    session = require_session(session_id)
    intermediates = sorted(
        session.output_folder.glob("intermediateResult_*.png"),
        key=lambda path: path.stat().st_mtime,
    )
    return {
        "session_id": session_id,
        "count": len(intermediates),
        "files": [path.name for path in intermediates],
    }


@api_router.get("/session/{session_id}/intermediates/{file_name}")
async def get_intermediate_result(session_id: str, file_name: str):
    session = require_session(session_id)
    if not INTERMEDIATE_PATTERN.fullmatch(file_name):
        raise HTTPException(status_code=404, detail="Intermediate image not found")
    output_file = session.output_folder / file_name
    if not output_file.is_file():
        raise HTTPException(status_code=404, detail="Intermediate image not found")
    return FileResponse(output_file, headers={"Cache-Control": "no-store"})


@api_router.get("/session/{session_id}/status")
async def get_session_status(session_id: str):
    session = require_session(session_id)
    session.refresh_image_count()
    return {
        "session_id": session_id,
        "image_count": session.image_count,
        "is_stitching": session.is_stitching,
        "auto_stitch_enabled": session.config.auto_stitch_enabled,
        "auto_stitch_threshold": session.config.auto_stitch_threshold,
        "folder_monitoring_enabled": session.config.folder_monitoring_enabled,
        "last_stitch_count": session.last_stitch_count,
        "images_since_last_stitch": session.image_count - session.last_stitch_count,
    }


@router.websocket("/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    try:
        session = require_session(session_id)
    except HTTPException:
        await websocket.send_json({"error": "Session not found"})
        await websocket.close(code=1008)
        return

    session.ws_clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except Exception:
        pass
    finally:
        session.ws_clients.discard(websocket)

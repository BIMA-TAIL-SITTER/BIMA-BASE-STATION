"""
Ground Station — FastAPI Application Entry Point
Initializes all services and registers routers.
"""

import asyncio
import logging
import logging.handlers
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config.settings import settings
from app.services.video.manager import MultiStreamManager
from app.services.telemetry.generator import TelemetryGenerator
from app.services.websocket.manager import WebSocketManager
from app.services.yolo.detector import YOLODetector
from app.routers import video, telemetry, system

# ─── Logging Setup ────────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)

_log_formatter = logging.Formatter(
    fmt="%(asctime)s [%(levelname)-8s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

_file_handler = logging.handlers.RotatingFileHandler(
    filename="logs/ground_station.log",
    maxBytes=10 * 1024 * 1024,  # 10 MB
    backupCount=5,
    encoding="utf-8",
)
_file_handler.setFormatter(_log_formatter)

_console_handler = logging.StreamHandler()
_console_handler.setFormatter(_log_formatter)

_root_logger = logging.getLogger()
_root_logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
_root_logger.addHandler(_file_handler)
_root_logger.addHandler(_console_handler)

logger = logging.getLogger(__name__)

# ─── Global Service Instances ──────────────────────────────────────
ws_manager = WebSocketManager()

# YOLO detector — disabled automatically if `ultralytics` isn't installed
# or YOLO_ENABLED=false in settings. Reads frames straight from the
# receiver, independent of the video broadcast loop.
yolo_detector = YOLODetector(
    ws_manager=ws_manager,
    model_path=settings.YOLO_MODEL_PATH,
    conf_threshold=settings.YOLO_CONF_THRESHOLD,
    iou_threshold=settings.YOLO_IOU_THRESHOLD,
    max_fps=settings.YOLO_MAX_FPS,
    device=settings.YOLO_DEVICE or None,
) if settings.YOLO_ENABLED else None

video_manager = MultiStreamManager(
    ws_manager=ws_manager,
    fps_limit=settings.VIDEO_FPS_LIMIT,
    detector=yolo_detector,
)
telemetry_generator = TelemetryGenerator(ws_manager=ws_manager)


# ─── Lifespan ─────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start background services on startup, stop them on shutdown."""
    logger.info("═══════════════════════════════════════════")
    logger.info("  UAV Ground Station starting up")
    logger.info("  Web  port : %d", settings.WEB_PORT)
    logger.info("  Host      : %s", settings.HOST)
    logger.info("  YOLO      : %s", "enabled" if settings.YOLO_ENABLED else "disabled")
    logger.info("═══════════════════════════════════════════")

    os.makedirs("snapshots", exist_ok=True)

    # Inject service references into routers so they can be accessed
    video.video_manager_instance = video_manager
    video.ws_manager_instance = ws_manager
    video.yolo_detector_instance = yolo_detector
    telemetry.telemetry_generator_instance = telemetry_generator
    telemetry.ws_manager_instance = ws_manager
    system.ws_manager_instance = ws_manager

    # Start YOLO detector in its own background thread (blocking inference)
    if yolo_detector is not None:
        yolo_detector.start()
        if yolo_detector.is_enabled:
            logger.info("YOLODetector started (model=%s)", settings.YOLO_MODEL_PATH)
        else:
            logger.warning("YOLODetector requested but unavailable — check ultralytics install")

    # Start async broadcast loops
    telemetry_task = asyncio.create_task(telemetry_generator.broadcast_loop())

    logger.info("Ground Station ready — open http://%s:%d", settings.HOST, settings.WEB_PORT)

    yield  # App is running

    # ─── Shutdown ──────────────────────────────────────────────────
    logger.info("Ground Station shutting down…")
    telemetry_task.cancel()
    video_manager.stop_all()
    if yolo_detector is not None:
        yolo_detector.stop()
    try:
        await asyncio.gather(video_task, telemetry_task, return_exceptions=True)
    except Exception:
        pass
    logger.info("Ground Station stopped.")


# ─── FastAPI App ──────────────────────────────────────────────────
app = FastAPI(
    title="UAV Ground Station",
    version="1.0.0",
    description="Web-based UAV Ground Station with real-time video and telemetry",
    lifespan=lifespan,
)

# ─── CORS ─────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],           # Restrict in production to known origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Static Files & Templates ────────────────────────────────────
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# ─── Routers ─────────────────────────────────────────────────────
app.include_router(video.router)
app.include_router(telemetry.router)
app.include_router(system.router)
app.include_router(video.api_router)
app.include_router(telemetry.api_router)
app.include_router(system.api_router)


# ─── Root ─────────────────────────────────────────────────────────
@app.get("/", include_in_schema=False)
async def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "title": "UAV Ground Station",
            "ws_host": request.headers.get("host", f"{settings.HOST}:{settings.WEB_PORT}"),
        },
    )


# ─── Health Check ─────────────────────────────────────────────────
@app.get("/health", tags=["system"])
async def health():
    video_status = video_manager.get_status()
    return {
        "status": "ok",
        "video": video_status,
        "yolo": {
            "enabled": yolo_detector.is_enabled if yolo_detector else False,
        },
        "clients": ws_manager.client_count(),
    }
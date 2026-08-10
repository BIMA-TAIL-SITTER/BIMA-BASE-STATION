"""
Ground Station — FastAPI Application Entry Point
Initializes all services and registers routers.
"""


import asyncio
import logging
import logging.handlers
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.config.settings import settings
from app.services.video.manager import MultiStreamManager
from app.services.mavlink.command_bridge import MavlinkCommandBridge
from app.services.mavlink.message_router import MavlinkMessageRouter
from app.services.mavlink.param_bridge import MavlinkParamBridge
from app.services.mavlink.telemetry_bridge import MavlinkTelemetryBridge
from app.services.websocket.manager import WebSocketManager
from app.routers import control, video, telemetry, system, stitching

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

video_manager = MultiStreamManager(
    ws_manager=ws_manager,
    fps_limit=settings.VIDEO_FPS_LIMIT,
)
telemetry_generator = MavlinkTelemetryBridge(ws_manager=ws_manager)
message_router = MavlinkMessageRouter(telemetry_generator.connections)
command_bridge = MavlinkCommandBridge(
    connections=telemetry_generator.connections,
    message_router=message_router,
    ws_manager=ws_manager,
    mission_cache_sink=telemetry_generator.set_mission,
)
param_bridge = MavlinkParamBridge(
    connections=telemetry_generator.connections,
    message_router=message_router,
    ws_manager=ws_manager,
)
message_router.register_handler({"*"}, telemetry_generator.handle_message)
message_router.register_handler(
    {"AUTOPILOT_VERSION", "HEARTBEAT", "PARAM_VALUE"},
    param_bridge.handle_message,
)


# ─── Lifespan ─────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start background services on startup, stop them on shutdown."""
    logger.info("═══════════════════════════════════════════")
    logger.info("  UAV Ground Station starting up")
    logger.info("  Web  port : %d", settings.WEB_PORT)
    logger.info("  Host      : %s", settings.HOST)
    logger.info("═══════════════════════════════════════════")

    os.makedirs("snapshots", exist_ok=True)

    # Inject service references into routers so they can be accessed
    video.video_manager_instance = video_manager
    video.ws_manager_instance = ws_manager
    stitching.video_manager_instance = video_manager
    telemetry.telemetry_generator_instance = telemetry_generator
    telemetry.ws_manager_instance = ws_manager
    telemetry.mission_manager_instance = command_bridge
    control.command_bridge_instance = command_bridge
    control.param_bridge_instance = param_bridge
    control.ws_manager_instance = ws_manager
    system.ws_manager_instance = ws_manager

    # Start the single MAVLink receiver before telemetry broadcasting.
    await stitching.startup()
    await message_router.start()
    telemetry_task = asyncio.create_task(telemetry_generator.broadcast_loop())

    logger.info("Ground Station ready — open http://%s:%d", settings.HOST, settings.WEB_PORT)

    yield  # App is running

    # ─── Shutdown ──────────────────────────────────────────────────
    logger.info("Ground Station shutting down…")
    telemetry_task.cancel()
    video_manager.stop_all()
    await stitching.shutdown()
    await param_bridge.stop()
    await message_router.stop()
    if hasattr(telemetry_generator, 'stop'):
        await telemetry_generator.stop()
    try:
        await asyncio.gather(telemetry_task, return_exceptions=True)
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
# Removed in favor of Next.js frontend

from app.routers.peta import peta_router

# ─── Routers ─────────────────────────────────────────────────────
app.include_router(video.router)
app.include_router(telemetry.router)
app.include_router(system.router)
app.include_router(control.router)
app.include_router(stitching.router)
app.include_router(video.api_router)
app.include_router(telemetry.api_router)
app.include_router(system.api_router)
app.include_router(control.api_router)
app.include_router(stitching.api_router)
app.include_router(peta_router)


# ─── Root ─────────────────────────────────────────────────────────
import socket

def get_tailscale_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Tailscale MagicDNS IP, forces routing to use the Tailscale interface
        s.connect(("100.100.100.100", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip.startswith("100."):
            return ip
    except Exception:
        pass
    
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Fallback to general internet routing to get primary LAN IP
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"




# ─── Config API (for decoupled Next.js frontend) ─────────────────
@app.get("/api/config", tags=["system"])
async def get_config(request: Request):
    """Return server configuration for the decoupled Next.js frontend."""
    return {
        "ws_host": request.headers.get("host", f"{settings.HOST}:{settings.WEB_PORT}"),
        "tailscale_ip": get_tailscale_ip(),
        "web_port": settings.WEB_PORT,
    }


# ─── Health Check ─────────────────────────────────────────────────
@app.get("/health", tags=["system"])
async def health():
    video_status = video_manager.get_status()
    return {
        "status": "ok",
        "video": video_status,
        "clients": ws_manager.client_count(),
    }

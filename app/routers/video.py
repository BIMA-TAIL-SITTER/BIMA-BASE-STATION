"""
Video Router
─────────────
Handles /ws/video WebSocket endpoint and /api/video/* REST endpoints.

video_manager_instance, ws_manager_instance, and yolo_detector_instance
are injected by main.py after the lifespan starts.
"""

import logging
import time

import cv2
import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["video"])

# Injected by main.py lifespan
video_manager_instance = None
ws_manager_instance = None


@router.websocket("/video/{port}")
async def video_ws(websocket: WebSocket, port: int, json_port: int = None):
    """
    Binary WebSocket stream of JPEG frames.

    The client receives raw JPEG bytes on each message.
    Each message is one complete frame — no framing protocol needed.
    """
    if ws_manager_instance is None or video_manager_instance is None:
        await websocket.close(code=1011)
        return

    # Ensure the UDP receiver for this port is running
    video_manager_instance.ensure_stream(port, json_port)
    
    await ws_manager_instance.connect_video(websocket, port)
    try:
        while True:
            # Keep the connection alive; client sends pings or nothing
            await websocket.receive_bytes()
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("Video WebSocket error on port %d: %s", port, exc)
    finally:
        ws_manager_instance.disconnect_video(websocket, port)
        
        # If no more clients are watching this port, stop the receiver to save resources
        if not ws_manager_instance.has_video_clients(port):
            video_manager_instance.stop_stream(port)


# ─── REST ─────────────────────────────────────────────────────────
api_router = APIRouter(prefix="/api/video", tags=["video"])


@api_router.get("/status")
async def video_status():
    """Return current video receiver statistics."""
    if video_manager_instance is None:
        return {"error": "not initialised"}
    return video_manager_instance.get_status()



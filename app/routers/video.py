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
yolo_detector_instance = None


@router.websocket("/video/{port}")
async def video_ws(websocket: WebSocket, port: int):
    """
    Binary WebSocket stream of JPEG frames.

    The client receives raw JPEG bytes on each message.
    Each message is one complete frame — no framing protocol needed.
    """
    if ws_manager_instance is None or video_manager_instance is None:
        await websocket.close(code=1011)
        return

    # Ensure the UDP receiver for this port is running
    video_manager_instance.ensure_stream(port)
    
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


@api_router.post("/detect")
async def detect_frame(request: Request):
    """
    Accept a JPEG frame via POST body and return YOLO detections.
    Used by the browser to run YOLO on webcam/phone camera frames.
    """
    if yolo_detector_instance is None or not yolo_detector_instance.is_enabled:
        return JSONResponse(
            {"type": "detections", "detections": [], "count": 0, "error": "YOLO not available"},
            status_code=200,
        )

    try:
        body = await request.body()
        if not body:
            return JSONResponse({"error": "empty body"}, status_code=400)

        # Decode JPEG → numpy array
        arr = np.frombuffer(body, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            return JSONResponse({"error": "invalid image"}, status_code=400)

        # Run inference
        t0 = time.monotonic()
        h, w = frame.shape[:2]

        # Debug: Save frame to disk to verify what the backend receives
        cv2.imwrite(f"debug_frame_{w}x{h}.jpg", frame)

        predict_kwargs = dict(
            conf=yolo_detector_instance._conf,
            iou=yolo_detector_instance._iou,
            verbose=False,
        )
        if yolo_detector_instance._class_ids is not None:
            predict_kwargs["classes"] = yolo_detector_instance._class_ids
        if yolo_detector_instance._device:
            predict_kwargs["device"] = yolo_detector_instance._device

        with yolo_detector_instance._inference_lock:
            results = yolo_detector_instance._model.predict(frame, **predict_kwargs)
        inference_ms = (time.monotonic() - t0) * 1000.0

        detections = []
        _PALETTE = ["#D5FF40", "#40C4FF", "#FF6B6B", "#FFD166", "#9D4EDD", "#06D6A0"]

        if results:
            result = results[0]
            boxes = result.boxes
            names = result.names

            if boxes is not None and len(boxes):
                for box in boxes:
                    xyxy = box.xyxy[0].tolist()
                    cls_id = int(box.cls[0].item())
                    conf = float(box.conf[0].item())

                    if isinstance(names, dict):
                        label = names.get(cls_id, str(cls_id))
                    elif isinstance(names, (list, tuple)):
                        label = names[cls_id] if cls_id < len(names) else str(cls_id)
                    else:
                        label = str(cls_id)

                    color = _PALETTE[cls_id % len(_PALETTE)]
                    detections.append({
                        "x1": round(xyxy[0], 1),
                        "y1": round(xyxy[1], 1),
                        "x2": round(xyxy[2], 1),
                        "y2": round(xyxy[3], 1),
                        "label": label,
                        "conf": round(conf, 3),
                        "class_id": cls_id,
                        "color": color,
                    })

        return {
            "type": "detections",
            "frame_width": w,
            "frame_height": h,
            "inference_ms": round(inference_ms, 1),
            "count": len(detections),
            "detections": detections,
        }

    except Exception as exc:
        logger.exception("YOLO detect endpoint error:")
        with open("yolo_debug.log", "a") as f:
            import traceback
            f.write(traceback.format_exc() + "\n")
        return JSONResponse({"error": str(exc)}, status_code=500)

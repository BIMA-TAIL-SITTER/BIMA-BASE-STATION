"""
YOLO Detector
─────────────
Real-time object detection on the latest video frame using Ultralytics YOLO.

Design notes
------------
* Inference runs in its own background thread — never inside the asyncio
  event loop, otherwise it would stall video/telemetry broadcasting.
* Only the *latest* frame is ever processed ("drop, don't queue").
  If inference is slower than the incoming frame rate, older frames are skipped.
* Detections are exposed via a thread-safe property (`latest_detections`)
  that VideoManager polls once per broadcast tick.
* Hasil deteksi di-broadcast langsung ke /ws/video sebagai JSON text message
  via ws_manager.broadcast_video_detections() menggunakan run_coroutine_threadsafe.

Install:
    pip install ultralytics

Model weights:
    Default: "yolo11n.pt" — auto-download saat pertama kali dipakai.
    Swap ke model custom dengan YOLO_MODEL_PATH di settings.

COCO class IDs (yolo11n.pt):
    0  = person   ← default target
    (lihat semua: detector.print_classes())
"""

import asyncio
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

try:
    from ultralytics import YOLO
    _ULTRALYTICS_AVAILABLE = True
except ImportError:
    _ULTRALYTICS_AVAILABLE = False
    logger.warning(
        "ultralytics tidak terinstall — YOLO detection disabled. "
        "Jalankan: pip install ultralytics"
    )


# ─── Palette warna per class ────────────────────────────────────────────────

_PALETTE = [
    "#D5FF40",  # lime   — class 0 (person di COCO)
    "#40C4FF",  # cyan   — class 1
    "#FF6B6B",  # red    — class 2
    "#FFD166",  # amber  — class 3
    "#9D4EDD",  # violet — class 4
    "#06D6A0",  # teal   — class 5
]


# ─── Data classes ───────────────────────────────────────────────────────────

@dataclass
class Detection:
    """Satu objek terdeteksi, dalam koordinat piksel frame sumber."""
    x1: float
    y1: float
    x2: float
    y2: float
    label: str
    conf: float
    class_id: int
    color: str = "#D5FF40"

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def center(self) -> tuple:
        return ((self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2)

    def to_dict(self) -> dict:
        return {
            "x1":       round(self.x1, 1),
            "y1":       round(self.y1, 1),
            "x2":       round(self.x2, 1),
            "y2":       round(self.y2, 1),
            "label":    self.label,
            "conf":     round(self.conf, 3),
            "class_id": self.class_id,
            "color":    self.color,
        }


@dataclass
class DetectionFrame:
    """Hasil deteksi lengkap untuk satu frame."""
    detections: List[Detection]
    frame_width: int
    frame_height: int
    inference_ms: float
    timestamp: float
    model_path: str = ""

    @property
    def count(self) -> int:
        return len(self.detections)

    def to_dict(self) -> dict:
        return {
            "type":         "detections",
            "timestamp":    self.timestamp,
            "frame_width":  self.frame_width,
            "frame_height": self.frame_height,
            "inference_ms": round(self.inference_ms, 1),
            "count":        self.count,
            "detections":   [d.to_dict() for d in self.detections],
        }


# ─── YOLODetector ───────────────────────────────────────────────────────────

class YOLODetector:
    """
    Background-thread YOLO inference engine.

    Contoh pemakaian untuk person detection:
        detector = YOLODetector(receiver=video_receiver, ws_manager=ws_manager)
        detector.start()
        detector.print_classes()         # debug: lihat semua class yang ada di model

    Contoh untuk model custom Roboflow (misal class "head", "person"):
        detector = YOLODetector(
            receiver=video_receiver,
            ws_manager=ws_manager,
            model_path="app/services/yolo/best.pt",
            target_classes=["head", "person"],
        )
    """

    def __init__(
        self,
        receiver,
        ws_manager=None,                             # ← WebSocketManager instance
        model_path: str = "yolo11n.pt",
        conf_threshold: float = 0.4,
        iou_threshold: float = 0.45,
        max_fps: float = 10.0,
        device: Optional[str] = None,
        target_classes: Optional[List[str]] = None,
        class_ids: Optional[List[int]] = None,
    ) -> None:
        self._receiver   = receiver
        self._ws         = ws_manager                # bisa None kalau ga mau broadcast
        self._model_path = model_path
        self._conf       = conf_threshold
        self._iou        = iou_threshold
        self._min_interval = 1.0 / max(0.1, max_fps)
        self._device     = device or ""

        self._target_class_names: Optional[List[str]] = target_classes or ["laptop", "person", "banana"]
        self._class_ids: Optional[List[int]]          = class_ids

        self._model: Optional["YOLO"] = None
        self._names: Dict[int, str]   = {}
        self._thread: Optional[threading.Thread] = None
        self._running  = False
        self._lock     = threading.Lock()
        self._inference_lock = threading.Lock()
        self._latest:  Optional[DetectionFrame] = None
        self._enabled  = _ULTRALYTICS_AVAILABLE

        # Event loop asyncio — di-grab saat start() dipanggil dari lifespan
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Diagnostics
        self._total_inferences = 0
        self._total_detections = 0

    # ─── Public API ──────────────────────────────────────────────

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    @property
    def class_names(self) -> Dict[int, str]:
        return dict(self._names)

    @property
    def active_class_ids(self) -> Optional[List[int]]:
        return self._class_ids

    @property
    def latest_detections(self) -> Optional[DetectionFrame]:
        with self._lock:
            return self._latest

    def print_classes(self) -> None:
        if not self._names:
            logger.warning("Model belum di-load, panggil start() dulu.")
            return
        logger.info("=== Class list dari model '%s' ===", self._model_path)
        for cid, name in sorted(self._names.items()):
            active = " ← AKTIF" if (
                self._class_ids is None or cid in self._class_ids
            ) else ""
            logger.info("  [%3d] %s%s", cid, name, active)
        logger.info("Filter aktif: %s", self._class_ids)

    def start(self) -> None:
        if not self._enabled:
            logger.error("YOLO tidak bisa start: ultralytics tidak terinstall.")
            return
        if self._thread and self._thread.is_alive():
            logger.warning("YOLODetector sudah running.")
            return

        # Simpan event loop asyncio yang sedang aktif (dipanggil dari lifespan)
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None
            logger.warning("YOLODetector.start() dipanggil di luar async context — broadcast dinonaktifkan.")

        logger.info("Loading YOLO model: %s", self._model_path)
        try:
            self._model = YOLO(self._model_path)
        except Exception as exc:
            logger.error("Gagal load model '%s': %s", self._model_path, exc)
            self._enabled = False
            return

        self._names = self._model.names if isinstance(self._model.names, dict) else {}

        if self._target_class_names and not self._class_ids:
            resolved = []
            name_to_id = {v.lower(): k for k, v in self._names.items()}
            for name in self._target_class_names:
                cid = name_to_id.get(name.lower())
                if cid is not None:
                    resolved.append(cid)
                    logger.info("Class '%s' → ID %d", name, cid)
                else:
                    logger.warning(
                        "Class '%s' tidak ditemukan di model. Tersedia: %s",
                        name, list(self._names.values()),
                    )
            self._class_ids = resolved if resolved else None

        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop, name="YOLODetector", daemon=True
        )
        self._thread.start()

        logger.info(
            "YOLODetector started | model=%s | conf=%.2f | iou=%.2f | "
            "max_fps=%.1f | device='%s' | filter=%s | ws_broadcast=%s",
            self._model_path,
            self._conf,
            self._iou,
            1.0 / self._min_interval,
            self._device or "auto",
            self._class_ids,
            "enabled" if (self._ws and self._loop) else "disabled",
        )

        self.print_classes()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=3.0)
        logger.info(
            "YOLODetector stopped | total_inferences=%d | total_detections=%d",
            self._total_inferences,
            self._total_detections,
        )

    # ─── Internal loop ───────────────────────────────────────────

    def _run_loop(self) -> None:
        last_run = 0.0
        while self._running:
            now = time.monotonic()
            wait = self._min_interval - (now - last_run)
            if wait > 0:
                time.sleep(wait)
                continue

            last_run = time.monotonic()

            frame = self._receiver.latest_frame
            if frame is None:
                logger.debug("latest_frame masih None, menunggu stream...")
                time.sleep(0.05)
                continue

            if not isinstance(frame, np.ndarray):
                logger.warning(
                    "latest_frame bukan np.ndarray, tipe=%s.",
                    type(frame).__name__,
                )
                time.sleep(0.1)
                continue

            try:
                self._infer(frame)
            except Exception:
                logger.exception("Error saat YOLO inference:")
                time.sleep(0.2)

    def _infer(self, frame: np.ndarray) -> None:
        t0 = time.monotonic()
        h, w = frame.shape[:2]

        predict_kwargs = dict(conf=self._conf, iou=self._iou, verbose=False)
        if self._class_ids is not None:
            predict_kwargs["classes"] = self._class_ids
        if self._device:
            predict_kwargs["device"] = self._device

        with self._inference_lock:
            results = self._model.predict(frame, **predict_kwargs)
        inference_ms = (time.monotonic() - t0) * 1000.0

        detections: List[Detection] = []
        if results:
            result = results[0]
            boxes  = result.boxes
            names  = result.names

            if boxes is not None and len(boxes):
                for box in boxes:
                    xyxy   = box.xyxy[0].tolist()
                    cls_id = int(box.cls[0].item())
                    conf   = float(box.conf[0].item())

                    if isinstance(names, dict):
                        label = names.get(cls_id, str(cls_id))
                    elif isinstance(names, (list, tuple)):
                        label = names[cls_id] if cls_id < len(names) else str(cls_id)
                    else:
                        label = str(cls_id)

                    color = _PALETTE[cls_id % len(_PALETTE)]
                    detections.append(Detection(
                        x1=xyxy[0], y1=xyxy[1],
                        x2=xyxy[2], y2=xyxy[3],
                        label=label, conf=conf,
                        class_id=cls_id, color=color,
                    ))

        self._total_inferences += 1
        self._total_detections += len(detections)

        if detections:
            logger.debug(
                "Detected %d object(s) | %.1f ms | %s",
                len(detections), inference_ms,
                [(d.label, f"{d.conf:.2f}") for d in detections],
            )

        frame_result = DetectionFrame(
            detections=detections,
            frame_width=w,
            frame_height=h,
            inference_ms=inference_ms,
            timestamp=time.time(),
            model_path=self._model_path,
        )

        with self._lock:
            self._latest = frame_result

        # ─── Broadcast ke /ws/video ──────────────────────────────
        if self._ws and self._loop and self._loop.is_running():
            payload = json.dumps(frame_result.to_dict())
            logger.info("Sending detections: %s", payload)  # sementara, hapus kalau udah jalan
            asyncio.run_coroutine_threadsafe(
                self._ws.broadcast_video_detections(payload),
                self._loop,
            )
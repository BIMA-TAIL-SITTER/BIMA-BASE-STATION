"use client";

import {
  useRef,
  useState,
  useCallback,
  useEffect,
  type CSSProperties,
} from "react";
import { UAV_AGENT_BY_ID } from "@/config/agents";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useGCSStore } from "@/hooks/useGCSStore";
import { HudCanvas, type HudCanvasHandle } from "./HudCanvas";
import type { Detection, PanelDrawState } from "@/types/video";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface VideoPanelProps {
  panelId: 1 | 2;
  onTargetUpdate?: (target: {
    detected: boolean;
    lat: string;
    lon: string;
    dist: string;
    gsd: string;
  }) => void;
}

interface CameraOption {
  deviceId: string;
  label: string;
}

export default function VideoPanel({ panelId, onTargetUpdate }: VideoPanelProps) {
  const { config, uavs, isConfigured, yoloEnabled } = useGCSStore();
  const uavConfig = uavs[panelId];
  const agent = UAV_AGENT_BY_ID[panelId];

  const videoCanvasRef = useRef<HTMLCanvasElement>(null);
  const webcamVideoRef = useRef<HTMLVideoElement>(null);
  const hudRef = useRef<HudCanvasHandle>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const [cameras, setCameras] = useState<CameraOption[]>([]);
  const [sourceMode, setSourceMode] = useState<string>("udp");
  const [udpPort, setUdpPort] = useState<number>(uavConfig ? parseInt(uavConfig.streamPort, 10) || (panelId === 1 ? 5600 : 5601) : (panelId === 1 ? 5600 : 5601));
  const [jsonPort, setJsonPort] = useState<number>(uavConfig ? parseInt(uavConfig.jsonPort, 10) || (panelId === 1 ? 5001 : 5002) : (panelId === 1 ? 5001 : 5002));

  const [showCrosshair, setShowCrosshair] = useState(true);
  const [showHUD, setShowHUD] = useState(true);
  const showDetections = true;
  const [noSignal, setNoSignal] = useState(true);
  const [noSignalText, setNoSignalText] = useState(`Waiting for UDP on port ${udpPort}...`);
  const [fps, setFps] = useState(0);
  const [yoloFps, setYoloFps] = useState("---");

  // Frame & detection refs (not state — avoids re-renders at 30fps)
  const detectionsRef = useRef<Detection[]>([]);
  const detFrameSizeRef = useRef({ w: 0, h: 0 });
  const lastDrawRef = useRef<PanelDrawState>({ dx: 0, dy: 0, dw: 0, dh: 0, cw: 0, ch: 0 });
  const frameCountRef = useRef(0);
  const lastFpsTimeRef = useRef(0);
  const activeStreamRef = useRef<MediaStream | null>(null);
  const animFrameRef = useRef<number>(0);
  const yoloTimerRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined);

  // Video stats
  const [videoStats, setVideoStats] = useState({
    gsd: "--",
    dist: "--",
    uavLoc: "--",
    tgtLoc: "--",
  });

  // Enumerate cameras
  useEffect(() => {
    async function loadCameras() {
      try {
        const devices = await navigator.mediaDevices.enumerateDevices();
        const cams = devices
          .filter((d) => d.kind === "videoinput")
          .map((d, i) => ({
            deviceId: d.deviceId,
            label: d.label || `Camera ${i + 1}`,
          }));
        setCameras(cams);
      } catch {
        // Permission not yet granted or no cameras
      }
    }
    loadCameras();
  }, []);

  // Update initial ports when config loads
  useEffect(() => {
    let active = true;
    queueMicrotask(() => {
      if (!active) return;
      if (uavConfig?.streamPort) {
        setUdpPort((current) => parseInt(uavConfig.streamPort, 10) || current);
      }
      if (uavConfig?.jsonPort) {
        setJsonPort((current) => parseInt(uavConfig.jsonPort, 10) || current);
      }
    });
    return () => {
      active = false;
    };
  }, [uavConfig]);

  // Build WebSocket URL for UDP source
  const wsHost = config?.ws_host;
  const wsUrl = isConfigured && wsHost && sourceMode === "udp" && udpPort
    ? `ws://${wsHost}/ws/video/${udpPort}${jsonPort ? `?json_port=${jsonPort}` : ""}`
    : "";

  // Canvas resize
  const syncCanvasSize = useCallback(() => {
    const container = containerRef.current;
    const vc = videoCanvasRef.current;
    if (!container || !vc) return;

    const w = container.clientWidth;
    const h = container.clientHeight;
    if (vc.width !== w || vc.height !== h) {
      vc.width = w;
      vc.height = h;
      const hudCanvas = container.querySelector<HTMLCanvasElement>(".hud-canvas-overlay");
      if (hudCanvas) {
        hudCanvas.width = w;
        hudCanvas.height = h;
      }
    }
  }, []);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const observer = new ResizeObserver(syncCanvasSize);
    observer.observe(container);
    syncCanvasSize();
    return () => observer.disconnect();
  }, [syncCanvasSize]);

  // Handle binary video frame from UDP WebSocket
  const onBinary = useCallback((blob: Blob) => {
    if (sourceMode !== "udp") return;
    const vc = videoCanvasRef.current;
    if (!vc) return;

    const img = new Image();
    const url = URL.createObjectURL(blob);
    img.onload = () => {
      URL.revokeObjectURL(url);
      // Backend placeholder image is 320x180
      if (img.width === 320 && img.height === 180) {
        setNoSignal(true);
        return;
      }
      setNoSignal(false);
      syncCanvasSize();
      const cw = vc.width;
      const ch = vc.height;
      const scale = Math.min(cw / img.width, ch / img.height);
      const dw = img.width * scale;
      const dh = img.height * scale;
      const dx = (cw - dw) / 2;
      const dy = (ch - dh) / 2;

      const ctx = vc.getContext("2d", { alpha: false });
      if (ctx) {
        ctx.fillStyle = "#0a0a08";
        ctx.fillRect(0, 0, cw, ch);
        ctx.drawImage(img, dx, dy, dw, dh);
      }

      const draw: PanelDrawState = { dx, dy, dw, dh, cw, ch };
      lastDrawRef.current = draw;

      hudRef.current?.drawHUD(draw, detectionsRef.current, detFrameSizeRef.current.w, detFrameSizeRef.current.h);

      frameCountRef.current++;
      const now = performance.now();
      if (lastFpsTimeRef.current === 0) lastFpsTimeRef.current = now;
      const elapsed = now - lastFpsTimeRef.current;
      if (elapsed >= 1000) {
        setFps(Math.round(frameCountRef.current / (elapsed / 1000)));
        frameCountRef.current = 0;
        lastFpsTimeRef.current = now;
      }
    };
    img.onerror = () => URL.revokeObjectURL(url);
    img.src = url;
  }, [sourceMode, syncCanvasSize]);

  // Handle text messages (detections + telemetry)
  const onMessage = useCallback((data: string) => {
    if (sourceMode !== "udp") return;
    try {
      const msg = JSON.parse(data);

      if (msg.type === "telemetry") {
        setYoloFps(msg.fps_inference?.toString() || "---");
        const isDetected = !!msg.detection;
        const gsdStr = msg.lokasi_target?.gsd_x?.toFixed(3) || "--";
        const distStr = msg.lokasi_target?.distance_m?.toFixed(1) || "--";
        const latStr = msg.lokasi_target?.lat ? msg.lokasi_target.lat.toFixed(6) : "--";
        const lonStr = msg.lokasi_target?.lon ? msg.lokasi_target.lon.toFixed(6) : "--";

        if (onTargetUpdate) {
          onTargetUpdate({
            detected: isDetected,
            lat: latStr,
            lon: lonStr,
            dist: distStr !== "--" ? `${distStr} m` : "--",
            gsd: gsdStr !== "--" ? `${gsdStr} m/px` : "--",
          });
        }

        if (msg.detection) {
          setVideoStats({
            gsd: gsdStr,
            dist: distStr,
            uavLoc: msg.lokasi_uav?.lat
              ? `${msg.lokasi_uav.lat.toFixed(5)}, ${msg.lokasi_uav.lon.toFixed(5)} (${msg.lokasi_uav.alt_m?.toFixed(1)}m)`
              : "Wait GPS Lock..",
            tgtLoc: msg.lokasi_target?.lat
              ? `${msg.lokasi_target.lat.toFixed(5)}, ${msg.lokasi_target.lon.toFixed(5)}`
              : "Wait GPS Lock..",
          });
        } else {
          setVideoStats((prev) => ({
            ...prev,
            tgtLoc: "--",
            uavLoc: msg.lokasi_uav?.lat
              ? `${msg.lokasi_uav.lat.toFixed(5)}, ${msg.lokasi_uav.lon.toFixed(5)} (${msg.lokasi_uav.alt_m?.toFixed(1)}m)`
              : "Wait GPS Lock..",
          }));
        }
        return;
      }

      if (msg.type === "detections") {
        detectionsRef.current = msg.detections || [];
        detFrameSizeRef.current = { w: msg.frame_width || 0, h: msg.frame_height || 0 };
        if (msg.inference_ms) {
          setYoloFps((1000 / msg.inference_ms).toFixed(1));
        }
        const ld = lastDrawRef.current;
        hudRef.current?.drawHUD(ld, detectionsRef.current, detFrameSizeRef.current.w, detFrameSizeRef.current.h);
      }
    } catch {
      // ignore parse errors
    }
  }, [sourceMode, onTargetUpdate]);

  const handleSocketClose = useCallback(() => {
    if (sourceMode === "udp") setNoSignal(true);
  }, [sourceMode]);

  // Connect WebSocket for UDP mode
  useWebSocket({
    url: wsUrl,
    onBinary,
    onMessage,
    enabled: !!wsUrl && sourceMode === "udp",
    binaryType: "blob",
    onClose: handleSocketClose,
  });

  // Local Webcam stream & YOLO processing
  const stopWebcam = useCallback(() => {
    if (activeStreamRef.current) {
      activeStreamRef.current.getTracks().forEach((t) => t.stop());
      activeStreamRef.current = null;
    }
    if (animFrameRef.current) {
      cancelAnimationFrame(animFrameRef.current);
      animFrameRef.current = 0;
    }
    if (yoloTimerRef.current) {
      clearInterval(yoloTimerRef.current);
      yoloTimerRef.current = undefined;
    }
  }, []);

  const startWebcam = useCallback(async (deviceId: string) => {
    stopWebcam();
    setNoSignal(true);
    setNoSignalText("Starting camera...");

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { deviceId: { exact: deviceId } },
      });
      activeStreamRef.current = stream;
      const videoEl = webcamVideoRef.current;
      if (videoEl) {
        videoEl.srcObject = stream;
        await videoEl.play();
      }
      setNoSignal(false);

      // Render loop for webcam
      const drawWebcamFrame = () => {
        if (!activeStreamRef.current) return;
        const vc = videoCanvasRef.current;
        const ve = webcamVideoRef.current;
        if (vc && ve && ve.readyState >= 2) {
          syncCanvasSize();
          const cw = vc.width;
          const ch = vc.height;
          const vw = ve.videoWidth || 1;
          const vh = ve.videoHeight || 1;
          const scale = Math.min(cw / vw, ch / vh);
          const dw = vw * scale;
          const dh = vh * scale;
          const dx = (cw - dw) / 2;
          const dy = (ch - dh) / 2;

          const ctx = vc.getContext("2d", { alpha: false });
          if (ctx) {
            ctx.fillStyle = "#0a0a08";
            ctx.fillRect(0, 0, cw, ch);
            ctx.drawImage(ve, dx, dy, dw, dh);
          }

          const draw: PanelDrawState = { dx, dy, dw, dh, cw, ch };
          lastDrawRef.current = draw;
          hudRef.current?.drawHUD(draw, detectionsRef.current, detFrameSizeRef.current.w, detFrameSizeRef.current.h);
        }
        animFrameRef.current = requestAnimationFrame(drawWebcamFrame);
      };
      drawWebcamFrame();

      // Start YOLO polling for local webcam
      const tmpCanvas = document.createElement("canvas");
      let sending = false;
      yoloTimerRef.current = setInterval(async () => {
        if (sending || !yoloEnabled || !webcamVideoRef.current || webcamVideoRef.current.readyState < 2) return;
        const ve = webcamVideoRef.current;
        tmpCanvas.width = ve.videoWidth;
        tmpCanvas.height = ve.videoHeight;
        const tctx = tmpCanvas.getContext("2d");
        if (!tctx) return;
        tctx.drawImage(ve, 0, 0);

        try {
          sending = true;
          const blob = await new Promise<Blob | null>((resolve) => tmpCanvas.toBlob(resolve, "image/jpeg", 0.7));
          if (!blob) return;

          const resp = await fetch(`${API_BASE}/api/video/detect`, {
            method: "POST",
            headers: { "Content-Type": "application/octet-stream" },
            body: blob,
          });
          const data = await resp.json();
          if (data.type === "detections") {
            detectionsRef.current = data.detections || [];
            detFrameSizeRef.current = { w: data.frame_width || 0, h: data.frame_height || 0 };
            if (data.inference_ms) setYoloFps((1000 / data.inference_ms).toFixed(1));
          }
        } catch {
          // ignore error
        } finally {
          sending = false;
        }
      }, 200); // 5 Hz
    } catch {
      setNoSignal(true);
      setNoSignalText("CAMERA IN USE OR BLOCKED");
    }
  }, [stopWebcam, syncCanvasSize, yoloEnabled]);

  const handleSourceChange = (val: string) => {
    setSourceMode(val);
    if (val === "udp") {
      stopWebcam();
      setNoSignal(true);
      setNoSignalText(`Waiting for UDP on port ${udpPort}...`);
    } else if (val === "none") {
      stopWebcam();
      setNoSignal(true);
      setNoSignalText("NO SOURCE SELECTED");
      const vc = videoCanvasRef.current;
      if (vc) {
        const ctx = vc.getContext("2d");
        ctx?.fillRect(0, 0, vc.width, vc.height);
      }
    } else {
      startWebcam(val);
    }
  };

  useEffect(() => {
    return () => stopWebcam();
  }, [stopWebcam]);

  // Controls
  const handleFullscreen = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    if (!document.fullscreenElement) {
      container.requestFullscreen().catch(console.warn);
    } else {
      document.exitFullscreen();
    }
  }, []);

  const handleSnapshot = useCallback(() => {
    const vc = videoCanvasRef.current;
    if (!vc) return;
    const tmp = document.createElement("canvas");
    tmp.width = vc.width;
    tmp.height = vc.height;
    const tctx = tmp.getContext("2d");
    if (!tctx) return;
    tctx.drawImage(vc, 0, 0);
    const hudCanvas = containerRef.current?.querySelector<HTMLCanvasElement>(".hud-canvas-overlay");
    if (hudCanvas) tctx.drawImage(hudCanvas, 0, 0);
    const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    const link = document.createElement("a");
    link.download = `snapshot_${ts}.jpg`;
    link.href = tmp.toDataURL("image/jpeg", 0.92);
    link.click();
  }, []);

  const hudTimeStr = useCallback(() => {
    const now = new Date();
    return `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}:${String(now.getSeconds()).padStart(2, "0")}.${String(Math.floor(now.getMilliseconds() / 10)).padStart(2, "0")}`;
  }, []);

  const [hudTime, setHudTime] = useState("--:--:--.--");
  useEffect(() => {
    const iv = setInterval(() => setHudTime(hudTimeStr()), 50);
    return () => clearInterval(iv);
  }, [hudTimeStr]);

  return (
    <div
      className="video-panel"
      id={`${panelId === 1 ? "left" : "right"}-panel`}
      style={{
        "--agent-color": agent.color,
        "--agent-color-rgb": agent.colorRgb,
      } as CSSProperties}
    >
      {/* Video frame */}
      <div className="video-frame" ref={containerRef}>
        <video ref={webcamVideoRef} autoPlay playsInline muted style={{ display: "none" }} />
        <canvas ref={videoCanvasRef} className="video-canvas-main" />
        <HudCanvas
          ref={hudRef}
          showCrosshair={showCrosshair}
          showHUD={showHUD}
          showDetections={showDetections}
        />

        {/* Top-left overlay */}
        <div className="hud-overlay hud-tl">
          <span className="hud-channel">
            CH{String(panelId).padStart(2, "0")} / CAM-{panelId - 1}
          </span>
          <span className="hud-time">{hudTime}</span>
        </div>

        {/* Top-right overlay matching index.html */}
        <div className="hud-overlay hud-tr">
          {!noSignal && <span className="hud-badge is-recording">REC</span>}
          {yoloEnabled && <span className="hud-badge">YOLO ON</span>}
        </div>

        {/* Compact flight/video stats pinned inside the frame edges. */}
        <div className="video-stats video-stats-overlay">
          <div className="video-stats-side video-stats-left">
            <div>fps: <span className="stat-value">{fps}</span></div>
            <div>yolo: <span className="stat-value">{yoloFps}</span></div>
            <div>gsd: <span className="stat-value">{videoStats.gsd}</span></div>
          </div>
          <div className="video-stats-side video-stats-right">
            <div>dist: <span className="stat-value">{videoStats.dist}</span></div>
            <div>uav: <span className="stat-value">{videoStats.uavLoc}</span></div>
            <div>tgt: <span className="stat-value">{videoStats.tgtLoc}</span></div>
          </div>
        </div>

        {/* No signal overlay */}
        {noSignal && (
          <div className="no-signal-overlay">
            <div className="no-signal-inner">
              <svg width="48" height="48" viewBox="0 0 48 48" fill="none" stroke="#555540" strokeWidth="1.5">
                <circle cx="24" cy="24" r="22" />
                <line x1="24" y1="10" x2="14" y2="4" />
                <line x1="24" y1="10" x2="34" y2="4" />
                <line x1="24" y1="10" x2="24" y2="22" />
              </svg>
              <div className="no-signal-title">NO SIGNAL</div>
              <div className="no-signal-detail">{noSignalText}</div>
            </div>
          </div>
        )}

        {/* Controls bar */}
        <div className="video-controls">
          <button className="vid-btn" onClick={handleFullscreen} title="Fullscreen (F)">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="15 3 21 3 21 9" />
              <polyline points="9 21 3 21 3 15" />
              <line x1="21" y1="3" x2="14" y2="10" />
              <line x1="3" y1="21" x2="10" y2="14" />
            </svg>
            FULLSCREEN
          </button>
          <button className="vid-btn" onClick={handleSnapshot} title="Snapshot (S)">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="4" />
              <path d="M20.94 11A9 9 0 1 1 13 3.06" />
            </svg>
            SNAPSHOT
          </button>
          <button className="vid-btn" onClick={() => setShowCrosshair(!showCrosshair)} title="Toggle crosshair">
            ✛ CROSSHAIR
          </button>
          <button className="vid-btn" onClick={() => setShowHUD(!showHUD)} title="Toggle HUD">
            HUD
          </button>
        </div>
      </div>

    </div>
  );
}

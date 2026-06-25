/**
 * video.js — Video WebSocket client
 * ─────────────────────────────────
 * Connects to /ws/video, receives binary JPEG frames, and renders them
 * on the main canvas.  A second HUD canvas draws crosshair and overlay.
 *
 * The same /ws/video channel also carries YOLO detection results as
 * JSON text messages (sent right after the binary frame they describe).
 * Those are parsed here and fed into the bounding-box overlay, which is
 * redrawn every time a new video frame is rendered so boxes always
 * track the frame they belong to.
 *
 * Automatically reconnects with exponential back-off on any disconnect.
 */

(function () {
  'use strict';

  // ─── Canvas Setup ────────────────────────────────────────────────────────
  const videoCanvas = document.getElementById('video-canvas');
  const hudCanvas = document.getElementById('hud-canvas');
  const vCtx = videoCanvas.getContext('2d', { alpha: false });
  const hCtx = hudCanvas.getContext('2d');

  const noSignalEl = document.getElementById('no-signal');
  const hudFpsEl = document.getElementById('hud-fps');
  const hudTimeEl = document.getElementById('hud-time');
  const vidFpsEl = document.getElementById('vid-fps');
  const vidDropsEl = document.getElementById('vid-drops');
  const vidSenderEl = document.getElementById('vid-sender');
  const detFpsEl = document.getElementById('det-fps'); // optional, ok if absent
  const detCountEl = document.getElementById('det-count'); // optional, ok if absent

  let showCrosshair = true;
  let showHUD = true;
  let showDetections = true;

  // ─── FPS counter ─────────────────────────────────────────────────────────
  let frameCount = 0;
  let fps = 0;
  let lastFpsTime = performance.now();

  function measureFps() {
    frameCount++;
    const now = performance.now();
    const elapsed = now - lastFpsTime;
    if (elapsed >= 1000) {
      fps = Math.round(frameCount / (elapsed / 1000));
      frameCount = 0;
      lastFpsTime = now;
      if (hudFpsEl) hudFpsEl.textContent = fps + ' FPS';
      if (vidFpsEl) vidFpsEl.textContent = fps;
    }
  }

  // ─── Canvas resize ───────────────────────────────────────────────────────
  function resizeCanvases() {
    const container = videoCanvas.parentElement;
    const w = container.clientWidth;
    const h = container.clientHeight;
    if (videoCanvas.width !== w || videoCanvas.height !== h) {
      videoCanvas.width = w;
      videoCanvas.height = h;
      hudCanvas.width = w;
      hudCanvas.height = h;
    }
  }

  const resizeObserver = new ResizeObserver(resizeCanvases);
  resizeObserver.observe(videoCanvas.parentElement);
  resizeCanvases();

  // ─── Frame rendering ─────────────────────────────────────────────────────
  let latestBlob = null;
  let rendering = false;

  // Remembers where the last frame was drawn (letterbox offsets + size)
  // so the detection overlay can be redrawn independently of new frames
  // arriving (e.g. if a detection message lands between video frames).
  let lastDraw = { dx: 0, dy: 0, dw: 0, dh: 0, cw: 0, ch: 0 };

  function renderFrame(blob) {
    latestBlob = blob;
    if (!rendering) {
      rendering = true;
      requestAnimationFrame(drawFrame);
    }
  }

  function drawFrame() {
    rendering = false;
    if (!latestBlob) return;
    const blob = latestBlob;
    latestBlob = null;

    resizeCanvases();

    const img = new Image();
    const url = URL.createObjectURL(blob);
    img.onload = () => {
      // Check again inside onload in case the source changed while waiting
      const src = window.GS_camSource ? window.GS_camSource[1] : 'udp';
      if (src !== 'udp') {
        URL.revokeObjectURL(url);
        return;
      }

      const cw = videoCanvas.width;
      const ch = videoCanvas.height;
      // Letterbox/pillarbox to preserve aspect ratio
      const scale = Math.min(cw / img.width, ch / img.height);
      const dw = img.width * scale;
      const dh = img.height * scale;
      const dx = (cw - dw) / 2;
      const dy = (ch - dh) / 2;
      vCtx.fillStyle = '#0a0a08';
      vCtx.fillRect(0, 0, cw, ch);
      vCtx.drawImage(img, dx, dy, dw, dh);
      URL.revokeObjectURL(url);

      lastDraw = { dx, dy, dw, dh, cw, ch };
      drawHUD(dx, dy, dw, dh, cw, ch);
      measureFps();
    };
    img.onerror = () => URL.revokeObjectURL(url);
    img.src = url;
  }

  // ─── HUD / Crosshair ─────────────────────────────────────────────────────
  function drawHUD(dx, dy, dw, dh, cw, ch) {
    hCtx.clearRect(0, 0, cw, ch);
    if (!showHUD) return;
    
    const src = window.GS_camSource ? window.GS_camSource[1] : 'udp';
    if (src === 'none') return;

    const cx = dx + dw / 2;
    const cy = dy + dh / 2;

    if (showCrosshair) drawCrosshair(cx, cy);
    drawCornerBrackets(dx, dy, dw, dh);
    if (showDetections) drawDetections(dx, dy, dw, dh);
    updateHudTime();
  }

  function drawCrosshair(cx, cy) {
    const len = 16;
    const gap = 6;
    const col = '#D5FF40';

    hCtx.strokeStyle = col;
    hCtx.lineWidth = 1;
    hCtx.globalAlpha = 0.8;
    hCtx.beginPath();
    // horizontal
    hCtx.moveTo(cx - len - gap, cy);
    hCtx.lineTo(cx - gap, cy);
    hCtx.moveTo(cx + gap, cy);
    hCtx.lineTo(cx + len + gap, cy);
    // vertical
    hCtx.moveTo(cx, cy - len - gap);
    hCtx.lineTo(cx, cy - gap);
    hCtx.moveTo(cx, cy + gap);
    hCtx.lineTo(cx, cy + len + gap);
    hCtx.stroke();
    // center dot
    hCtx.globalAlpha = 0.6;
    hCtx.fillStyle = col;
    hCtx.beginPath();
    hCtx.arc(cx, cy, 2, 0, Math.PI * 2);
    hCtx.fill();
    hCtx.globalAlpha = 1;
  }

  function drawCornerBrackets(x, y, w, h) {
    const len = 14;
    const col = 'rgba(213,255,64,0.5)';
    hCtx.strokeStyle = col;
    hCtx.lineWidth = 1.5;
    hCtx.beginPath();
    // TL
    hCtx.moveTo(x + len, y);
    hCtx.lineTo(x, y);
    hCtx.lineTo(x, y + len);
    // TR
    hCtx.moveTo(x + w - len, y);
    hCtx.lineTo(x + w, y);
    hCtx.lineTo(x + w, y + len);
    // BL
    hCtx.moveTo(x, y + h - len);
    hCtx.lineTo(x, y + h);
    hCtx.lineTo(x + len, y + h);
    // BR
    hCtx.moveTo(x + w - len, y + h);
    hCtx.lineTo(x + w, y + h);
    hCtx.lineTo(x + w, y + h - len);
    hCtx.stroke();
  }

  function updateHudTime() {
    const now = new Date();
    const hh = String(now.getHours()).padStart(2, '0');
    const mm = String(now.getMinutes()).padStart(2, '0');
    const ss = String(now.getSeconds()).padStart(2, '0');
    const ms = String(Math.floor(now.getMilliseconds() / 10)).padStart(2, '0');
    if (hudTimeEl) hudTimeEl.textContent = `${hh}:${mm}:${ss}.${ms}`;
  }

  // ─── YOLO bounding-box overlay ───────────────────────────────────────────
  // Populated from the JSON "detections" messages on /ws/video; drawn as
  // part of every drawHUD() pass so boxes stay aligned with the current frame.
  let detections = [];
  let detFrameW = 0;
  let detFrameH = 0;
  let lastDetFps = 0;
  let detMsgCount = 0;
  let lastDetFpsT = performance.now();

  function drawDetections(dx, dy, dw, dh) {
    if (!detections.length || !detFrameW || !detFrameH) return;

    const scaleX = dw / detFrameW;
    const scaleY = dh / detFrameH;

    detections.forEach((det) => {
      const { x1, y1, x2, y2, label, conf, color } = det;
      const px1 = dx + x1 * scaleX;
      const py1 = dy + y1 * scaleY;
      const pw = (x2 - x1) * scaleX;
      const ph = (y2 - y1) * scaleY;
      const col = color || '#D5FF40';

      hCtx.strokeStyle = col;
      hCtx.lineWidth = 1.5;
      hCtx.strokeRect(px1, py1, pw, ph);

      const text = `${label} ${Math.round(conf * 100)}%`;
      hCtx.font = "bold 10px 'JetBrains Mono', monospace";
      const textW = hCtx.measureText(text).width;

      hCtx.fillStyle = col;
      hCtx.globalAlpha = 0.85;
      hCtx.fillRect(px1, py1 - 13, textW + 6, 13);
      hCtx.globalAlpha = 1;

      hCtx.fillStyle = '#0a0a08';
      hCtx.fillText(text, px1 + 3, py1 - 3);
    });
  }

  /**
   * Public hook — kept for compatibility with any other caller that wants
   * to push detections in image/canvas coordinates directly (bypassing the
   * WebSocket JSON path). Most of the time detections arrive automatically
   * via the /ws/video text messages handled below.
   */
  window.GS_setDetections = function (dets, frameW, frameH) {
    detections = dets || [];
    detFrameW = frameW || 0;
    detFrameH = frameH || 0;
    drawHUD(lastDraw.dx, lastDraw.dy, lastDraw.dw, lastDraw.dh, lastDraw.cw, lastDraw.ch);
  };

  function handleDetectionMessage(json) {
    console.log('YOLO MSG:', json);
    let msg;
    try {
      msg = JSON.parse(json);
    } catch (_) {
      return;
    }
    console.log('PARSED:', msg);
    if (!msg || msg.type !== 'detections') return;

    detections = msg.detections || [];
    detFrameW = msg.frame_width || 0;
    detFrameH = msg.frame_height || 0;

    if (detCountEl) detCountEl.textContent = detections.length;

    detMsgCount++;
    const now = performance.now();
    const elapsed = now - lastDetFpsT;
    if (elapsed >= 1000) {
      lastDetFps = Math.round((detMsgCount / elapsed) * 1000);
      detMsgCount = 0;
      lastDetFpsT = now;
      if (detFpsEl) detFpsEl.textContent = lastDetFps + ' FPS';
    }

    // Redraw immediately so boxes don't lag behind a detection-only update.
    drawHUD(lastDraw.dx, lastDraw.dy, lastDraw.dw, lastDraw.dh, lastDraw.cw, lastDraw.ch);
  }

  // ─── WebSocket Connection ─────────────────────────────────────────────────
  const WS_URL = `${window.GS_CONFIG.wsProto}://${window.GS_CONFIG.wsHost}/ws/video`;
  let ws = null;
  let backoff = 1000;
  let connected = false;
  let hasFrame = false;

  function connect() {
    ws = new WebSocket(WS_URL);
    ws.binaryType = 'blob';

    ws.onopen = () => {
      console.log('[video] WebSocket connected');
      backoff = 1000;
      connected = true;
      window.GS_log('event', 'video', 'Video WebSocket connected');
    };

    ws.onmessage = (ev) => {
      // Only render UDP frames on panel 1 if it's set to UDP source
      if (ev.data instanceof Blob) {
        const src = window.GS_camSource ? window.GS_camSource[1] : 'udp';
        if (src !== 'udp') return;
        if (!hasFrame) {
          hasFrame = true;
          noSignalEl && noSignalEl.classList.add('hidden');
        }
        renderFrame(ev.data);
      } else if (typeof ev.data === 'string') {
        // YOLO detection JSON rides the same channel as text messages
        handleDetectionMessage(ev.data);
      }
    };

    ws.onclose = () => {
      connected = false;
      hasFrame = false;
      detections = [];
      if (noSignalEl) noSignalEl.classList.remove('hidden');
      window.GS_log('warning', 'video', `Video WebSocket closed — reconnecting in ${backoff / 1000}s`);
      setTimeout(connect, backoff);
      backoff = Math.min(backoff * 2, 16000);
    };

    ws.onerror = (e) => {
      console.warn('[video] WebSocket error', e);
    };
  }

  connect();

  // ─── Button wiring ───────────────────────────────────────────────────────
  document.getElementById('btn-fullscreen')?.addEventListener('click', () => {
    const container = document.getElementById('video-container');
    if (!document.fullscreenElement) {
      container.requestFullscreen().catch(console.warn);
    } else {
      document.exitFullscreen();
    }
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'f' || e.key === 'F') {
      document.getElementById('btn-fullscreen')?.click();
    }
    if (e.key === 's' || e.key === 'S') {
      document.getElementById('btn-snapshot')?.click();
    }
    if (e.key === 'd' || e.key === 'D') {
      document.getElementById('btn-detections')?.click();
    }
  });

  document.getElementById('btn-snapshot')?.addEventListener('click', () => {
    if (!hasFrame) {
      window.GS_log('warning', 'video', 'No frame to snapshot');
      return;
    }
    const link = document.createElement('a');
    const tmp = document.createElement('canvas');
    tmp.width = videoCanvas.width;
    tmp.height = videoCanvas.height;
    const tctx = tmp.getContext('2d');
    tctx.drawImage(videoCanvas, 0, 0);
    tctx.drawImage(hudCanvas, 0, 0); // bake in HUD + bounding boxes
    const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    link.download = `snapshot_${ts}.jpg`;
    link.href = tmp.toDataURL('image/jpeg', 0.92);
    link.click();
    window.GS_log('event', 'video', `Snapshot saved: snapshot_${ts}.jpg`);
  });

  document.getElementById('btn-crosshair')?.addEventListener('click', () => {
    showCrosshair = !showCrosshair;
    window.GS_log('info', 'video', `Crosshair ${showCrosshair ? 'enabled' : 'disabled'}`);
  });

  document.getElementById('btn-hud')?.addEventListener('click', () => {
    showHUD = !showHUD;
    if (!showHUD) {
      hCtx.clearRect(0, 0, hudCanvas.width, hudCanvas.height);
    }
  });

  document.getElementById('btn-detections')?.addEventListener('click', () => {
    showDetections = !showDetections;
    window.GS_log('info', 'video', `YOLO overlay ${showDetections ? 'enabled' : 'disabled'}`);
    drawHUD(lastDraw.dx, lastDraw.dy, lastDraw.dw, lastDraw.dh, lastDraw.cw, lastDraw.ch);
  });

  // ─── Poll video REST stats every 5s ──────────────────────────────────────
  async function pollVideoStats() {
    try {
      const r = await fetch('/api/video/status');
      const d = await r.json();
      if (vidFpsEl) vidFpsEl.textContent = d.fps ?? '--';
      if (vidDropsEl) vidDropsEl.textContent = d.drops ?? 0;
      if (vidSenderEl) vidSenderEl.textContent = d.sender ?? '---';
    } catch (_) {}
  }
  setInterval(pollVideoStats, 5000);
  pollVideoStats();
})();

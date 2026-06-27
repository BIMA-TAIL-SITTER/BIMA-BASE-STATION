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

  // Panel 2 HUD elements
  const hudFpsEl2 = document.getElementById('hud-fps-2');
  const hudTimeEl2 = document.getElementById('hud-time-2');
  const vidFpsEl2 = document.getElementById('vid-fps-2');

  let showCrosshair = true;
  let showHUD = true;
  let showDetections = true;

  // ─── FPS counter ─────────────────────────────────────────────────────────
  let frameCount = 0;
  let fps = 0;
  let lastFpsTime = performance.now();

  // Panel 2 FPS counter (independent)
  let frameCount2 = 0;
  let fps2 = 0;
  let lastFpsTime2 = performance.now();

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

  function measureFps2() {
    frameCount2++;
    const now = performance.now();
    const elapsed = now - lastFpsTime2;
    if (elapsed >= 1000) {
      fps2 = Math.round(frameCount2 / (elapsed / 1000));
      frameCount2 = 0;
      lastFpsTime2 = now;
      if (hudFpsEl2) hudFpsEl2.textContent = fps2 + ' FPS';
      if (vidFpsEl2) vidFpsEl2.textContent = fps2;
    }
  }

  function updateHudTime2() {
    const now = new Date();
    const hh = String(now.getHours()).padStart(2, '0');
    const mm = String(now.getMinutes()).padStart(2, '0');
    const ss = String(now.getSeconds()).padStart(2, '0');
    const ms = String(Math.floor(now.getMilliseconds() / 10)).padStart(2, '0');
    if (hudTimeEl2) hudTimeEl2.textContent = `${hh}:${mm}:${ss}.${ms}`;
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
  const panelState = {
    1: { detections: [], detFrameW: 0, detFrameH: 0, lastDraw: { dx: 0, dy: 0, dw: 0, dh: 0, cw: 0, ch: 0 } },
    2: { detections: [], detFrameW: 0, detFrameH: 0, lastDraw: { dx: 0, dy: 0, dw: 0, dh: 0, cw: 0, ch: 0 } }
  };

  function drawHUD(panelId, dx, dy, dw, dh, cw, ch) {
    const ctx = panelId === 1 ? hCtx : document.getElementById('hud-canvas-2').getContext('2d');
    if (!ctx) return;
    
    ctx.clearRect(0, 0, cw, ch);
    if (!showHUD) return;
    
    const src = window.GS_camSource ? window.GS_camSource[panelId] : 'udp';
    if (src === 'none') return;

    const cx = dx + dw / 2;
    const cy = dy + dh / 2;

    if (showCrosshair) drawCrosshair(ctx, cx, cy);
    drawCornerBrackets(ctx, dx, dy, dw, dh);
    if (showDetections) drawDetections(panelId, ctx, dx, dy, dw, dh);
    
    if (panelId === 1) updateHudTime();
    else updateHudTime2();
  }

  function drawCrosshair(ctx, cx, cy) {
    const len = 16;
    const gap = 6;
    const col = '#D5FF40';

    ctx.strokeStyle = col;
    ctx.lineWidth = 1;
    ctx.globalAlpha = 0.8;
    ctx.beginPath();
    // horizontal
    ctx.moveTo(cx - len - gap, cy);
    ctx.lineTo(cx - gap, cy);
    ctx.moveTo(cx + gap, cy);
    ctx.lineTo(cx + len + gap, cy);
    // vertical
    ctx.moveTo(cx, cy - len - gap);
    ctx.lineTo(cx, cy - gap);
    ctx.moveTo(cx, cy + gap);
    ctx.lineTo(cx, cy + len + gap);
    ctx.stroke();
    // center dot
    ctx.globalAlpha = 0.6;
    ctx.fillStyle = col;
    ctx.beginPath();
    ctx.arc(cx, cy, 2, 0, Math.PI * 2);
    ctx.fill();
    ctx.globalAlpha = 1;
  }

  function drawCornerBrackets(ctx, x, y, w, h) {
    const len = 14;
    const col = 'rgba(213,255,64,0.5)';
    ctx.strokeStyle = col;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    // TL
    ctx.moveTo(x + len, y);
    ctx.lineTo(x, y);
    ctx.lineTo(x, y + len);
    // TR
    ctx.moveTo(x + w - len, y);
    ctx.lineTo(x + w, y);
    ctx.lineTo(x + w, y + len);
    // BL
    ctx.moveTo(x, y + h - len);
    ctx.lineTo(x, y + h);
    ctx.lineTo(x + len, y + h);
    // BR
    ctx.moveTo(x + w - len, y + h);
    ctx.lineTo(x + w, y + h);
    ctx.lineTo(x + w, y + h - len);
    ctx.stroke();
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
  let lastDetFps = 0;
  let detMsgCount = 0;
  let lastDetFpsT = performance.now();

  function drawDetections(panelId, ctx, dx, dy, dw, dh) {
    const state = panelState[panelId];
    if (!state.detections.length || !state.detFrameW || !state.detFrameH) return;

    const scaleX = dw / state.detFrameW;
    const scaleY = dh / state.detFrameH;

    state.detections.forEach((det) => {
      const { x1, y1, x2, y2, label, conf, color } = det;
      const px1 = dx + x1 * scaleX;
      const py1 = dy + y1 * scaleY;
      const pw = (x2 - x1) * scaleX;
      const ph = (y2 - y1) * scaleY;
      const col = color || '#D5FF40';

      ctx.strokeStyle = col;
      ctx.lineWidth = 1.5;
      ctx.strokeRect(px1, py1, pw, ph);

      const text = `${label} ${Math.round(conf * 100)}%`;
      ctx.font = "bold 10px 'JetBrains Mono', monospace";
      const textW = ctx.measureText(text).width;

      ctx.fillStyle = col;
      ctx.globalAlpha = 0.85;
      ctx.fillRect(px1, py1 - 13, textW + 6, 13);
      ctx.globalAlpha = 1;

      ctx.fillStyle = '#0a0a08';
      ctx.fillText(text, px1 + 3, py1 - 3);

      // ── Centroid dot ──────────────────────────────────────────
      if (det.cx !== undefined && det.cy !== undefined) {
        const pcx = dx + det.cx * scaleX;
        const pcy = dy + det.cy * scaleY;
        const dotR = 5;

        // Filled dot
        ctx.beginPath();
        ctx.arc(pcx, pcy, dotR, 0, Math.PI * 2);
        ctx.fillStyle = col;
        ctx.globalAlpha = 0.9;
        ctx.fill();

        // Outer ring
        ctx.beginPath();
        ctx.arc(pcx, pcy, dotR + 2, 0, Math.PI * 2);
        ctx.strokeStyle = col;
        ctx.lineWidth = 1;
        ctx.globalAlpha = 0.5;
        ctx.stroke();

        // Mini crosshair
        const cLen = 10;
        ctx.beginPath();
        ctx.globalAlpha = 0.6;
        ctx.strokeStyle = col;
        ctx.lineWidth = 0.8;
        ctx.moveTo(pcx - cLen, pcy);
        ctx.lineTo(pcx + cLen, pcy);
        ctx.moveTo(pcx, pcy - cLen);
        ctx.lineTo(pcx, pcy + cLen);
        ctx.stroke();

        ctx.globalAlpha = 1;
      }
    });

    // Update bottom stats for the first detected object (if any)
    const cxEl = document.getElementById(panelId === 1 ? 'vid-cx' : 'vid-cx-2');
    const cyEl = document.getElementById(panelId === 1 ? 'vid-cy' : 'vid-cy-2');
    const distEl = document.getElementById(panelId === 1 ? 'vid-dist' : 'vid-dist-2');
    if (cxEl && cyEl && distEl) {
      if (state.detections[0] && state.detections[0].cx !== undefined) {
        const cx = state.detections[0].cx;
        const cy = state.detections[0].cy;
        cxEl.textContent = cx.toFixed(1);
        cyEl.textContent = cy.toFixed(1);

        // Calculate distance from center of the original frame
        const center_x = state.detFrameW / 2;
        const center_y = state.detFrameH / 2;
        const dist = Math.sqrt(Math.pow(cx - center_x, 2) + Math.pow(cy - center_y, 2));
        distEl.textContent = dist.toFixed(1);
      } else {
        cxEl.textContent = '--';
        cyEl.textContent = '--';
        distEl.textContent = '--';
      }
    }
  }

  // --- Multi-panel rendering helper ---
  function renderFrameToPanel(panelId, blob) {
    const vc = panelId === 1 ? videoCanvas : document.getElementById('video-canvas-2');
    const hc = panelId === 1 ? hudCanvas : document.getElementById('hud-canvas-2');
    if (!vc || !hc) return;

    const img = new Image();
    const url = URL.createObjectURL(blob);
    img.onload = () => {
      // Re-check source just in case it changed while decoding
      if (window.GS_camSource[panelId] !== 'udp') {
        URL.revokeObjectURL(url);
        return;
      }

      // Sync canvas size to container (prevents blurry rendering)
      const container = vc.parentElement;
      if (container) {
        const cw = container.clientWidth;
        const ch = container.clientHeight;
        if (vc.width !== cw || vc.height !== ch) {
          vc.width = cw;
          vc.height = ch;
          hc.width = cw;
          hc.height = ch;
        }
      }

      const cw = vc.width;
      const ch = vc.height;
      const scale = Math.min(cw / img.width, ch / img.height);
      const dw = img.width * scale;
      const dh = img.height * scale;
      const dx = (cw - dw) / 2;
      const dy = (ch - dh) / 2;

      const vCtx2 = vc.getContext('2d', { alpha: false });
      vCtx2.fillStyle = '#0a0a08';
      vCtx2.fillRect(0, 0, cw, ch);
      vCtx2.drawImage(img, dx, dy, dw, dh);
      URL.revokeObjectURL(url);

      panelState[panelId].lastDraw = { dx, dy, dw, dh, cw, ch };
      drawHUD(panelId, dx, dy, dw, dh, cw, ch);
      
      if (panelId === 1) {
        measureFps();
      } else {
        measureFps2();
        updateHudTime2();
      }
    };
    img.onerror = () => URL.revokeObjectURL(url);
    img.src = url;
  }

  /**
   * Public hook — kept for compatibility with any other caller that wants
   * to push detections in image/canvas coordinates directly (bypassing the
   * WebSocket JSON path). Most of the time detections arrive automatically
   * via the /ws/video text messages handled below.
   */
  window.GS_setDetections = function (dets, frameW, frameH) {
    // Legacy support, default to panel 1
    panelState[1].detections = dets || [];
    panelState[1].detFrameW = frameW || 0;
    panelState[1].detFrameH = frameH || 0;
    const ld = panelState[1].lastDraw;
    drawHUD(1, ld.dx, ld.dy, ld.dw, ld.dh, ld.cw, ld.ch);
  };

  function handleDetectionMessage(port, json) {
    console.log('YOLO MSG:', json);
    let msg;
    try {
      msg = JSON.parse(json);
    } catch (_) {
      return;
    }
    console.log('PARSED:', msg);
    if (!msg || msg.type !== 'detections') return;

    const incomingDetections = msg.detections || [];
    const incomingFrameW = msg.frame_width || 0;
    const incomingFrameH = msg.frame_height || 0;

    [1, 2].forEach(pId => {
      if (window.GS_camSource[pId] === 'udp' && window.GS_udpPorts[pId] === port) {
        panelState[pId].detections = incomingDetections;
        panelState[pId].detFrameW = incomingFrameW;
        panelState[pId].detFrameH = incomingFrameH;
        
        if (pId === 1 && detCountEl) detCountEl.textContent = incomingDetections.length;
        
        // Update YOLO FPS from inference_ms
        const yoloFpsEl = document.getElementById(pId === 1 ? 'vid-yolo-fps' : 'vid-yolo-fps-2');
        if (yoloFpsEl && msg.inference_ms) {
          const fpsYolo = 1000 / msg.inference_ms;
          yoloFpsEl.textContent = fpsYolo.toFixed(1);
        }

        const ld = panelState[pId].lastDraw;
        drawHUD(pId, ld.dx, ld.dy, ld.dw, ld.dh, ld.cw, ld.ch);
      }
    });

    // Update global YOLO FPS
    detMsgCount++;
    const now = performance.now();
    const elapsed = now - lastDetFpsT;
    if (elapsed >= 1000) {
      lastDetFps = Math.round((detMsgCount / elapsed) * 1000);
      detMsgCount = 0;
      lastDetFpsT = now;
      if (detFpsEl) detFpsEl.textContent = lastDetFps + ' FPS';
    }
  }

  // ─── WebSocket Connections (by Port) ────────────────────────────────────
  const websockets = {};
  
  function connectPort(port) {
    if (websockets[port]) return;
    
    const url = `${window.GS_CONFIG.wsProto}://${window.GS_CONFIG.wsHost}/ws/video/${port}`;
    const ws = new WebSocket(url);
    ws.binaryType = 'blob';
    
    let backoff = 1000;
    
    ws.onopen = () => {
      console.log(`[video] WebSocket connected to port ${port}`);
      backoff = 1000;
      window.GS_log('event', 'video', `Video WebSocket connected (port ${port})`);
    };
    
    ws.onmessage = (ev) => {
      if (ev.data instanceof Blob) {
        // Hide no-signal if this is the first frame
        [1, 2].forEach(pId => {
          if (window.GS_camSource[pId] === 'udp' && window.GS_udpPorts[pId] === port) {
             const ns = document.getElementById(pId === 1 ? 'no-signal' : 'no-signal-2');
             if (ns) ns.classList.add('hidden');
             renderFrameToPanel(pId, ev.data);
          }
        });
      } else if (typeof ev.data === 'string') {
        handleDetectionMessage(port, ev.data);
      }
    };
    
    ws.onclose = () => {
      console.warn(`[video] WebSocket closed (port ${port}), reconnecting...`);
      [1, 2].forEach(pId => {
         if (window.GS_camSource[pId] === 'udp' && window.GS_udpPorts[pId] === port) {
             const ns = document.getElementById(pId === 1 ? 'no-signal' : 'no-signal-2');
             if (ns) ns.classList.remove('hidden');
         }
      });
      delete websockets[port];
      setTimeout(() => connectPort(port), backoff);
      backoff = Math.min(backoff * 2, 16000);
    };
    
    websockets[port] = ws;
  }
  
  function disconnectPort(port) {
    if (websockets[port]) {
      websockets[port].onclose = null; // prevent reconnect
      websockets[port].close();
      delete websockets[port];
    }
  }

  // Listen to camera.js events
  window.addEventListener('gs-source-change', (e) => {
    const { panelId, source, port } = e.detail;
    
    // Evaluate needed ports
    const neededPorts = new Set();
    if (window.GS_camSource[1] === 'udp') neededPorts.add(window.GS_udpPorts[1]);
    if (window.GS_camSource[2] === 'udp') neededPorts.add(window.GS_udpPorts[2]);
    
    // Connect new ones
    neededPorts.forEach(p => {
      if (!websockets[p]) connectPort(p);
    });
    
    // Disconnect old ones
    Object.keys(websockets).forEach(pStr => {
      const p = parseInt(pStr);
      if (!neededPorts.has(p)) disconnectPort(p);
    });
  });

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
    [1, 2].forEach(pId => {
      const ld = panelState[pId].lastDraw;
      drawHUD(pId, ld.dx, ld.dy, ld.dw, ld.dh, ld.cw, ld.ch);
    });
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

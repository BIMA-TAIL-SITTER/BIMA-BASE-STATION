/**
 * camera.js — Camera source manager with YOLO detection
 * ──────────────────────────────────────────────────────
 * Enumerates available cameras (webcam, phone via USB, etc.)
 * and populates the source selectors for both video panels.
 * Handles switching between UDP stream and local camera devices.
 * Sends webcam frames to /api/video/detect for YOLO processing
 * and draws bounding boxes on both panels.
 */

(function () {
  'use strict';

  const select1 = document.getElementById('cam-source-1');
  const select2 = document.getElementById('cam-source-2');
  const portInput1 = document.getElementById('udp-port-1');
  const portInput2 = document.getElementById('udp-port-2');
  const jsonInput1 = document.getElementById('json-port-1');
  const jsonInput2 = document.getElementById('json-port-2');
  const videoEl1 = document.getElementById('webcam-video-1');
  const videoEl2 = document.getElementById('webcam-video-2');
  const canvas1 = document.getElementById('video-canvas');
  const canvas2 = document.getElementById('video-canvas-2');
  const hudCanvas2 = document.getElementById('hud-canvas-2');
  const noSignal2 = document.getElementById('no-signal-2');

  // Track active streams per panel
  const activeStreams = { 1: null, 2: null };
  // Track animation frame IDs per panel
  const animFrames = { 1: null, 2: null };
  // Track YOLO intervals per panel
  const yoloIntervals = { 1: null, 2: null };
  // Track latest detections per panel
  const panelDetections = { 1: [], 2: [] };
  const panelDetFrameSize = { 1: { w: 0, h: 0 }, 2: { w: 0, h: 0 } };

  // ─── Enumerate cameras ─────────────────────────────────────────────────
  async function enumerateCameras() {
    // Clear selects first to prevent duplicates if HTML has initial values
    select1.innerHTML = '';
    select2.innerHTML = '';

    try {
      // Request permission first (needed to get device labels)
      try {
        const tempStream = await navigator.mediaDevices.getUserMedia({ video: true });
        tempStream.getTracks().forEach(t => t.stop());
      } catch (e) {
        console.warn('[camera] getUserMedia failed, trying to enumerate anyway:', e);
      }

      const devices = await navigator.mediaDevices.enumerateDevices();
      const cameras = devices.filter(d => d.kind === 'videoinput');

      // Populate both selects
      cameras.forEach((cam, i) => {
        const label = cam.label || `Camera ${i + 1}`;
        const opt1 = new Option(label, cam.deviceId);
        const opt2 = new Option(label, cam.deviceId);
        select1.appendChild(opt1);
        select2.appendChild(opt2);
      });

      window.GS_log('info', 'video', `Found ${cameras.length} camera(s)`);
    } catch (err) {
      console.warn('[camera] Could not enumerate cameras:', err);
      window.GS_log('warning', 'video', 'Camera enumeration failed: ' + err.message);
    } finally {
      // Add standard options to BOTH
      select1.appendChild(new Option('UDP Stream', 'udp'));
      select1.appendChild(new Option('No Source', 'none'));
      select1.value = 'none';

      select2.appendChild(new Option('UDP Stream', 'udp'));
      select2.appendChild(new Option('No Source', 'none'));
      select2.value = 'none';

      // Trigger change event so the correct text ('NO SOURCE SELECTED') appears on load
      select1.dispatchEvent(new Event('change'));
      select2.dispatchEvent(new Event('change'));
    }
  }

  // ─── YOLO detection for webcam panels ──────────────────────────────────
  function startYoloForPanel(panelId) {
    stopYoloForPanel(panelId);

    const canvas = panelId === 1 ? canvas1 : canvas2;
    const tmpCanvas = document.createElement('canvas');
    let sending = false;

    yoloIntervals[panelId] = setInterval(async () => {
      if (sending) return; // skip if previous request still in-flight
      if (!activeStreams[panelId]) return;

      const yoloToggle = document.getElementById('yolo-toggle');
      const isYoloOn = yoloToggle ? yoloToggle.checked : true;
      
      if (!isYoloOn) {
        // YOLO is OFF: clear old detections if any, and skip fetching
        if (panelDetections[panelId] && panelDetections[panelId].length > 0) {
          console.log(`[camera] Panel ${panelId} YOLO is OFF. Clearing detections.`);
          panelDetections[panelId] = [];
        }
        return;
      }

      const videoEl = panelId === 1 ? videoEl1 : videoEl2;
      if (!videoEl || videoEl.readyState < 2) return;

      // Capture frame from webcam video element
      tmpCanvas.width = videoEl.videoWidth;
      tmpCanvas.height = videoEl.videoHeight;
      const tmpCtx = tmpCanvas.getContext('2d');
      tmpCtx.drawImage(videoEl, 0, 0);

      try {
        sending = true;
        const blob = await new Promise(resolve =>
          tmpCanvas.toBlob(resolve, 'image/jpeg', 0.7)
        );
        if (!blob) { sending = false; return; }

        const resp = await fetch('/api/video/detect', {
          method: 'POST',
          headers: { 'Content-Type': 'application/octet-stream' },
          body: blob,
        });
        const data = await resp.json();

        if (data.type === 'detections') {
          console.log(`[camera] Panel ${panelId} YOLO:`, data.count, 'detections');
          panelDetections[panelId] = data.detections || [];
          panelDetFrameSize[panelId] = {
            w: data.frame_width || 0,
            h: data.frame_height || 0,
          };

          // Update YOLO FPS
          const yoloFpsEl = document.getElementById(panelId === 1 ? 'vid-yolo-fps' : 'vid-yolo-fps-2');
          if (yoloFpsEl && data.inference_ms) {
            const fpsYolo = 1000 / data.inference_ms;
            yoloFpsEl.textContent = fpsYolo.toFixed(1);
          }
        } else {
          console.warn(`[camera] Panel ${panelId} YOLO error:`, data);
          panelDetections[panelId] = { error: data.error || data.detail || 'Unknown API Error' };
        }
      } catch (err) {
        console.warn('[camera] YOLO detect error:', err);
        panelDetections[panelId] = { error: 'Network/Fetch Error' };
      } finally {
        sending = false;
      }
    }, 33); // ~5 FPS YOLO detection
  }

  function stopYoloForPanel(panelId) {
    if (yoloIntervals[panelId]) {
      clearInterval(yoloIntervals[panelId]);
      yoloIntervals[panelId] = null;
    }
    panelDetections[panelId] = [];
  }

  // ─── Draw YOLO bounding boxes on webcam panel ─────────────────────────
  function drawWebcamDetections(panelId, dx, dy, dw, dh) {
    const detections = panelDetections[panelId];
    const frameSize = panelDetFrameSize[panelId];
    if (!detections || (!detections.length && !detections.error) || !frameSize.w || !frameSize.h) return;

    // Get the correct HUD canvas for the panel
    const hudCanvas = panelId === 1 ? document.getElementById('hud-canvas') : hudCanvas2;
    if (!hudCanvas) return;

    const hudCtx = hudCanvas.getContext('2d');

    if (detections.error) {
      hudCtx.fillStyle = 'red';
      hudCtx.font = 'bold 14px monospace';
      hudCtx.fillText(`YOLO Error: ${detections.error}`, 10, 20);
      hudCtx.fillText(`Did you restart the backend?`, 10, 40);
      return;
    }

    if (!detections.length || !frameSize.w || !frameSize.h) return;

    const scaleX = dw / frameSize.w;
    const scaleY = dh / frameSize.h;

    detections.forEach((det) => {
      const { x1, y1, x2, y2, label, conf, color } = det;
      const px1 = dx + x1 * scaleX;
      const py1 = dy + y1 * scaleY;
      const pw = (x2 - x1) * scaleX;
      const ph = (y2 - y1) * scaleY;
      const col = color || '#ffffff';

      hudCtx.strokeStyle = col;
      hudCtx.lineWidth = 1.5;
      hudCtx.strokeRect(px1, py1, pw, ph);

      const text = `${label} ${Math.round(conf * 1000) / 10}%`;
      hudCtx.font = "bold 10px 'JetBrains Mono', monospace";
      const textW = hudCtx.measureText(text).width;

      hudCtx.fillStyle = col;
      hudCtx.globalAlpha = 0.85;
      hudCtx.fillRect(px1, py1 - 13, textW + 6, 13);
      hudCtx.globalAlpha = 1;

      hudCtx.fillStyle = '#0a0a08';
      hudCtx.fillText(text, px1 + 3, py1 - 3);

      // ── Centroid dot ──────────────────────────────────────────
      if (det.cx !== undefined && det.cy !== undefined) {
        const pcx = dx + det.cx * scaleX;
        const pcy = dy + det.cy * scaleY;
        const dotR = 5;

        // Filled dot
        hudCtx.beginPath();
        hudCtx.arc(pcx, pcy, dotR, 0, Math.PI * 2);
        hudCtx.fillStyle = col;
        hudCtx.globalAlpha = 0.9;
        hudCtx.fill();

        // Outer ring
        hudCtx.beginPath();
        hudCtx.arc(pcx, pcy, dotR + 2, 0, Math.PI * 2);
        hudCtx.strokeStyle = col;
        hudCtx.lineWidth = 1;
        hudCtx.globalAlpha = 0.5;
        hudCtx.stroke();

        // Mini crosshair
        const cLen = 10;
        hudCtx.beginPath();
        hudCtx.globalAlpha = 0.6;
        hudCtx.strokeStyle = col;
        hudCtx.lineWidth = 0.8;
        hudCtx.moveTo(pcx - cLen, pcy);
        hudCtx.lineTo(pcx + cLen, pcy);
        hudCtx.moveTo(pcx, pcy - cLen);
        hudCtx.lineTo(pcx, pcy + cLen);
        hudCtx.stroke();

        hudCtx.globalAlpha = 1;
      }
    });

    // Update bottom stats for the first detected object (if any)
    const cxEl = document.getElementById(panelId === 1 ? 'vid-cx' : 'vid-cx-2');
    const cyEl = document.getElementById(panelId === 1 ? 'vid-cy' : 'vid-cy-2');
    const distEl = document.getElementById(panelId === 1 ? 'vid-dist' : 'vid-dist-2');
    if (cxEl && cyEl && distEl) {
      if (detections[0] && detections[0].cx !== undefined) {
        const cx = detections[0].cx;
        const cy = detections[0].cy;
        cxEl.textContent = cx.toFixed(1);
        cyEl.textContent = cy.toFixed(1);

        // Calculate distance from center of the original frame
        // (assuming frameSize.w and frameSize.h are the dimensions of the original video)
        const center_x = frameSize.w / 2;
        const center_y = frameSize.h / 2;
        const dist = Math.sqrt(Math.pow(cx - center_x, 2) + Math.pow(cy - center_y, 2));
        distEl.textContent = dist.toFixed(1);
      } else {
        cxEl.textContent = '--';
        cyEl.textContent = '--';
        distEl.textContent = '--';
      }
    }
  }

  // ─── Start webcam stream ───────────────────────────────────────────────
  async function startWebcam(panelId, deviceId) {
    const videoEl = panelId === 1 ? videoEl1 : videoEl2;
    const canvas = panelId === 1 ? canvas1 : canvas2;
    const noSignal = panelId === 1 ? document.getElementById('no-signal') : noSignal2;
    const noSignalText = document.getElementById(`no-signal-text-${panelId}`);

    // Stop existing stream if any
    stopWebcam(panelId);

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { deviceId: { exact: deviceId } }
      });
      activeStreams[panelId] = stream;
      videoEl.srcObject = stream;
      videoEl.play();

      // Hide no-signal overlay
      if (noSignal) noSignal.classList.add('hidden');

      // Setup HUD canvas for panel 2
      if (panelId === 2 && hudCanvas2) {
        const container = canvas.parentElement;
        hudCanvas2.width = container.clientWidth;
        hudCanvas2.height = container.clientHeight;
      }

      // Render webcam frames to canvas
      const ctx = canvas.getContext('2d', { alpha: false });

      function drawWebcam() {
        if (!activeStreams[panelId]) return;

        const container = canvas.parentElement;
        const w = container.clientWidth;
        const h = container.clientHeight;
        if (canvas.width !== w || canvas.height !== h) {
          canvas.width = w;
          canvas.height = h;
          // Sync HUD canvas for panel 2
          if (panelId === 2 && hudCanvas2) {
            hudCanvas2.width = w;
            hudCanvas2.height = h;
          }
        }

        // Letterbox
        const vw = videoEl.videoWidth || 1;
        const vh = videoEl.videoHeight || 1;
        const scale = Math.min(w / vw, h / vh);
        const dw = vw * scale;
        const dh = vh * scale;
        const dx = (w - dw) / 2;
        const dy = (h - dh) / 2;

        ctx.fillStyle = '#0a0a08';
        ctx.fillRect(0, 0, w, h);
        if (videoEl.readyState >= 2) {
          ctx.drawImage(videoEl, dx, dy, dw, dh);
        }

        // Draw YOLO detections and Crosshair
        const hudCanvas = panelId === 1 ? document.getElementById('hud-canvas') : hudCanvas2;
        if (hudCanvas) {
          const hudCtx = hudCanvas.getContext('2d');
          hudCtx.clearRect(0, 0, w, h);

          // ── Calculate frame center ──
          const center_frame_x = dx + dw / 2;
          const center_frame_y = dy + dh / 2;

          // ── Draw Crosshair ──
          const cLen = 16;
          const gap = 6;
          const col = '#D5FF40';

          hudCtx.strokeStyle = col;
          hudCtx.lineWidth = 1;
          hudCtx.globalAlpha = 0.8;
          hudCtx.beginPath();
          // horizontal
          hudCtx.moveTo(center_frame_x - cLen - gap, center_frame_y);
          hudCtx.lineTo(center_frame_x - gap, center_frame_y);
          hudCtx.moveTo(center_frame_x + gap, center_frame_y);
          hudCtx.lineTo(center_frame_x + cLen + gap, center_frame_y);
          // vertical
          hudCtx.moveTo(center_frame_x, center_frame_y - cLen - gap);
          hudCtx.lineTo(center_frame_x, center_frame_y - gap);
          hudCtx.moveTo(center_frame_x, center_frame_y + gap);
          hudCtx.lineTo(center_frame_x, center_frame_y + cLen + gap);
          hudCtx.stroke();

          // center dot
          hudCtx.globalAlpha = 0.6;
          hudCtx.fillStyle = col;
          hudCtx.beginPath();
          hudCtx.arc(center_frame_x, center_frame_y, 2, 0, Math.PI * 2);
          hudCtx.fill();
          hudCtx.globalAlpha = 1;

          drawWebcamDetections(panelId, dx, dy, dw, dh);
        }

        animFrames[panelId] = requestAnimationFrame(drawWebcam);
      }

      drawWebcam();

      // Start YOLO detection for this panel
      startYoloForPanel(panelId);

      window.GS_log('event', 'video', `Panel ${panelId}: Webcam started with YOLO`);
    } catch (err) {
      console.warn('[camera] Failed to start webcam:', err);
      window.GS_log('warning', 'video', `Panel ${panelId}: Webcam error: ${err.message}`);

      // Update the overlay to show the camera error
      if (noSignal) noSignal.classList.remove('hidden');
      if (noSignalText) noSignalText.textContent = 'CAMERA IN USE OR BLOCKED';
    }
  }

  // ─── Stop webcam stream ────────────────────────────────────────────────
  function stopWebcam(panelId) {
    stopYoloForPanel(panelId);
    if (activeStreams[panelId]) {
      activeStreams[panelId].getTracks().forEach(t => t.stop());
      activeStreams[panelId] = null;
    }
    if (animFrames[panelId]) {
      cancelAnimationFrame(animFrames[panelId]);
      animFrames[panelId] = null;
    }
    const videoEl = panelId === 1 ? videoEl1 : videoEl2;
    if (videoEl) videoEl.srcObject = null;
  }

  // ─── Source change handlers ────────────────────────────────────────────
  // Expose current source mode so video.js knows whether to render UDP frames
  window.GS_camSource = { 1: 'none', 2: 'none' };
  window.GS_udpPorts = { 1: 1, 2: 3 };
  window.GS_jsonPorts = { 1: 2, 2: 4 };

  function dispatchSourceChange(panelId, source, port, jsonPort) {
    const event = new CustomEvent('gs-source-change', {
      detail: { panelId, source, port, jsonPort }
    });
    window.dispatchEvent(event);
  }

  portInput1.addEventListener('change', () => {
    window.GS_udpPorts[1] = parseInt(portInput1.value) || 1;
    if (window.GS_camSource[1] === 'udp') {
      dispatchSourceChange(1, 'udp', window.GS_udpPorts[1], window.GS_jsonPorts[1]);
    }
  });

  jsonInput1.addEventListener('change', () => {
    window.GS_jsonPorts[1] = parseInt(jsonInput1.value) || 2;
    if (window.GS_camSource[1] === 'udp') {
      dispatchSourceChange(1, 'udp', window.GS_udpPorts[1], window.GS_jsonPorts[1]);
    }
  });

  portInput2.addEventListener('change', () => {
    window.GS_udpPorts[2] = parseInt(portInput2.value) || 3;
    if (window.GS_camSource[2] === 'udp') {
      dispatchSourceChange(2, 'udp', window.GS_udpPorts[2], window.GS_jsonPorts[2]);
    }
  });

  jsonInput2.addEventListener('change', () => {
    window.GS_jsonPorts[2] = parseInt(jsonInput2.value) || 4;
    if (window.GS_camSource[2] === 'udp') {
      dispatchSourceChange(2, 'udp', window.GS_udpPorts[2], window.GS_jsonPorts[2]);
    }
  });

  select1.addEventListener('change', () => {
    const val = select1.value;
    window.GS_camSource[1] = val;

    const noSignal1 = document.getElementById('no-signal');
    const noSignalText1 = document.getElementById('no-signal-text-1');

    if (val === 'udp') {
      portInput1.style.display = 'inline-block';
      jsonInput1.style.display = 'inline-block';
      stopWebcam(1);
      // UDP rendering + YOLO handled by video.js
      if (noSignal1) noSignal1.classList.remove('hidden');
      if (noSignalText1) noSignalText1.textContent = `Waiting for UDP on port ${window.GS_udpPorts[1]}...`;
      dispatchSourceChange(1, 'udp', window.GS_udpPorts[1], window.GS_jsonPorts[1]);
    } else if (val === 'none') {
      portInput1.style.display = 'none';
      jsonInput1.style.display = 'none';
      stopWebcam(1);
      const ctx = canvas1.getContext('2d');
      ctx.fillStyle = '#0a0a08';
      ctx.fillRect(0, 0, canvas1.width, canvas1.height);
      if (noSignal1) noSignal1.classList.remove('hidden');
      if (noSignalText1) noSignalText1.textContent = 'NO SOURCE SELECTED';
      dispatchSourceChange(1, 'none', null, null);
    } else {
      portInput1.style.display = 'none';
      jsonInput1.style.display = 'none';
      if (noSignal1) noSignal1.classList.remove('hidden');
      if (noSignalText1) noSignalText1.textContent = 'Starting camera...';
      startWebcam(1, val);
      dispatchSourceChange(1, val, null, null);
    }
  });

  select2.addEventListener('change', () => {
    const val = select2.value;
    window.GS_camSource[2] = val;

    const noSignalText2 = document.getElementById('no-signal-text-2');

    if (val === 'udp') {
      portInput2.style.display = 'inline-block';
      jsonInput2.style.display = 'inline-block';
      stopWebcam(2);
      if (noSignal2) noSignal2.classList.remove('hidden');
      if (noSignalText2) noSignalText2.textContent = `Waiting for UDP on port ${window.GS_udpPorts[2]}...`;
      dispatchSourceChange(2, 'udp', window.GS_udpPorts[2], window.GS_jsonPorts[2]);
    } else if (val === 'none') {
      portInput2.style.display = 'none';
      jsonInput2.style.display = 'none';
      stopWebcam(2);
      if (noSignal2) noSignal2.classList.remove('hidden');
      const ctx = canvas2.getContext('2d');
      ctx.fillStyle = '#0a0a08';
      ctx.fillRect(0, 0, canvas2.width, canvas2.height);
      if (noSignalText2) noSignalText2.textContent = 'NO SOURCE SELECTED';
      dispatchSourceChange(2, 'none', null, null);
    } else {
      portInput2.style.display = 'none';
      jsonInput2.style.display = 'none';
      if (noSignal2) noSignal2.classList.remove('hidden');
      if (noSignalText2) noSignalText2.textContent = 'Starting camera...';
      startWebcam(2, val);
      dispatchSourceChange(2, val, null, null);
    }
  });

  // ─── Init ──────────────────────────────────────────────────────────────
  enumerateCameras();

})();

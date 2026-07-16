"use client";

import { useRef, useCallback, useImperativeHandle, forwardRef } from "react";
import type { Detection, PanelDrawState } from "@/types/video";

export interface HudCanvasHandle {
  drawHUD: (draw: PanelDrawState, detections: Detection[], detFrameW: number, detFrameH: number) => void;
  clear: () => void;
}

interface HudCanvasProps {
  showCrosshair: boolean;
  showHUD: boolean;
  showDetections: boolean;
}

export const HudCanvas = forwardRef<HudCanvasHandle, HudCanvasProps>(
  function HudCanvas({ showCrosshair, showHUD, showDetections }, ref) {
    const canvasRef = useRef<HTMLCanvasElement>(null);

    const drawCrosshair = useCallback(
      (ctx: CanvasRenderingContext2D, cx: number, cy: number) => {
        const len = 16;
        const gap = 6;
        const col = "#D5FF40";

        ctx.strokeStyle = col;
        ctx.lineWidth = 1;
        ctx.globalAlpha = 0.8;
        ctx.beginPath();
        ctx.moveTo(cx - len - gap, cy);
        ctx.lineTo(cx - gap, cy);
        ctx.moveTo(cx + gap, cy);
        ctx.lineTo(cx + len + gap, cy);
        ctx.moveTo(cx, cy - len - gap);
        ctx.lineTo(cx, cy - gap);
        ctx.moveTo(cx, cy + gap);
        ctx.lineTo(cx, cy + len + gap);
        ctx.stroke();

        ctx.globalAlpha = 0.6;
        ctx.fillStyle = col;
        ctx.beginPath();
        ctx.arc(cx, cy, 2, 0, Math.PI * 2);
        ctx.fill();
        ctx.globalAlpha = 1;
      },
      []
    );

    const drawCornerBrackets = useCallback(
      (ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number) => {
        const len = 14;
        ctx.strokeStyle = "rgba(213,255,64,0.5)";
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(x + len, y); ctx.lineTo(x, y); ctx.lineTo(x, y + len);
        ctx.moveTo(x + w - len, y); ctx.lineTo(x + w, y); ctx.lineTo(x + w, y + len);
        ctx.moveTo(x, y + h - len); ctx.lineTo(x, y + h); ctx.lineTo(x + len, y + h);
        ctx.moveTo(x + w - len, y + h); ctx.lineTo(x + w, y + h); ctx.lineTo(x + w, y + h - len);
        ctx.stroke();
      },
      []
    );

    const drawDetectionBoxes = useCallback(
      (ctx: CanvasRenderingContext2D, detections: Detection[], dx: number, dy: number, dw: number, dh: number, fw: number, fh: number) => {
        if (!detections.length || !fw || !fh) return;
        const scaleX = dw / fw;
        const scaleY = dh / fh;

        detections.forEach((det) => {
          const { x1, y1, x2, y2, label, conf, color } = det;
          const px1 = dx + x1 * scaleX;
          const py1 = dy + y1 * scaleY;
          const pw = (x2 - x1) * scaleX;
          const ph = (y2 - y1) * scaleY;
          const col = color || "#D5FF40";

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
          ctx.fillStyle = "#0a0a08";
          ctx.fillText(text, px1 + 3, py1 - 3);

          // Centroid
          if (det.cx !== undefined && det.cy !== undefined) {
            const pcx = dx + det.cx * scaleX;
            const pcy = dy + det.cy * scaleY;
            ctx.beginPath();
            ctx.arc(pcx, pcy, 5, 0, Math.PI * 2);
            ctx.fillStyle = col;
            ctx.globalAlpha = 0.9;
            ctx.fill();

            ctx.beginPath();
            ctx.arc(pcx, pcy, 7, 0, Math.PI * 2);
            ctx.strokeStyle = col;
            ctx.lineWidth = 1;
            ctx.globalAlpha = 0.5;
            ctx.stroke();

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
      },
      []
    );

    useImperativeHandle(ref, () => ({
      drawHUD(draw: PanelDrawState, detections: Detection[], detFrameW: number, detFrameH: number) {
        const canvas = canvasRef.current;
        if (!canvas) return;
        const ctx = canvas.getContext("2d");
        if (!ctx) return;

        ctx.clearRect(0, 0, draw.cw, draw.ch);
        if (!showHUD) return;

        const cx = draw.dx + draw.dw / 2;
        const cy = draw.dy + draw.dh / 2;

        if (showCrosshair) drawCrosshair(ctx, cx, cy);
        drawCornerBrackets(ctx, draw.dx, draw.dy, draw.dw, draw.dh);
        if (showDetections) drawDetectionBoxes(ctx, detections, draw.dx, draw.dy, draw.dw, draw.dh, detFrameW, detFrameH);
      },
      clear() {
        const canvas = canvasRef.current;
        if (!canvas) return;
        const ctx = canvas.getContext("2d");
        if (!ctx) return;
        ctx.clearRect(0, 0, canvas.width, canvas.height);
      },
    }), [showCrosshair, showHUD, showDetections, drawCrosshair, drawCornerBrackets, drawDetectionBoxes]);

    return <canvas ref={canvasRef} className="hud-canvas-overlay" />;
  }
);

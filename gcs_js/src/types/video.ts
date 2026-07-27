/** YOLO detection item from WebSocket or /api/video/detect */
export interface Detection {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  label: string;
  conf: number;
  color?: string;
  cx?: number;
  cy?: number;
}

/** YOLO detections message received from /ws/video text frames */
export interface DetectionMessage {
  type: "detections";
  detections: Detection[];
  frame_width: number;
  frame_height: number;
  inference_ms?: number;
}

/** Video panel state for tracking rendering geometry */
export interface PanelDrawState {
  dx: number;
  dy: number;
  dw: number;
  dh: number;
  cw: number;
  ch: number;
}

/** Camera source type */
export type CameraSource = "none" | "udp" | string;

"use client";

import { useCallback, useEffect, useRef } from "react";

interface UseWebSocketOptions {
  url: string;
  onMessage?: (data: string) => void;
  onBinary?: (data: Blob) => void;
  onOpen?: () => void;
  onClose?: () => void;
  enabled?: boolean;
  binaryType?: BinaryType;
}

export function useWebSocket({
  url,
  onMessage,
  onBinary,
  onOpen,
  onClose,
  enabled = true,
  binaryType = "blob",
}: UseWebSocketOptions) {
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!enabled || !url) return;

    let active = true;
    let backoff = 1000;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;

    function connect() {
      if (!active) return;

      if (wsRef.current) {
        wsRef.current.onclose = null;
        wsRef.current.close();
      }

      const websocket = new WebSocket(url);
      websocket.binaryType = binaryType;
      wsRef.current = websocket;

      websocket.onopen = () => {
        backoff = 1000;
        onOpen?.();
      };

      websocket.onmessage = (event) => {
        if (event.data instanceof Blob) {
          onBinary?.(event.data);
        } else if (typeof event.data === "string") {
          onMessage?.(event.data);
        }
      };

      websocket.onclose = () => {
        onClose?.();
        if (!active) return;
        reconnectTimer = setTimeout(connect, backoff);
        backoff = Math.min(backoff * 2, 16000);
      };

      websocket.onerror = () => {};
    }

    connect();

    return () => {
      active = false;
      clearTimeout(reconnectTimer);
      if (wsRef.current) {
        wsRef.current.onclose = null;
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [binaryType, enabled, onBinary, onClose, onMessage, onOpen, url]);

  const send = useCallback((data: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(data);
    }
  }, []);

  return { send, wsRef };
}

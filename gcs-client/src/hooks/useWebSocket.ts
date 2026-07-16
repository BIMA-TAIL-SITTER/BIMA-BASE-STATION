"use client";

import { useEffect, useRef, useCallback } from "react";

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
  const backoffRef = useRef(1000);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const mountedRef = useRef(true);

  const onMessageRef = useRef(onMessage);
  const onBinaryRef = useRef(onBinary);
  const onOpenRef = useRef(onOpen);
  const onCloseRef = useRef(onClose);

  onMessageRef.current = onMessage;
  onBinaryRef.current = onBinary;
  onOpenRef.current = onOpen;
  onCloseRef.current = onClose;

  const connect = useCallback(() => {
    if (!mountedRef.current || !url) return;

    if (wsRef.current) {
      wsRef.current.onclose = null;
      wsRef.current.close();
    }

    const ws = new WebSocket(url);
    ws.binaryType = binaryType;
    wsRef.current = ws;

    ws.onopen = () => {
      backoffRef.current = 1000;
      onOpenRef.current?.();
    };

    ws.onmessage = (ev) => {
      if (ev.data instanceof Blob) {
        onBinaryRef.current?.(ev.data);
      } else if (typeof ev.data === "string") {
        onMessageRef.current?.(ev.data);
      }
    };

    ws.onclose = () => {
      onCloseRef.current?.();
      if (mountedRef.current) {
        reconnectTimerRef.current = setTimeout(() => {
          connect();
        }, backoffRef.current);
        backoffRef.current = Math.min(backoffRef.current * 2, 16000);
      }
    };

    ws.onerror = () => {};
  }, [url, binaryType]);

  useEffect(() => {
    mountedRef.current = true;
    if (enabled && url) {
      connect();
    }
    return () => {
      mountedRef.current = false;
      clearTimeout(reconnectTimerRef.current);
      if (wsRef.current) {
        wsRef.current.onclose = null;
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [enabled, url, connect]);

  const send = useCallback((data: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(data);
    }
  }, []);

  return { send, wsRef };
}

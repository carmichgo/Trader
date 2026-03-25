/**
 * WebSocket hook for real-time event streaming from the trading system.
 */

import { useEffect, useRef, useCallback, useState } from "react";
import type { WSEvent, WSEventType } from "../lib/types";

type EventHandler = (event: WSEvent) => void;

interface UseWebSocketOptions {
  /** Topics to subscribe to on connect (e.g. "trades", "portfolio") */
  topics?: string[];
  /** Auto-reconnect on disconnect (default: true) */
  reconnect?: boolean;
  /** Reconnect delay in ms (default: 3000) */
  reconnectDelay?: number;
  /** Specific event types to listen for */
  eventTypes?: WSEventType[];
  /** Handler called for every matching event */
  onEvent?: EventHandler;
}

interface UseWebSocketReturn {
  connected: boolean;
  lastEvent: WSEvent | null;
  send: (data: Record<string, unknown>) => void;
}

export function useWebSocket(
  options: UseWebSocketOptions = {}
): UseWebSocketReturn {
  const {
    topics = [],
    reconnect = true,
    reconnectDelay = 3000,
    eventTypes,
    onEvent,
  } = options;

  const [connected, setConnected] = useState(false);
  const [lastEvent, setLastEvent] = useState<WSEvent | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>();
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  const send = useCallback((data: Record<string, unknown>) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data));
    }
  }, []);

  useEffect(() => {
    function connect() {
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const ws = new WebSocket(`${protocol}//${window.location.host}/ws`);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        // Subscribe to requested topics
        for (const topic of topics) {
          ws.send(JSON.stringify({ action: "subscribe", topic }));
        }
      };

      ws.onmessage = (e) => {
        try {
          const event = JSON.parse(e.data) as WSEvent;
          // Filter by event type if specified
          if (eventTypes && !eventTypes.includes(event.event as WSEventType)) {
            return;
          }
          setLastEvent(event);
          onEventRef.current?.(event);
        } catch {
          // Ignore malformed messages
        }
      };

      ws.onclose = () => {
        setConnected(false);
        wsRef.current = null;
        if (reconnect) {
          reconnectTimer.current = setTimeout(connect, reconnectDelay);
        }
      };

      ws.onerror = () => {
        ws.close();
      };
    }

    connect();

    return () => {
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
      wsRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reconnect, reconnectDelay, topics.join(","), eventTypes?.join(",")]);

  return { connected, lastEvent, send };
}

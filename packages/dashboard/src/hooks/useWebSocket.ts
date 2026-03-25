/**
 * Real-time event hook using Supabase Realtime subscriptions.
 * Replaces the previous WebSocket-based implementation while
 * exporting the same interface so pages don't need changes.
 */

import { useEffect, useRef, useState, useCallback } from "react";
import { supabase } from "../lib/supabase";
import type {
  WSEvent,
  WSEventType,
  Trade,
  PortfolioSnapshot,
  AIDecision,
} from "../lib/types";
import type { RealtimeChannel } from "@supabase/supabase-js";

type EventHandler = (event: WSEvent) => void;

interface UseWebSocketOptions {
  /** Topics to subscribe to (e.g. "trades", "portfolio") */
  topics?: string[];
  /** Auto-reconnect on disconnect (default: true) — kept for API compat */
  reconnect?: boolean;
  /** Reconnect delay in ms — kept for API compat */
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

/** Map a Supabase table + event type into our WSEvent format. */
function toWSEvent(
  table: string,
  eventType: string,
  newRow: Record<string, unknown>
): WSEvent | null {
  const timestamp = new Date().toISOString();

  if (table === "trades") {
    let event: WSEvent["event"];
    if (eventType === "INSERT") event = "trade.opened";
    else if (eventType === "UPDATE") {
      const status = newRow.status as string | undefined;
      event = status === "closed" ? "trade.closed" : "trade.updated";
    } else if (eventType === "DELETE") {
      event = "trade.updated";
    } else {
      return null;
    }
    return { event, data: newRow as unknown as Trade, timestamp };
  }

  if (table === "portfolio_snapshots") {
    return {
      event: "portfolio.snapshot",
      data: newRow as unknown as PortfolioSnapshot,
      timestamp,
    };
  }

  if (table === "ai_decisions") {
    return {
      event: "ai.decision",
      data: newRow as unknown as AIDecision,
      timestamp,
    };
  }

  return null;
}

/** Which Supabase tables to subscribe to based on requested topics. */
function topicsToTables(topics: string[]): string[] {
  if (topics.length === 0) {
    // Default: subscribe to core tables
    return ["trades", "portfolio_snapshots", "ai_decisions"];
  }

  const tables: string[] = [];
  for (const t of topics) {
    switch (t) {
      case "trades":
        tables.push("trades");
        break;
      case "portfolio":
        tables.push("portfolio_snapshots");
        break;
      case "ai":
      case "decisions":
        tables.push("ai_decisions");
        break;
      case "pace":
      case "cost":
        // These are derived; subscribe to underlying tables
        tables.push("trades", "ai_decisions");
        break;
      default:
        // Treat topic name as a table name directly
        tables.push(t);
    }
  }
  return [...new Set(tables)];
}

export function useWebSocket(
  options: UseWebSocketOptions = {}
): UseWebSocketReturn {
  const { topics = [], eventTypes, onEvent } = options;

  const [connected, setConnected] = useState(false);
  const [lastEvent, setLastEvent] = useState<WSEvent | null>(null);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;
  const channelsRef = useRef<RealtimeChannel[]>([]);

  // send() is a no-op — Supabase Realtime is server-push only
  const send = useCallback((_data: Record<string, unknown>) => {
    // No-op: Supabase Realtime does not support client-to-server messages.
  }, []);

  useEffect(() => {
    const tables = topicsToTables(topics);
    const channels: RealtimeChannel[] = [];

    for (const table of tables) {
      const channel = supabase
        .channel(`realtime-${table}-${Math.random().toString(36).slice(2)}`)
        .on(
          "postgres_changes" as never,
          { event: "*", schema: "public", table } as never,
          (payload: { eventType: string; new: Record<string, unknown> }) => {
            const wsEvent = toWSEvent(table, payload.eventType, payload.new);
            if (!wsEvent) return;

            // Filter by event type if specified
            if (
              eventTypes &&
              !eventTypes.includes(wsEvent.event as WSEventType)
            ) {
              return;
            }

            setLastEvent(wsEvent);
            onEventRef.current?.(wsEvent);
          }
        )
        .subscribe((status: string) => {
          if (status === "SUBSCRIBED") {
            setConnected(true);
          }
        });

      channels.push(channel);
    }

    channelsRef.current = channels;

    return () => {
      for (const ch of channels) {
        supabase.removeChannel(ch);
      }
      channelsRef.current = [];
      setConnected(false);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [topics.join(","), eventTypes?.join(",")]);

  return { connected, lastEvent, send };
}

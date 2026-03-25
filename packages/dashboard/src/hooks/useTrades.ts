/**
 * Trade history hooks with real-time updates via WebSocket.
 */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getTrades, getTrade } from "../lib/api";
import { useWebSocket } from "./useWebSocket";
import type { WSEvent } from "../lib/types";
import { useCallback } from "react";

export function useTrades(params?: {
  trader?: string;
  status?: string;
  asset?: string;
  direction?: string;
  since_hours?: number;
  limit?: number;
  offset?: number;
}) {
  const queryClient = useQueryClient();

  const onEvent = useCallback(
    (event: WSEvent) => {
      if (
        event.event === "trade.opened" ||
        event.event === "trade.closed" ||
        event.event === "trade.updated"
      ) {
        queryClient.invalidateQueries({ queryKey: ["trades"] });
      }
    },
    [queryClient]
  );

  useWebSocket({
    topics: ["trades"],
    eventTypes: ["trade.opened", "trade.closed", "trade.updated"],
    onEvent,
  });

  return useQuery({
    queryKey: ["trades", params],
    queryFn: () => getTrades(params),
    refetchInterval: 15_000,
  });
}

export function useTradeDetail(tradeId: string | null) {
  return useQuery({
    queryKey: ["trade", tradeId],
    queryFn: () => getTrade(tradeId!),
    enabled: !!tradeId,
  });
}

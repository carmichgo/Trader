/**
 * Portfolio data hooks using React Query + Supabase Realtime for live updates.
 */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getPortfolio, getTraderPortfolio, getGoal, getPace } from "../lib/api";
import { useWebSocket } from "./useWebSocket";
import type { WSEvent } from "../lib/types";
import { useCallback } from "react";

export function usePortfolio(hours = 24) {
  const queryClient = useQueryClient();

  const onEvent = useCallback(
    (event: WSEvent) => {
      if (event.event === "portfolio.snapshot") {
        queryClient.invalidateQueries({ queryKey: ["portfolio"] });
      }
    },
    [queryClient]
  );

  useWebSocket({
    topics: ["portfolio"],
    eventTypes: ["portfolio.snapshot"],
    onEvent,
  });

  return useQuery({
    queryKey: ["portfolio", hours],
    queryFn: () => getPortfolio(hours),
    refetchInterval: 30_000,
  });
}

export function useTraderPortfolio(trader: string, days = 7) {
  const queryClient = useQueryClient();

  const onEvent = useCallback(
    (event: WSEvent) => {
      if (
        event.event === "trade.opened" ||
        event.event === "trade.closed" ||
        event.event === "trade.updated"
      ) {
        queryClient.invalidateQueries({ queryKey: ["portfolio", trader] });
      }
    },
    [queryClient, trader]
  );

  useWebSocket({
    topics: ["trades"],
    eventTypes: ["trade.opened", "trade.closed", "trade.updated"],
    onEvent,
  });

  return useQuery({
    queryKey: ["portfolio", trader, days],
    queryFn: () => getTraderPortfolio(trader, days),
    refetchInterval: 30_000,
  });
}

export function useGoal() {
  return useQuery({
    queryKey: ["goal"],
    queryFn: getGoal,
    refetchInterval: 60_000,
  });
}

export function usePace() {
  const queryClient = useQueryClient();

  const onEvent = useCallback(
    (event: WSEvent) => {
      if (
        event.event === "trade.opened" ||
        event.event === "trade.closed" ||
        event.event === "ai.decision"
      ) {
        queryClient.invalidateQueries({ queryKey: ["pace"] });
      }
    },
    [queryClient]
  );

  useWebSocket({
    topics: ["trades", "decisions"],
    eventTypes: ["trade.opened", "trade.closed", "ai.decision"],
    onEvent,
  });

  return useQuery({
    queryKey: ["pace"],
    queryFn: getPace,
    refetchInterval: 30_000,
  });
}

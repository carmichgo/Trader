/**
 * API client for the AI Trading System backend.
 * All endpoints proxy through Vite dev server to localhost:8000.
 */

import type {
  PortfolioResponse,
  TraderPortfolioResponse,
  TradesResponse,
  RiskOverview,
  CorrelationResponse,
  CostResponse,
  CostTodayResponse,
  AIDecisionsResponse,
  GoalResponse,
  PaceStatus,
  StrategistPlan,
  Trade,
} from "./types";

const BASE = "/api";

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${res.statusText} - ${body}`);
  }
  return res.json() as Promise<T>;
}

// ── Portfolio ──────────────────────────────────────────────────────────────

export function getPortfolio(hours = 24): Promise<PortfolioResponse> {
  return fetchJSON(`${BASE}/portfolio?hours=${hours}`);
}

export function getTraderPortfolio(
  trader: string,
  days = 7
): Promise<TraderPortfolioResponse> {
  return fetchJSON(`${BASE}/portfolio/${trader}?days=${days}`);
}

// ── Trades ─────────────────────────────────────────────────────────────────

export function getTrades(params?: {
  trader?: string;
  status?: string;
  asset?: string;
  direction?: string;
  since_hours?: number;
  limit?: number;
  offset?: number;
}): Promise<TradesResponse> {
  const qs = new URLSearchParams();
  if (params?.trader) qs.set("trader", params.trader);
  if (params?.status) qs.set("status", params.status);
  if (params?.asset) qs.set("asset", params.asset);
  if (params?.direction) qs.set("direction", params.direction);
  if (params?.since_hours) qs.set("since_hours", String(params.since_hours));
  if (params?.limit) qs.set("limit", String(params.limit));
  if (params?.offset) qs.set("offset", String(params.offset));
  const q = qs.toString();
  return fetchJSON(`${BASE}/trades${q ? `?${q}` : ""}`);
}

export function getTrade(tradeId: string): Promise<Trade> {
  return fetchJSON(`${BASE}/trades/${tradeId}`);
}

// ── Risk ───────────────────────────────────────────────────────────────────

export function getRiskOverview(): Promise<RiskOverview> {
  return fetchJSON(`${BASE}/risk`);
}

export function getCorrelations(days = 30): Promise<CorrelationResponse> {
  return fetchJSON(`${BASE}/risk/correlations?days=${days}`);
}

// ── Costs ──────────────────────────────────────────────────────────────────

export function getCosts(days = 7): Promise<CostResponse> {
  return fetchJSON(`${BASE}/costs?days=${days}`);
}

export function getCostsToday(): Promise<CostTodayResponse> {
  return fetchJSON(`${BASE}/costs/today`);
}

// ── AI Decisions ───────────────────────────────────────────────────────────

export function getAIDecisions(params?: {
  decision_type?: string;
  trader?: string;
  since_hours?: number;
  limit?: number;
  offset?: number;
}): Promise<AIDecisionsResponse> {
  const qs = new URLSearchParams();
  if (params?.decision_type) qs.set("decision_type", params.decision_type);
  if (params?.trader) qs.set("trader", params.trader);
  if (params?.since_hours) qs.set("since_hours", String(params.since_hours));
  if (params?.limit) qs.set("limit", String(params.limit));
  if (params?.offset) qs.set("offset", String(params.offset));
  const q = qs.toString();
  return fetchJSON(`${BASE}/ai/decisions${q ? `?${q}` : ""}`);
}

export function getLatestStrategistPlan(): Promise<{
  plan: StrategistPlan | null;
  message?: string;
}> {
  return fetchJSON(`${BASE}/ai/strategist/latest`);
}

// ── Goal & Pace ────────────────────────────────────────────────────────────

export function getGoal(): Promise<GoalResponse> {
  return fetchJSON(`${BASE}/goal`);
}

export function updateGoal(body: {
  starting_capital?: number;
  target_capital?: number;
  time_horizon_days?: number;
}): Promise<GoalResponse> {
  return fetchJSON(`${BASE}/goal`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export function getPace(): Promise<PaceStatus> {
  return fetchJSON(`${BASE}/pace`);
}

// ── Health ─────────────────────────────────────────────────────────────────

export function getHealth(): Promise<{ status: string }> {
  return fetchJSON("/healthz");
}

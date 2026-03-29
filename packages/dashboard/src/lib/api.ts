/**
 * API client for the AI Trading System dashboard.
 * Queries Supabase directly instead of a FastAPI backend.
 */

import { supabase } from "./supabase";
import type {
  PortfolioResponse,
  PortfolioSnapshot,
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
  AIDecision,
  DailyCostSummary,
  CostByModel,
  DailyPerformance,
} from "./types";

// ── Helpers ──────────────────────────────────────────────────────────────

function hoursAgo(hours: number): string {
  return new Date(Date.now() - hours * 60 * 60 * 1000).toISOString();
}

function daysAgo(days: number): string {
  return new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString();
}

function todayStart(): string {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  return d.toISOString();
}

// ── Portfolio ──────────────────────────────────────────────────────────────

export async function getPortfolio(hours = 24): Promise<PortfolioResponse> {
  const since = hoursAgo(hours);

  const { data: snapshots, error } = await supabase
    .from("portfolio_snapshots")
    .select("*")
    .gte("time", since)
    .order("time", { ascending: true });

  if (error) throw new Error(`getPortfolio: ${error.message}`);

  const history: PortfolioSnapshot[] = (snapshots ?? []).map((s: Record<string, unknown>) => ({
    time: s.time as string,
    total_capital: (s.total_capital as number) ?? 0,
    polymarket_capital: (s.polymarket_capital as number) ?? null,
    crypto_capital: (s.crypto_capital as number) ?? null,
    stocks_capital: (s.stocks_capital as number) ?? null,
    total_unrealized_pnl: (s.total_unrealized_pnl as number) ?? undefined,
    total_realized_pnl_today: (s.total_realized_pnl_today as number) ?? undefined,
    open_positions_count: (s.open_positions_count as number) ?? undefined,
    daily_inference_cost: (s.daily_inference_cost as number) ?? undefined,
    daily_trading_fees: (s.daily_trading_fees as number) ?? undefined,
    drawdown_from_peak: (s.drawdown_from_peak as number) ?? undefined,
  }));

  const current = history.length > 0 ? history[history.length - 1]! : null;

  // Count open trades
  const { count: openTradesCount } = await supabase
    .from("trades")
    .select("id", { count: "exact", head: true })
    .eq("status", "open");

  return {
    current,
    history,
    open_trades_count: openTradesCount ?? 0,
  };
}

export async function getTraderPortfolio(
  trader: string,
  days = 7
): Promise<TraderPortfolioResponse> {
  const since = daysAgo(days);

  // Fetch trades for this trader
  const { data: trades, error: tradesErr } = await supabase
    .from("trades")
    .select("*")
    .eq("trader", trader)
    .gte("opened_at", since)
    .order("opened_at", { ascending: false });

  if (tradesErr) throw new Error(`getTraderPortfolio trades: ${tradesErr.message}`);

  const allTrades: Trade[] = trades ?? [];
  const openTrades = allTrades.filter((t) => t.status === "open");
  const closedTrades = allTrades.filter((t) => t.status === "closed");

  const totalPnl = closedTrades.reduce((sum, t) => sum + (t.net_pnl ?? 0), 0);
  const wins = closedTrades.filter((t) => (t.net_pnl ?? 0) > 0).length;
  const losses = closedTrades.filter((t) => (t.net_pnl ?? 0) < 0).length;

  // Fetch daily performance
  const { data: dailyPerf, error: perfErr } = await supabase
    .from("daily_performance")
    .select("*")
    .eq("trader", trader)
    .gte("date", daysAgo(days).slice(0, 10))
    .order("date", { ascending: true });

  if (perfErr) throw new Error(`getTraderPortfolio perf: ${perfErr.message}`);

  const dailyPerformance: DailyPerformance[] = (dailyPerf ?? []).map(
    (d: Record<string, unknown>) => ({
      date: d.date as string,
      trades_count: (d.trades_count as number) ?? 0,
      winning_trades: (d.winning_trades as number) ?? 0,
      losing_trades: (d.losing_trades as number) ?? 0,
      gross_pnl: (d.gross_pnl as number) ?? 0,
      net_pnl: (d.net_pnl as number) ?? 0,
      total_inference_cost: (d.total_inference_cost as number) ?? 0,
      total_trading_fees: (d.total_trading_fees as number) ?? 0,
      win_rate: (d.win_rate as number) ?? null,
      sharpe_ratio: (d.sharpe_ratio as number) ?? null,
    })
  );

  return {
    trader,
    summary: {
      total_pnl: totalPnl,
      total_trades: closedTrades.length,
      total_wins: wins,
      total_losses: losses,
      win_rate_pct: closedTrades.length > 0 ? (wins / closedTrades.length) * 100 : 0,
    },
    daily_performance: dailyPerformance,
    open_trades: openTrades,
  };
}

// ── Trades ─────────────────────────────────────────────────────────────────

export async function getTrades(params?: {
  trader?: string;
  status?: string;
  asset?: string;
  direction?: string;
  since_hours?: number;
  limit?: number;
  offset?: number;
}): Promise<TradesResponse> {
  const limit = params?.limit ?? 50;
  const offset = params?.offset ?? 0;

  let query = supabase
    .from("trades")
    .select("*", { count: "exact" });

  if (params?.trader) query = query.eq("trader", params.trader);
  if (params?.status) query = query.eq("status", params.status);
  if (params?.asset) query = query.eq("asset", params.asset);
  if (params?.direction) query = query.eq("direction", params.direction);
  if (params?.since_hours) query = query.gte("opened_at", hoursAgo(params.since_hours));

  query = query.order("opened_at", { ascending: false }).range(offset, offset + limit - 1);

  const { data, error, count } = await query;
  if (error) throw new Error(`getTrades: ${error.message}`);

  return {
    trades: (data ?? []) as Trade[],
    total: count ?? 0,
    limit,
    offset,
  };
}

export async function getTrade(tradeId: string): Promise<Trade> {
  const { data: trade, error } = await supabase
    .from("trades")
    .select("*")
    .eq("id", tradeId)
    .single();

  if (error) throw new Error(`getTrade: ${error.message}`);

  // Fetch related AI decisions
  const { data: decisions } = await supabase
    .from("ai_decisions")
    .select("*")
    .eq("related_trade_id", tradeId)
    .order("created_at", { ascending: true });

  const result = trade as Trade;
  result.ai_decisions = (decisions ?? []) as AIDecision[];

  // Extract screener/analyst outputs from decisions
  const screener = (decisions ?? []).find(
    (d: Record<string, unknown>) => d.decision_type === "screener"
  );
  const analyst = (decisions ?? []).find(
    (d: Record<string, unknown>) => d.decision_type === "analyst"
  );
  result.screener_output = screener ? (screener.output_raw as string | null) : null;
  result.analyst_output = analyst ? (analyst.output_raw as string | null) : null;

  return result;
}

// ── Risk ───────────────────────────────────────────────────────────────────

export async function getRiskOverview(): Promise<RiskOverview> {
  // Get recent portfolio snapshots for drawdown history
  const { data: snapshots } = await supabase
    .from("portfolio_snapshots")
    .select("time, total_capital, drawdown_from_peak")
    .order("time", { ascending: true })
    .gte("time", hoursAgo(24));

  const snapshotList = snapshots ?? [];
  const lastSnapshot = snapshotList.length > 0 ? snapshotList[snapshotList.length - 1]! : null;
  const latestCapital = lastSnapshot ? (lastSnapshot.total_capital as number) : 0;
  const currentDrawdown = lastSnapshot
    ? ((lastSnapshot.drawdown_from_peak as number) ?? 0)
    : 0;

  const drawdownHistory = snapshotList.map((s: Record<string, unknown>) => ({
    time: s.time as string,
    drawdown_pct: (s.drawdown_from_peak as number) ?? 0,
    capital: (s.total_capital as number) ?? 0,
  }));

  // Get open trades for exposure
  const { data: openTrades } = await supabase
    .from("trades")
    .select("*")
    .eq("status", "open")
    .order("position_size_usd", { ascending: false });

  const trades = (openTrades ?? []) as Trade[];

  // Compute exposure by trader
  const traderMap: Record<
    string,
    { open_positions: number; total_exposure_usd: number; confidences: number[] }
  > = {};
  for (const t of trades) {
    if (!traderMap[t.trader]) {
      traderMap[t.trader] = { open_positions: 0, total_exposure_usd: 0, confidences: [] };
    }
    const tm = traderMap[t.trader]!;
    tm.open_positions++;
    tm.total_exposure_usd += t.position_size_usd;
    if (t.ai_confidence != null) tm.confidences.push(t.ai_confidence);
  }

  const byTrader = Object.entries(traderMap).map(([trader, data]) => ({
    trader,
    open_positions: data.open_positions,
    total_exposure_usd: data.total_exposure_usd,
    avg_confidence:
      data.confidences.length > 0
        ? data.confidences.reduce((a, b) => a + b, 0) / data.confidences.length
        : 0,
  }));

  // Compute exposure by direction
  const dirMap: Record<string, { count: number; exposure_usd: number }> = {};
  for (const t of trades) {
    if (!dirMap[t.direction]) dirMap[t.direction] = { count: 0, exposure_usd: 0 };
    const dm = dirMap[t.direction]!;
    dm.count++;
    dm.exposure_usd += t.position_size_usd;
  }

  const byDirection = Object.entries(dirMap).map(([direction, data]) => ({
    direction,
    count: data.count,
    exposure_usd: data.exposure_usd,
  }));

  const totalExposure = trades.reduce((sum, t) => sum + t.position_size_usd, 0);

  // Largest positions
  const largestPositions = trades.slice(0, 10).map((t) => ({
    id: t.id,
    trader: t.trader,
    asset: t.asset,
    direction: t.direction,
    size_usd: t.position_size_usd,
    entry_price: t.entry_price,
    stop_loss: t.stop_loss,
    opened_at: t.opened_at,
  }));

  return {
    drawdown: {
      current_pct: currentDrawdown,
      total_capital: latestCapital,
      history: drawdownHistory,
    },
    exposure: {
      total_usd: totalExposure,
      by_trader: byTrader,
      by_direction: byDirection,
    },
    largest_positions: largestPositions,
  };
}

export async function getCorrelations(days = 30): Promise<CorrelationResponse> {
  const since = daysAgo(days);

  // Get closed trades in the period for correlation computation
  const { data: trades } = await supabase
    .from("trades")
    .select("trader, asset, net_pnl, closed_at")
    .eq("status", "closed")
    .gte("closed_at", since);

  const tradeList = trades ?? [];

  // Compute simple asset correlation based on PnL co-occurrence per day
  const assetDailyPnl: Record<string, Record<string, number>> = {};
  const traderDailyPnl: Record<string, Record<string, number>> = {};

  for (const t of tradeList) {
    const day = ((t.closed_at as string) ?? "").slice(0, 10);
    const asset = t.asset as string;
    const trader = t.trader as string;
    const pnl = (t.net_pnl as number) ?? 0;

    if (!assetDailyPnl[asset]) assetDailyPnl[asset] = {};
    assetDailyPnl[asset][day] = (assetDailyPnl[asset][day] ?? 0) + pnl;

    if (!traderDailyPnl[trader]) traderDailyPnl[trader] = {};
    traderDailyPnl[trader][day] = (traderDailyPnl[trader][day] ?? 0) + pnl;
  }

  const assets = Object.keys(assetDailyPnl);
  const traders = Object.keys(traderDailyPnl);

  // Compute pairwise correlations for assets
  const assetCorrelations: {
    asset_a: string;
    asset_b: string;
    correlation: number;
    observations: number;
  }[] = [];

  for (let i = 0; i < assets.length; i++) {
    for (let j = i + 1; j < assets.length; j++) {
      const assetA = assets[i]!;
      const assetB = assets[j]!;
      const a = assetDailyPnl[assetA]!;
      const b = assetDailyPnl[assetB]!;
      const commonDays = Object.keys(a).filter((d) => d in b);
      if (commonDays.length < 2) continue;
      const aVals = commonDays.map((d) => a[d]!);
      const bVals = commonDays.map((d) => b[d]!);
      const corr = pearsonCorrelation(aVals, bVals);
      assetCorrelations.push({
        asset_a: assetA,
        asset_b: assetB,
        correlation: corr,
        observations: commonDays.length,
      });
    }
  }

  // Compute pairwise correlations for traders
  const marketCorrelations: {
    trader_a: string;
    trader_b: string;
    correlation: number;
    observations: number;
  }[] = [];

  for (let i = 0; i < traders.length; i++) {
    for (let j = i + 1; j < traders.length; j++) {
      const traderA = traders[i]!;
      const traderB = traders[j]!;
      const a = traderDailyPnl[traderA]!;
      const b = traderDailyPnl[traderB]!;
      const commonDays = Object.keys(a).filter((d) => d in b);
      if (commonDays.length < 2) continue;
      const aVals = commonDays.map((d) => a[d]!);
      const bVals = commonDays.map((d) => b[d]!);
      const corr = pearsonCorrelation(aVals, bVals);
      marketCorrelations.push({
        trader_a: traderA,
        trader_b: traderB,
        correlation: corr,
        observations: commonDays.length,
      });
    }
  }

  return {
    days,
    asset_correlations: assetCorrelations,
    market_correlations: marketCorrelations,
    assets_tracked: assets.length,
    traders_tracked: traders.length,
  };
}

function pearsonCorrelation(x: number[], y: number[]): number {
  const n = x.length;
  if (n < 2) return 0;
  const meanX = x.reduce((a, b) => a + b, 0) / n;
  const meanY = y.reduce((a, b) => a + b, 0) / n;
  let num = 0;
  let denX = 0;
  let denY = 0;
  for (let i = 0; i < n; i++) {
    const dx = x[i]! - meanX;
    const dy = y[i]! - meanY;
    num += dx * dy;
    denX += dx * dx;
    denY += dy * dy;
  }
  const den = Math.sqrt(denX * denY);
  return den === 0 ? 0 : num / den;
}

// ── Costs ──────────────────────────────────────────────────────────────────

export async function getCosts(days = 7): Promise<CostResponse> {
  const since = daysAgo(days);

  const { data: decisions, error } = await supabase
    .from("ai_decisions")
    .select("model, decision_type, cost_usd, prompt_tokens, completion_tokens, created_at")
    .gte("created_at", since);

  if (error) throw new Error(`getCosts: ${error.message}`);

  const decisionList = decisions ?? [];

  // Aggregate daily
  const dailyMap: Record<string, DailyCostSummary> = {};
  for (const d of decisionList) {
    const day = ((d.created_at as string) ?? "").slice(0, 10);
    if (!dailyMap[day]) dailyMap[day] = { date: day, inference_cost: 0, trading_fees: 0, slippage: 0 };
    dailyMap[day].inference_cost += (d.cost_usd as number) ?? 0;
  }

  // Also get trading fees from trades
  const { data: trades } = await supabase
    .from("trades")
    .select("exchange_fee, slippage, closed_at, opened_at")
    .gte("opened_at", since);

  for (const t of trades ?? []) {
    const day = ((t.closed_at ?? t.opened_at) as string ?? "").slice(0, 10);
    if (!day) continue;
    if (!dailyMap[day]) dailyMap[day] = { date: day, inference_cost: 0, trading_fees: 0, slippage: 0 };
    dailyMap[day].trading_fees += (t.exchange_fee as number) ?? 0;
    dailyMap[day].slippage += (t.slippage as number) ?? 0;
  }

  const daily = Object.values(dailyMap).sort((a, b) => a.date.localeCompare(b.date));

  // Aggregate by model
  const modelMap: Record<string, CostByModel> = {};
  for (const d of decisionList) {
    const model = (d.model as string) ?? "unknown";
    if (!modelMap[model]) {
      modelMap[model] = { model, call_count: 0, total_prompt_tokens: 0, total_completion_tokens: 0, total_cost: 0 };
    }
    modelMap[model].call_count++;
    modelMap[model].total_prompt_tokens += (d.prompt_tokens as number) ?? 0;
    modelMap[model].total_completion_tokens += (d.completion_tokens as number) ?? 0;
    modelMap[model].total_cost += (d.cost_usd as number) ?? 0;
  }

  const totalInference = decisionList.reduce((s, d) => s + ((d.cost_usd as number) ?? 0), 0);
  const totalFees = daily.reduce((s, d) => s + d.trading_fees, 0);
  const totalSlippage = daily.reduce((s, d) => s + d.slippage, 0);

  return {
    summary: {
      days,
      total_inference_cost: totalInference,
      total_trading_fees: totalFees,
      total_slippage: totalSlippage,
      total_all_costs: totalInference + totalFees + totalSlippage,
    },
    daily,
    by_model: Object.values(modelMap),
  };
}

export async function getCostsToday(): Promise<CostTodayResponse> {
  const today = todayStart();
  const dateStr = new Date().toISOString().slice(0, 10);

  const { data: decisions } = await supabase
    .from("ai_decisions")
    .select("decision_type, cost_usd, prompt_tokens, completion_tokens")
    .gte("created_at", today);

  const decisionList = decisions ?? [];

  const totalCost = decisionList.reduce((s, d) => s + ((d.cost_usd as number) ?? 0), 0);
  const callCount = decisionList.length;
  const promptTokens = decisionList.reduce((s, d) => s + ((d.prompt_tokens as number) ?? 0), 0);
  const completionTokens = decisionList.reduce(
    (s, d) => s + ((d.completion_tokens as number) ?? 0),
    0
  );

  // By type
  const typeMap: Record<string, { count: number; cost: number }> = {};
  for (const d of decisionList) {
    const dt = (d.decision_type as string) ?? "unknown";
    if (!typeMap[dt]) typeMap[dt] = { count: 0, cost: 0 };
    typeMap[dt].count++;
    typeMap[dt].cost += (d.cost_usd as number) ?? 0;
  }
  const byType = Object.entries(typeMap).map(([decision_type, v]) => ({
    decision_type,
    count: v.count,
    cost: v.cost,
  }));

  // Trading costs today
  const { data: trades } = await supabase
    .from("trades")
    .select("exchange_fee, slippage")
    .gte("opened_at", today);

  const tradeList = trades ?? [];
  const exchangeFees = tradeList.reduce((s, t) => s + ((t.exchange_fee as number) ?? 0), 0);
  const slippage = tradeList.reduce((s, t) => s + ((t.slippage as number) ?? 0), 0);

  return {
    date: dateStr,
    inference: {
      total_cost: totalCost,
      call_count: callCount,
      prompt_tokens: promptTokens,
      completion_tokens: completionTokens,
      by_type: byType,
    },
    trading: {
      exchange_fees: exchangeFees,
      slippage,
      total_trade_costs: exchangeFees + slippage,
    },
    total_all_costs: totalCost + exchangeFees + slippage,
  };
}

// ── AI Decisions ───────────────────────────────────────────────────────────

export async function getAIDecisions(params?: {
  decision_type?: string;
  trader?: string;
  since_hours?: number;
  limit?: number;
  offset?: number;
}): Promise<AIDecisionsResponse> {
  const limit = params?.limit ?? 50;
  const offset = params?.offset ?? 0;

  let query = supabase.from("ai_decisions").select("*");

  if (params?.decision_type) query = query.eq("decision_type", params.decision_type);
  if (params?.trader) query = query.eq("trader", params.trader);
  if (params?.since_hours) query = query.gte("created_at", hoursAgo(params.since_hours));

  query = query.order("created_at", { ascending: false }).range(offset, offset + limit - 1);

  const { data, error } = await query;
  if (error) throw new Error(`getAIDecisions: ${error.message}`);

  return {
    decisions: (data ?? []) as AIDecision[],
    limit,
    offset,
  };
}

export async function getLatestStrategistPlan(): Promise<{
  plan: StrategistPlan | null;
  message?: string;
}> {
  const { data, error } = await supabase
    .from("strategist_plans")
    .select("*")
    .order("created_at", { ascending: false })
    .limit(1)
    .maybeSingle();

  if (error) throw new Error(`getLatestStrategistPlan: ${error.message}`);

  if (!data) {
    return { plan: null, message: "No strategist plan found" };
  }

  return { plan: data as StrategistPlan };
}

// ── Goal & Pace ────────────────────────────────────────────────────────────

export async function getGoal(): Promise<GoalResponse> {
  const { data: goal, error } = await supabase
    .from("goals")
    .select("*")
    .eq("is_active", true)
    .order("created_at", { ascending: false })
    .limit(1)
    .maybeSingle();

  if (error) throw new Error(`getGoal: ${error.message}`);

  if (!goal) {
    return { goal: null, message: "No active goal set" };
  }

  // Compute progress from latest portfolio snapshot
  const { data: latestSnapshot } = await supabase
    .from("portfolio_snapshots")
    .select("total_capital")
    .order("time", { ascending: false })
    .limit(1)
    .maybeSingle();

  const currentCapital = (latestSnapshot?.total_capital as number) ?? (goal.starting_capital as number);
  const startDate = new Date(goal.start_date as string);
  const now = new Date();
  const daysElapsed = Math.max(0, Math.floor((now.getTime() - startDate.getTime()) / (1000 * 60 * 60 * 24)));
  const daysRemaining = Math.max(0, (goal.time_horizon_days as number) - daysElapsed);
  const targetPnl = (goal.target_capital as number) - (goal.starting_capital as number);
  const achievedPnl = currentCapital - (goal.starting_capital as number);
  const remainingPnl = targetPnl - achievedPnl;
  const progressPct = targetPnl > 0 ? (achievedPnl / targetPnl) * 100 : 0;
  const requiredDailyReturnPct =
    daysRemaining > 0 && currentCapital > 0
      ? ((remainingPnl / currentCapital) / daysRemaining) * 100
      : 0;

  return {
    goal: goal as unknown as import("./types").Goal,
    progress: {
      current_capital: currentCapital,
      days_elapsed: daysElapsed,
      days_remaining: daysRemaining,
      progress_pct: progressPct,
      achieved_pnl: achievedPnl,
      remaining_pnl: remainingPnl,
      required_daily_return_pct: requiredDailyReturnPct,
    },
  };
}

export async function updateGoal(body: {
  starting_capital?: number;
  target_capital?: number;
  time_horizon_days?: number;
}): Promise<GoalResponse> {
  // Get the current active goal or create a new one
  const { data: existing } = await supabase
    .from("goals")
    .select("*")
    .eq("is_active", true)
    .order("created_at", { ascending: false })
    .limit(1)
    .maybeSingle();

  if (existing) {
    const { error } = await supabase
      .from("goals")
      .update({
        ...(body.starting_capital !== undefined && { starting_capital: body.starting_capital }),
        ...(body.target_capital !== undefined && { target_capital: body.target_capital }),
        ...(body.time_horizon_days !== undefined && { time_horizon_days: body.time_horizon_days }),
      })
      .eq("id", existing.id);

    if (error) throw new Error(`updateGoal: ${error.message}`);
  } else {
    const { error } = await supabase.from("goals").insert({
      starting_capital: body.starting_capital ?? 1000,
      target_capital: body.target_capital ?? 10000,
      time_horizon_days: body.time_horizon_days ?? 365,
      start_date: new Date().toISOString().slice(0, 10),
      is_active: true,
    });

    if (error) throw new Error(`updateGoal insert: ${error.message}`);
  }

  // Trigger strategist to rethink strategy based on new goal
  await fetch('/api/trigger-strategist', { method: 'POST' }).catch(() => {});

  return getGoal();
}

export async function getPace(): Promise<PaceStatus> {
  const today = todayStart();

  // Get active goal for daily target
  const goalResp = await getGoal();
  const dailyTarget =
    goalResp.progress && goalResp.goal
      ? goalResp.progress.remaining_pnl / Math.max(1, goalResp.progress.days_remaining)
      : 0;

  // Get today's trades
  const { data: todayTrades } = await supabase
    .from("trades")
    .select("trader, net_pnl, status")
    .gte("opened_at", today);

  const tradesList = todayTrades ?? [];
  const pnlToday = tradesList.reduce((s, t) => s + ((t.net_pnl as number) ?? 0), 0);
  const tradesCount = tradesList.length;

  // How far through the day are we?
  const now = new Date();
  const dayStart = new Date(today);
  const timeElapsedPct = ((now.getTime() - dayStart.getTime()) / (24 * 60 * 60 * 1000)) * 100;
  const expectedPnlNow = dailyTarget * (timeElapsedPct / 100);
  const progressPct = dailyTarget > 0 ? (pnlToday / dailyTarget) * 100 : 0;

  // Determine pace status
  let status: import("./types").PaceStatusType = "no_target";
  if (dailyTarget > 0) {
    const ratio = pnlToday / Math.max(dailyTarget * (timeElapsedPct / 100), 0.01);
    if (ratio >= 1.5) status = "well_ahead";
    else if (ratio >= 0.8) status = "on_track";
    else if (ratio >= 0.4) status = "behind";
    else status = "far_behind";
  }

  // Get daily performance by trader for today
  const { data: dailyPerf } = await supabase
    .from("daily_performance")
    .select("*")
    .eq("date", new Date().toISOString().slice(0, 10));

  const byTrader = (dailyPerf ?? []).map((d: Record<string, unknown>) => ({
    trader: (d.trader as string) ?? "",
    net_pnl: (d.net_pnl as number) ?? 0,
    trades_count: (d.trades_count as number) ?? 0,
    winning_trades: (d.winning_trades as number) ?? 0,
    losing_trades: (d.losing_trades as number) ?? 0,
    inference_cost: (d.total_inference_cost as number) ?? 0,
  }));

  return {
    status,
    daily_target_usd: dailyTarget,
    pnl_today: pnlToday,
    expected_pnl_now: expectedPnlNow,
    progress_pct: progressPct,
    time_elapsed_pct: timeElapsedPct,
    trades_today: tradesCount,
    by_trader: byTrader,
  };
}

// ── Health ─────────────────────────────────────────────────────────────────

export async function getHealth(): Promise<{ status: string }> {
  // Simple connectivity check against Supabase
  try {
    const { error } = await supabase.from("portfolio_snapshots").select("time").limit(1);
    if (error) return { status: "error" };
    return { status: "ok" };
  } catch {
    return { status: "error" };
  }
}

// ── Controls ──────────────────────────────────────────────────────────────

export async function pauseTrader(trader: string): Promise<{ status: string }> {
  const { error } = await supabase
    .from("system_controls")
    .upsert({ key: `trader_paused_${trader}`, value: true, updated_at: new Date().toISOString() }, { onConflict: "key" });

  if (error) {
    console.warn("pauseTrader: system_controls table may not exist:", error.message);
    return { status: "paused (ui-only)" };
  }
  return { status: "paused" };
}

export async function resumeTrader(trader: string): Promise<{ status: string }> {
  const { error } = await supabase
    .from("system_controls")
    .upsert({ key: `trader_paused_${trader}`, value: false, updated_at: new Date().toISOString() }, { onConflict: "key" });

  if (error) {
    console.warn("resumeTrader: system_controls table may not exist:", error.message);
    return { status: "resumed (ui-only)" };
  }
  return { status: "resumed" };
}

export async function pauseAll(): Promise<{ status: string }> {
  const { error } = await supabase
    .from("system_controls")
    .upsert({ key: "all_paused", value: true, updated_at: new Date().toISOString() }, { onConflict: "key" });

  if (error) {
    console.warn("pauseAll: system_controls table may not exist:", error.message);
    return { status: "all_paused (ui-only)" };
  }
  return { status: "all_paused" };
}

export async function killSwitch(): Promise<{ status: string }> {
  const { error } = await supabase
    .from("system_controls")
    .upsert({ key: "kill_switch", value: true, updated_at: new Date().toISOString() }, { onConflict: "key" });

  if (error) {
    console.warn("killSwitch: system_controls table may not exist:", error.message);
    return { status: "killed (ui-only)" };
  }
  return { status: "killed" };
}

// ── Reset System ──────────────────────────────────────────────────────────

export async function resetSystem(): Promise<{ status: string; deleted: Record<string, number> }> {
  const deleted: Record<string, number> = {};

  // Delete in order respecting foreign keys
  const tables = [
    "ai_decisions",
    "trades",
    "strategist_plans",
    "daily_performance",
    "portfolio_snapshots",
    "market_data",
    "system_controls",
    "goals",
  ];

  for (const table of tables) {
    const { data, error } = await supabase
      .from(table)
      .delete()
      .gte("id", 0)  // Delete all rows with id
      .select("id");

    if (error) {
      // Try without id filter (for tables with composite PKs)
      const { data: data2 } = await supabase
        .from(table)
        .delete()
        .neq("time", "1900-01-01")  // portfolio_snapshots, market_data
        .select();

      if (!data2) {
        const { data: data3 } = await supabase
          .from(table)
          .delete()
          .neq("date", "1900-01-01")  // daily_performance
          .select();
        deleted[table] = data3?.length ?? 0;
      } else {
        deleted[table] = data2?.length ?? 0;
      }
    } else {
      deleted[table] = data?.length ?? 0;
    }
  }

  return { status: "reset_complete", deleted };
}

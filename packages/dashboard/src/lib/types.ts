/**
 * TypeScript types matching all backend models.
 * Mirrors the Python Pydantic models in packages/core/models/.
 */

// ── Enums ──────────────────────────────────────────────────────────────────

export type TradeStatus = "open" | "closed" | "cancelled";
export type OrderStatus =
  | "created"
  | "submitted"
  | "pending"
  | "partially_filled"
  | "filled"
  | "cancelled"
  | "rejected";
export type CloseReason =
  | "take_profit"
  | "stop_loss"
  | "time_expiry"
  | "manual"
  | "signal_reversal"
  | "kill_switch";
export type Direction = "buy" | "sell" | "short";
export type MarketType = "polymarket" | "crypto" | "stocks";
export type DecisionType = "screener" | "analyst" | "strategist";
export type GoalFeasibility = "on_track" | "at_risk" | "unreachable";
export type PaceStatusType =
  | "well_ahead"
  | "on_track"
  | "behind"
  | "far_behind"
  | "no_target";

// ── Core Models ────────────────────────────────────────────────────────────

export interface Order {
  id: string | null;
  trade_id: string | null;
  market: MarketType;
  symbol: string;
  direction: Direction;
  quantity: number;
  price: number | null;
  order_type: string;
  status: OrderStatus;
  filled_quantity: number;
  filled_price: number | null;
  fees: number;
  exchange_order_id: string | null;
  created_at: string;
  updated_at: string | null;
  submitted_at: string | null;
  filled_at: string | null;
  cancelled_at: string | null;
  error_message: string | null;
  metadata: Record<string, unknown>;
}

export interface Position {
  id: string | null;
  trade_id: string | null;
  market: MarketType;
  symbol: string;
  direction: Direction;
  quantity: number;
  entry_price: number;
  current_price: number | null;
  unrealized_pnl: number;
  realized_pnl: number;
  stop_loss_price: number | null;
  take_profit_price: number | null;
  leverage: number;
  margin_used: number;
  liquidation_price: number | null;
  opened_at: string;
  updated_at: string | null;
  metadata: Record<string, unknown>;
}

export interface Trade {
  id: string;
  trader: string;
  asset: string;
  direction: string;
  position_size_usd: number;
  quantity: number | null;
  entry_price: number | null;
  exit_price: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  status: TradeStatus;
  close_reason: CloseReason | null;
  gross_pnl: number | null;
  net_pnl: number | null;
  exchange_fee: number | null;
  slippage: number | null;
  ai_confidence: number | null;
  ai_model_used: string | null;
  screener_cost: number | null;
  analyst_cost: number | null;
  total_cost: number | null;
  opened_at: string | null;
  closed_at: string | null;
  // Extended fields from detail endpoint
  ai_decisions?: AIDecision[];
  screener_output?: string | null;
  analyst_output?: string | null;
}

export interface Opportunity {
  id: string | null;
  market: MarketType;
  symbol: string;
  title: string | null;
  description: string | null;
  current_price: number | null;
  estimated_edge: number | null;
  confidence: number;
  volume_24h: number | null;
  liquidity: number | null;
  volatility: number | null;
  category: string | null;
  tags: string[];
  source: string | null;
  url: string | null;
  expires_at: string | null;
  discovered_at: string;
  metadata: Record<string, unknown>;
}

// ── Portfolio ──────────────────────────────────────────────────────────────

export interface PortfolioState {
  total_balance: number;
  available_balance: number;
  allocated_balance: number;
  unrealized_pnl: number;
  realized_pnl_today: number;
  realized_pnl_total: number;
  open_positions: Position[];
  open_position_count: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  avg_win: number;
  avg_loss: number;
  largest_win: number;
  largest_loss: number;
  current_drawdown: number;
  max_drawdown: number;
  peak_balance: number;
  current_streak: number;
  losing_streak: number;
  allocation_by_market: Record<string, number>;
  daily_pnl_history: number[];
  total_fees_paid: number;
  total_inference_cost: number;
  sharpe_ratio: number | null;
  sortino_ratio: number | null;
  profit_factor: number | null;
  updated_at: string;
  metadata: Record<string, unknown>;
}

export interface PortfolioSnapshot {
  time: string;
  total_capital: number;
  polymarket_capital: number | null;
  crypto_capital: number | null;
  stocks_capital: number | null;
  total_unrealized_pnl?: number;
  total_realized_pnl_today?: number;
  open_positions_count?: number;
  daily_inference_cost?: number;
  daily_trading_fees?: number;
  drawdown_from_peak?: number;
}

export interface PortfolioResponse {
  current: PortfolioSnapshot | null;
  history: PortfolioSnapshot[];
  open_trades_count: number;
}

export interface TraderPortfolioSummary {
  total_pnl: number;
  total_trades: number;
  total_wins: number;
  total_losses: number;
  win_rate_pct: number;
}

export interface DailyPerformance {
  date: string;
  trades_count: number;
  winning_trades: number;
  losing_trades: number;
  gross_pnl: number;
  net_pnl: number;
  total_inference_cost: number;
  total_trading_fees: number;
  win_rate: number | null;
  sharpe_ratio: number | null;
}

export interface TraderPortfolioResponse {
  trader: string;
  summary: TraderPortfolioSummary;
  daily_performance: DailyPerformance[];
  open_trades: Trade[];
}

// ── Strategist ─────────────────────────────────────────────────────────────

export interface StrategistOutput {
  id: string | null;
  recommended_trades: Record<string, unknown>[];
  signals_to_act_on: unknown[];
  signals_to_skip: unknown[];
  positions_to_close: string[];
  positions_to_adjust: Record<string, unknown>[];
  rebalance_actions: Record<string, unknown>[];
  reasoning: string | null;
  risk_assessment: string | null;
  confidence: number;
  estimated_portfolio_impact: number | null;
  inference_cost: number;
  duration_seconds: number;
  created_at: string;
  metadata: Record<string, unknown>;
}

export interface StrategistPlan {
  id: string;
  goal_id: string;
  plan_date: string;
  allocations: Record<string, unknown>;
  trader_configs: Record<string, unknown>;
  daily_target: number;
  reasoning: string;
  goal_feasibility: number | null;
  inference_cost: number | null;
  tokens_in: number | null;
  tokens_out: number | null;
  created_at: string;
}

// ── Config & Safety ────────────────────────────────────────────────────────

export interface SafetyRails {
  max_single_trade_pct: number;
  max_single_market_allocation: number;
  kill_switch_drawdown_pct: number;
  max_daily_drawdown_pct: number;
  mandatory_stop_loss: boolean;
  max_stop_loss_pct: number;
  max_leverage: number;
  max_daily_inference_cost: number;
  max_inference_to_profit_ratio: number;
  max_concurrent_positions: number;
  require_paper_trade_first: boolean;
  min_paper_trade_days: number;
  max_losing_streak_before_pause: number;
  cool_down_after_pause_hours: number;
}

export interface TraderConfig {
  name: string;
  mode: string;
  markets: MarketType[];
  initial_balance: number;
  target_balance: number | null;
  target_date: string | null;
  safety_rails: SafetyRails;
  screener_interval_minutes: number;
  rebalance_interval_minutes: number;
  max_positions_per_market: number;
  default_leverage: number;
  default_stop_loss_pct: number;
  default_take_profit_pct: number;
  enabled_strategies: string[];
  notifications_enabled: boolean;
  log_level: string;
  metadata: Record<string, unknown>;
}

// ── Cost Tracking ──────────────────────────────────────────────────────────

export interface TradeCostBreakdown {
  trade_id: string | null;
  total_inference_cost: number;
  total_execution_cost: number;
  total_cost: number;
  gross_pnl: number;
  net_pnl: number;
  cost_to_profit_ratio: number | null;
  created_at: string;
}

export interface DailyCostSummary {
  date: string;
  inference_cost: number;
  trading_fees: number;
  slippage: number;
}

export interface CostByModel {
  model: string;
  call_count: number;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_cost: number;
}

export interface CostResponse {
  summary: {
    days: number;
    total_inference_cost: number;
    total_trading_fees: number;
    total_slippage: number;
    total_all_costs: number;
  };
  daily: DailyCostSummary[];
  by_model: CostByModel[];
}

export interface CostTodayResponse {
  date: string;
  inference: {
    total_cost: number;
    call_count: number;
    prompt_tokens: number;
    completion_tokens: number;
    by_type: { decision_type: string; count: number; cost: number }[];
  };
  trading: {
    exchange_fees: number;
    slippage: number;
    total_trade_costs: number;
  };
  total_all_costs: number;
}

// ── AI Decisions ───────────────────────────────────────────────────────────

export interface AIDecision {
  id: string;
  decision_type: DecisionType;
  trader: string;
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
  latency_ms: number;
  input_summary: string | null;
  output_raw: string | null;
  related_trade_id: string | null;
  created_at: string;
}

// ── Goal & Pace ────────────────────────────────────────────────────────────

export interface Goal {
  id: string;
  starting_capital: number;
  target_capital: number;
  time_horizon_days: number;
  start_date: string;
  is_active: boolean;
  created_at: string;
}

export interface GoalProgress {
  current_capital: number;
  days_elapsed: number;
  days_remaining: number;
  progress_pct: number;
  achieved_pnl: number;
  remaining_pnl: number;
  required_daily_return_pct: number;
}

export interface GoalResponse {
  goal: Goal | null;
  progress?: GoalProgress;
  message?: string;
}

export interface PaceStatus {
  status: PaceStatusType;
  daily_target_usd: number;
  pnl_today: number;
  expected_pnl_now: number;
  progress_pct: number;
  time_elapsed_pct: number;
  trades_today: number;
  by_trader: {
    trader: string;
    net_pnl: number;
    trades_count: number;
    winning_trades: number;
    losing_trades: number;
    inference_cost: number;
  }[];
}

// ── Risk ───────────────────────────────────────────────────────────────────

export interface RiskOverview {
  drawdown: {
    current_pct: number;
    total_capital: number;
    history: { time: string; drawdown_pct: number; capital: number }[];
  };
  exposure: {
    total_usd: number;
    by_trader: {
      trader: string;
      open_positions: number;
      total_exposure_usd: number;
      avg_confidence: number;
    }[];
    by_direction: {
      direction: string;
      count: number;
      exposure_usd: number;
    }[];
  };
  largest_positions: {
    id: string;
    trader: string;
    asset: string;
    direction: string;
    size_usd: number;
    entry_price: number | null;
    stop_loss: number | null;
    opened_at: string | null;
  }[];
}

export interface CorrelationPair {
  asset_a: string;
  asset_b: string;
  correlation: number;
  observations: number;
}

export interface CorrelationResponse {
  days: number;
  asset_correlations: CorrelationPair[];
  market_correlations: {
    trader_a: string;
    trader_b: string;
    correlation: number;
    observations: number;
  }[];
  assets_tracked: number;
  traders_tracked: number;
}

// ── WebSocket Events ───────────────────────────────────────────────────────

export type WSEventType =
  | "trade.opened"
  | "trade.closed"
  | "trade.updated"
  | "portfolio.snapshot"
  | "ai.decision"
  | "risk.alert"
  | "pace.update"
  | "cost.update"
  | "system.status"
  | "trader.paused"
  | "trader.resumed"
  | "kill_switch";

export interface WSTradeEvent {
  event: "trade.opened" | "trade.closed" | "trade.updated";
  data: Trade;
  timestamp: string;
}

export interface WSPortfolioEvent {
  event: "portfolio.snapshot";
  data: PortfolioSnapshot;
  timestamp: string;
}

export interface WSAIDecisionEvent {
  event: "ai.decision";
  data: AIDecision;
  timestamp: string;
}

export interface WSRiskAlertEvent {
  event: "risk.alert";
  data: { message: string; severity: string; details: Record<string, unknown> };
  timestamp: string;
}

export interface WSPaceEvent {
  event: "pace.update";
  data: PaceStatus;
  timestamp: string;
}

export interface WSCostEvent {
  event: "cost.update";
  data: { total_today: number; inference: number; fees: number };
  timestamp: string;
}

export interface WSSystemEvent {
  event: "system.status" | "trader.paused" | "trader.resumed" | "kill_switch";
  data: Record<string, unknown>;
  timestamp: string;
}

export type WSEvent =
  | WSTradeEvent
  | WSPortfolioEvent
  | WSAIDecisionEvent
  | WSRiskAlertEvent
  | WSPaceEvent
  | WSCostEvent
  | WSSystemEvent;

// ── Trade list response ────────────────────────────────────────────────────

export interface TradesResponse {
  trades: Trade[];
  total: number;
  limit: number;
  offset: number;
}

export interface AIDecisionsResponse {
  decisions: AIDecision[];
  limit: number;
  offset: number;
}

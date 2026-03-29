"""Strategy configuration and safety models."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from packages.core.models.signal import NormalizedSignal, Opportunity
from packages.core.models.portfolio_state import PortfolioState
from packages.core.models.trade import Direction, Market


class SafetyRails(BaseModel):
    """Safety constraints and risk limits for the trading system."""

    max_single_trade_pct: float = 0.25
    max_single_market_allocation: float = 0.60
    kill_switch_drawdown_pct: float = 0.50
    max_daily_drawdown_pct: float = 0.10
    mandatory_stop_loss: bool = True
    max_stop_loss_pct: float = 0.15
    max_leverage: float = 3.0
    max_daily_inference_cost: float = 15.00
    max_inference_to_profit_ratio: float = 0.20
    max_concurrent_positions: int = 30
    require_paper_trade_first: bool = True
    min_paper_trade_days: int = 7
    max_losing_streak_before_pause: int = 10
    cool_down_after_pause_hours: int = 4


class TraderConfig(BaseModel):
    """Top-level configuration for the trading system."""

    name: str = "ai-trader"
    mode: str = "paper"
    markets: list[Market] = Field(default_factory=lambda: [Market.POLYMARKET, Market.CRYPTO, Market.STOCKS])
    initial_balance: float = 0.0
    target_balance: Optional[float] = None
    target_date: Optional[datetime] = None
    safety_rails: SafetyRails = Field(default_factory=SafetyRails)
    screener_interval_minutes: int = 30
    rebalance_interval_minutes: int = 60
    max_positions_per_market: int = 10
    default_leverage: float = 1.0
    default_stop_loss_pct: float = 0.10
    default_take_profit_pct: float = 0.20
    enabled_strategies: list[str] = Field(default_factory=list)
    api_keys: dict[str, str] = Field(default_factory=dict)
    notifications_enabled: bool = True
    log_level: str = "INFO"
    metadata: dict[str, Any] = Field(default_factory=dict)


class StrategistInput(BaseModel):
    """Input data for the strategist decision-making process."""

    portfolio_state: PortfolioState
    opportunities: list[Opportunity] = Field(default_factory=list)
    normalized_signals: list[NormalizedSignal] = Field(default_factory=list)
    config: TraderConfig = Field(default_factory=TraderConfig)
    market_snapshots: dict[str, Any] = Field(default_factory=dict)
    recent_trade_results: list[dict] = Field(default_factory=list)
    current_inference_cost_today: float = 0.0
    budget_remaining: Optional[float] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StrategistOutput(BaseModel):
    """Output from the strategist decision-making process."""

    id: Optional[str] = None
    recommended_trades: list[dict] = Field(default_factory=list)
    signals_to_act_on: list[NormalizedSignal] = Field(default_factory=list)
    signals_to_skip: list[NormalizedSignal] = Field(default_factory=list)
    positions_to_close: list[str] = Field(default_factory=list)
    positions_to_adjust: list[dict] = Field(default_factory=list)
    rebalance_actions: list[dict] = Field(default_factory=list)
    reasoning: Optional[str] = None
    risk_assessment: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    estimated_portfolio_impact: Optional[float] = None
    inference_cost: float = 0.0
    duration_seconds: float = 0.0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)

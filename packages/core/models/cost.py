"""Cost tracking models for inference and trading costs."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from packages.core.models.trade import Market


class InferenceCost(BaseModel):
    """Cost of a single AI inference call."""

    id: Optional[str] = None
    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: Optional[float] = None
    purpose: Optional[str] = None
    trade_id: Optional[str] = None
    signal_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict = Field(default_factory=dict)


class TradeCost(BaseModel):
    """Costs associated with executing a single trade."""

    trade_id: Optional[str] = None
    market: Market
    exchange_fees: float = 0.0
    spread_cost: float = 0.0
    slippage_cost: float = 0.0
    funding_cost: float = 0.0
    gas_fees: float = 0.0
    total_cost: float = 0.0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict = Field(default_factory=dict)


class TradeCostBreakdown(BaseModel):
    """Full cost breakdown for a trade including inference costs."""

    trade_id: Optional[str] = None
    trade_cost: TradeCost = Field(default_factory=TradeCost)
    inference_costs: list[InferenceCost] = Field(default_factory=list)
    total_inference_cost: float = 0.0
    total_execution_cost: float = 0.0
    total_cost: float = 0.0
    gross_pnl: float = 0.0
    net_pnl: float = 0.0
    cost_to_profit_ratio: Optional[float] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict = Field(default_factory=dict)


class DailyCostSummary(BaseModel):
    """Aggregated costs for a single day."""

    date: str
    total_inference_cost: float = 0.0
    total_execution_cost: float = 0.0
    total_cost: float = 0.0
    inference_call_count: int = 0
    trade_count: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    gross_pnl: float = 0.0
    net_pnl: float = 0.0
    cost_to_profit_ratio: Optional[float] = None
    cost_by_model: dict[str, float] = Field(default_factory=dict)
    cost_by_purpose: dict[str, float] = Field(default_factory=dict)
    cost_by_market: dict[str, float] = Field(default_factory=dict)
    budget_remaining: Optional[float] = None
    budget_utilization_pct: Optional[float] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict = Field(default_factory=dict)


class NetExpectedValue(BaseModel):
    """Expected value calculation for a potential trade after all costs."""

    signal_id: Optional[str] = None
    market: Market
    symbol: str
    gross_expected_value: float = 0.0
    estimated_inference_cost: float = 0.0
    estimated_execution_cost: float = 0.0
    estimated_total_cost: float = 0.0
    net_expected_value: float = 0.0
    probability_of_profit: Optional[float] = None
    risk_reward_ratio: Optional[float] = None
    break_even_win_rate: Optional[float] = None
    is_profitable_after_costs: bool = False
    margin_of_safety: float = 0.0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict = Field(default_factory=dict)

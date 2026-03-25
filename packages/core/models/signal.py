"""Signal and market data models."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from packages.core.models.trade import Direction, Market


class DecisionType(str, Enum):
    SCREENER = "screener"
    ANALYST = "analyst"
    STRATEGIST = "strategist"


class TradeSignal(BaseModel):
    """A raw trading signal from any source."""

    id: Optional[str] = None
    source: str
    market: Market
    symbol: str
    direction: Direction
    confidence: float = Field(ge=0.0, le=1.0)
    strength: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    decision_type: DecisionType
    reasoning: Optional[str] = None
    suggested_entry: Optional[float] = None
    suggested_stop_loss: Optional[float] = None
    suggested_take_profit: Optional[float] = None
    suggested_quantity: Optional[float] = None
    suggested_leverage: Optional[float] = None
    timeframe: Optional[str] = None
    expiry_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict = Field(default_factory=dict)


class Opportunity(BaseModel):
    """A screened market opportunity with potential for a trade."""

    id: Optional[str] = None
    market: Market
    symbol: str
    title: Optional[str] = None
    description: Optional[str] = None
    current_price: Optional[float] = None
    estimated_edge: Optional[float] = None
    confidence: float = Field(ge=0.0, le=1.0)
    volume_24h: Optional[float] = None
    liquidity: Optional[float] = None
    volatility: Optional[float] = None
    category: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    source: Optional[str] = None
    url: Optional[str] = None
    expires_at: Optional[datetime] = None
    discovered_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict = Field(default_factory=dict)


class ScreenerResult(BaseModel):
    """Result from a market screener pass."""

    id: Optional[str] = None
    market: Market
    screener_name: str
    opportunities: list[Opportunity] = Field(default_factory=list)
    total_scanned: int = 0
    total_passed: int = 0
    filters_applied: list[str] = Field(default_factory=list)
    inference_cost: float = 0.0
    duration_seconds: float = 0.0
    run_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict = Field(default_factory=dict)


class NormalizedSignal(BaseModel):
    """A signal normalized across markets for cross-market comparison."""

    id: Optional[str] = None
    original_signal_id: Optional[str] = None
    market: Market
    symbol: str
    direction: Direction
    normalized_confidence: float = Field(ge=0.0, le=1.0)
    expected_return: Optional[float] = None
    expected_duration_hours: Optional[float] = None
    risk_adjusted_score: Optional[float] = None
    sharpe_estimate: Optional[float] = None
    max_drawdown_estimate: Optional[float] = None
    correlation_to_portfolio: Optional[float] = None
    inference_cost: float = 0.0
    source_signals: list[TradeSignal] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict = Field(default_factory=dict)


class MarketSnapshot(BaseModel):
    """Point-in-time snapshot of a market's state."""

    market: Market
    symbol: str
    price: float
    bid: Optional[float] = None
    ask: Optional[float] = None
    spread: Optional[float] = None
    volume_24h: Optional[float] = None
    change_24h_pct: Optional[float] = None
    high_24h: Optional[float] = None
    low_24h: Optional[float] = None
    market_cap: Optional[float] = None
    open_interest: Optional[float] = None
    funding_rate: Optional[float] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    source: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

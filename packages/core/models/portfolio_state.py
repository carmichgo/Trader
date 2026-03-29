"""Portfolio state and tracking models."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from packages.core.models.trade import Market, Position, Trade


class GoalFeasibility(str, Enum):
    ON_TRACK = "on_track"
    AT_RISK = "at_risk"
    UNREACHABLE = "unreachable"


class PaceStatus(str, Enum):
    WELL_AHEAD = "well_ahead"
    ON_TRACK = "on_track"
    BEHIND = "behind"
    FAR_BEHIND = "far_behind"


class PortfolioState(BaseModel):
    """Current state of the trading portfolio."""

    total_balance: float = 0.0
    available_balance: float = 0.0
    allocated_balance: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl_today: float = 0.0
    realized_pnl_total: float = 0.0
    open_positions: list[Position] = Field(default_factory=list)
    open_position_count: int = 0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    current_drawdown: float = 0.0
    max_drawdown: float = 0.0
    peak_balance: float = 0.0
    current_streak: int = 0
    losing_streak: int = 0
    allocation_by_market: dict[str, float] = Field(default_factory=dict)
    daily_pnl_history: list[float] = Field(default_factory=list)
    total_fees_paid: float = 0.0
    total_inference_cost: float = 0.0
    sharpe_ratio: Optional[float] = None
    sortino_ratio: Optional[float] = None
    profit_factor: Optional[float] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict = Field(default_factory=dict)


class TraderPortfolio(BaseModel):
    """Full trader portfolio with goal tracking and performance metrics."""

    id: Optional[str] = None
    name: str = "default"
    initial_balance: float = 0.0
    current_state: PortfolioState = Field(default_factory=PortfolioState)
    target_balance: Optional[float] = None
    target_date: Optional[datetime] = None
    goal_feasibility: GoalFeasibility = GoalFeasibility.ON_TRACK
    pace_status: PaceStatus = PaceStatus.ON_TRACK
    required_daily_return: Optional[float] = None
    actual_daily_return: Optional[float] = None
    days_elapsed: int = 0
    days_remaining: Optional[int] = None
    active_trades: list[Trade] = Field(default_factory=list)
    trade_history: list[Trade] = Field(default_factory=list)
    market_allocations: dict[str, float] = Field(default_factory=dict)
    is_paper_trading: bool = True
    is_paused: bool = False
    pause_reason: Optional[str] = None
    paused_at: Optional[datetime] = None
    resume_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None
    metadata: dict = Field(default_factory=dict)

"""SQLAlchemy ORM models for the AI trading system."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    starting_capital: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False
    )
    target_capital: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False
    )
    time_horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    plans: Mapped[list[StrategistPlan]] = relationship(
        "StrategistPlan", back_populates="goal", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_goals_is_active", "is_active"),
    )


class StrategistPlan(Base):
    __tablename__ = "strategist_plans"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    goal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("goals.id", ondelete="CASCADE"), nullable=False
    )
    plan_date: Mapped[date] = mapped_column(Date, nullable=False)
    allocations: Mapped[dict] = mapped_column(JSONB, nullable=False)
    trader_configs: Mapped[dict] = mapped_column(JSONB, nullable=False)
    daily_target: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    goal_feasibility: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=True
    )
    inference_cost: Mapped[Decimal] = mapped_column(
        Numeric(10, 6), nullable=True
    )
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    goal: Mapped[Goal] = relationship("Goal", back_populates="plans")

    __table_args__ = (
        Index("ix_strategist_plans_goal_id", "goal_id"),
        Index("ix_strategist_plans_plan_date", "plan_date"),
    )


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    trader: Mapped[str] = mapped_column(String(50), nullable=False)
    asset: Mapped[str] = mapped_column(String(100), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)  # long / short
    position_size_usd: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=True)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=True)
    exit_price: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=True)
    stop_loss: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=True)
    take_profit: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )  # pending / open / closed / cancelled
    close_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    gross_pnl: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    net_pnl: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    exchange_fee: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    slippage: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    screener_cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    analyst_cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    total_cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    screener_output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    analyst_output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ai_confidence: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 4), nullable=True
    )
    ai_model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    ai_decisions: Mapped[list[AIDecision]] = relationship(
        "AIDecision", back_populates="trade", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_trades_trader", "trader"),
        Index("ix_trades_asset", "asset"),
        Index("ix_trades_status", "status"),
        Index("ix_trades_opened_at", "opened_at"),
        Index("ix_trades_trader_status", "trader", "status"),
    )


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )
    total_capital: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    polymarket_capital: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=True
    )
    crypto_capital: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=True)
    stocks_capital: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=True)
    total_unrealized_pnl: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=True
    )
    total_realized_pnl_today: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=True
    )
    open_positions_count: Mapped[int] = mapped_column(Integer, nullable=True)
    daily_inference_cost: Mapped[Decimal] = mapped_column(
        Numeric(10, 6), nullable=True
    )
    daily_trading_fees: Mapped[Decimal] = mapped_column(
        Numeric(10, 6), nullable=True
    )
    drawdown_from_peak: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), nullable=True
    )


class AIDecision(Base):
    __tablename__ = "ai_decisions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    decision_type: Mapped[str] = mapped_column(String(50), nullable=False)
    trader: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=True)
    input_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    output_raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    related_trade_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("trades.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    trade: Mapped[Trade | None] = relationship("Trade", back_populates="ai_decisions")

    __table_args__ = (
        Index("ix_ai_decisions_decision_type", "decision_type"),
        Index("ix_ai_decisions_trader", "trader"),
        Index("ix_ai_decisions_created_at", "created_at"),
        Index("ix_ai_decisions_related_trade_id", "related_trade_id"),
    )


class MarketData(Base):
    __tablename__ = "market_data"

    time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )
    market: Mapped[str] = mapped_column(
        String(50), primary_key=True, nullable=False
    )
    asset: Mapped[str] = mapped_column(
        String(100), primary_key=True, nullable=False
    )
    open: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    volume: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_market_data_market_asset", "market", "asset"),
        Index("ix_market_data_asset_time", "asset", "time"),
    )


class DailyPerformance(Base):
    __tablename__ = "daily_performance"

    date: Mapped[date] = mapped_column(Date, primary_key=True, nullable=False)
    trader: Mapped[str] = mapped_column(
        String(50), primary_key=True, nullable=False
    )
    trades_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    winning_trades: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    losing_trades: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    gross_pnl: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=0, nullable=False
    )
    net_pnl: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=0, nullable=False
    )
    total_inference_cost: Mapped[Decimal] = mapped_column(
        Numeric(10, 6), default=0, nullable=False
    )
    total_trading_fees: Mapped[Decimal] = mapped_column(
        Numeric(10, 6), default=0, nullable=False
    )
    total_slippage: Mapped[Decimal] = mapped_column(
        Numeric(10, 6), default=0, nullable=False
    )
    max_drawdown_pct: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), nullable=True
    )
    win_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=True)
    avg_trade_pnl: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=True)
    sharpe_ratio: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=True)

    __table_args__ = (
        Index("ix_daily_performance_date", "date"),
        Index("ix_daily_performance_trader", "trader"),
    )

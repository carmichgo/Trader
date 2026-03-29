"""Shared pytest fixtures for the AI trading system test suite."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from packages.core.ai.client import AIResponse
from packages.core.config import AIConfig, SystemConfig
from packages.core.models.cost import InferenceCost, TradeCostBreakdown, TradeCost
from packages.core.models.portfolio_state import PortfolioState
from packages.core.models.signal import NormalizedSignal, Opportunity
from packages.core.models.strategy_config import SafetyRails, TraderConfig
from packages.core.models.trade import Direction, Market, Position, Trade, TradeStatus


# ---------------------------------------------------------------------------
# AI Client
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_ai_client() -> MagicMock:
    """A mocked AIClient that returns deterministic AIResponse objects."""
    client = MagicMock()

    default_response = AIResponse(
        content='{"opportunities": []}',
        input_tokens=500,
        output_tokens=200,
        cost_usd=0.0045,
        latency_ms=350,
        model="claude-sonnet-4-20250514",
    )

    client.call_sonnet = AsyncMock(return_value=default_response)
    client.call_opus = AsyncMock(return_value=default_response)
    return client


# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_redis() -> AsyncMock:
    """A mocked ``redis.asyncio.Redis`` instance.

    Simulates hget, hincrbyfloat, hincrby, pipeline, scan_iter, etc.
    """
    redis = AsyncMock()

    # hget returns None by default (no existing cost data)
    redis.hget = AsyncMock(return_value=None)
    redis.hgetall = AsyncMock(return_value={})

    # Pipeline mock that collects calls and executes them as a no-op
    pipe = AsyncMock()
    pipe.hincrbyfloat = MagicMock(return_value=pipe)
    pipe.hincrby = MagicMock(return_value=pipe)
    pipe.expire = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=[])
    redis.pipeline = MagicMock(return_value=pipe)

    # scan_iter yields nothing by default
    redis.scan_iter = MagicMock(return_value=AsyncIteratorMock([]))

    return redis


class AsyncIteratorMock:
    """Helper to create an async iterator from a plain list."""

    def __init__(self, items: list) -> None:
        self._items = items

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._items:
            raise StopAsyncIteration
        return self._items.pop(0)


# ---------------------------------------------------------------------------
# Database session
# ---------------------------------------------------------------------------


@pytest.fixture
def test_db_session() -> AsyncMock:
    """A mocked SQLAlchemy ``AsyncSession``."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock()
    session.rollback = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# Domain objects
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_trade() -> Trade:
    """A sample open trade in the crypto market."""
    return Trade(
        id="trade-001",
        market=Market.CRYPTO,
        symbol="BTC/USDT",
        direction=Direction.BUY,
        strategy="momentum",
        status=TradeStatus.OPEN,
        entry_price=42000.0,
        quantity=0.1,
        stop_loss_price=40000.0,
        take_profit_price=46000.0,
        leverage=1.0,
        confidence=0.75,
        is_paper_trade=True,
    )


@pytest.fixture
def sample_opportunity() -> Opportunity:
    """A sample screened opportunity."""
    return Opportunity(
        id="opp-001",
        market=Market.CRYPTO,
        symbol="ETH/USDT",
        title="ETH breakout above resistance",
        description="ETH showing strong momentum above $3200 resistance with volume confirmation.",
        current_price=3250.0,
        estimated_edge=0.05,
        confidence=0.72,
        volume_24h=1_500_000_000.0,
        liquidity=500_000_000.0,
        volatility=0.04,
        category="momentum",
        tags=["breakout", "volume"],
        source="screener-sonnet",
    )


@pytest.fixture
def sample_portfolio() -> PortfolioState:
    """A sample portfolio state with moderate exposure."""
    return PortfolioState(
        total_balance=10_000.0,
        available_balance=7_000.0,
        allocated_balance=3_000.0,
        unrealized_pnl=150.0,
        realized_pnl_today=50.0,
        realized_pnl_total=500.0,
        open_position_count=3,
        total_trades=25,
        winning_trades=15,
        losing_trades=10,
        win_rate=0.60,
        avg_win=120.0,
        avg_loss=80.0,
        largest_win=350.0,
        largest_loss=200.0,
        current_drawdown=0.03,
        max_drawdown=0.07,
        peak_balance=10_500.0,
        current_streak=2,
        losing_streak=0,
        allocation_by_market={"crypto": 2000.0, "stocks": 1000.0},
        total_fees_paid=25.0,
        total_inference_cost=2.50,
    )


@pytest.fixture
def sample_trader_config() -> TraderConfig:
    """A sample trader configuration for paper trading."""
    return TraderConfig(
        name="test-trader",
        mode="paper",
        markets=[Market.CRYPTO, Market.STOCKS],
        initial_balance=10_000.0,
        target_balance=20_000.0,
        target_date=datetime(2026, 6, 25, tzinfo=timezone.utc),
        safety_rails=SafetyRails(
            max_single_trade_pct=0.10,
            max_single_market_allocation=0.50,
            kill_switch_drawdown_pct=0.25,
            max_daily_drawdown_pct=0.05,
            mandatory_stop_loss=True,
            max_stop_loss_pct=0.15,
            max_leverage=3.0,
            max_daily_inference_cost=15.0,
            max_concurrent_positions=10,
            max_losing_streak_before_pause=5,
            cool_down_after_pause_hours=4,
        ),
        screener_interval_minutes=30,
        max_positions_per_market=5,
        default_leverage=1.0,
        default_stop_loss_pct=0.10,
        default_take_profit_pct=0.20,
    )


@pytest.fixture
def sample_safety_rails() -> SafetyRails:
    """A standalone SafetyRails instance with conservative limits."""
    return SafetyRails(
        max_single_trade_pct=0.10,
        max_single_market_allocation=0.50,
        kill_switch_drawdown_pct=0.25,
        max_daily_drawdown_pct=0.05,
        mandatory_stop_loss=True,
        max_stop_loss_pct=0.15,
        max_leverage=3.0,
        max_daily_inference_cost=15.0,
        max_concurrent_positions=10,
        max_losing_streak_before_pause=5,
        cool_down_after_pause_hours=4,
    )

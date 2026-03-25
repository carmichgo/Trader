"""Unit tests for RiskManager: pre-trade checks and NEV calculation."""

from __future__ import annotations

import pytest

from packages.core.models.cost import TradeCostBreakdown, TradeCost
from packages.core.models.portfolio_state import PortfolioState
from packages.core.models.signal import NormalizedSignal
from packages.core.models.strategy_config import SafetyRails, TraderConfig
from packages.core.models.trade import Direction, Market
from packages.core.risk.manager import RiskManager, TradePlan


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_signal(
    confidence: float = 0.70,
    expected_return: float | None = 0.05,
    correlation: float | None = None,
) -> NormalizedSignal:
    return NormalizedSignal(
        market=Market.CRYPTO,
        symbol="BTC/USDT",
        direction=Direction.BUY,
        normalized_confidence=confidence,
        expected_return=expected_return,
        correlation_to_portfolio=correlation,
    )


def _make_plan(
    size_usd: float = 500.0,
    stop_loss_pct: float = 0.10,
    take_profit_pct: float = 0.20,
    confidence: float = 0.70,
    expected_return: float | None = 0.05,
    correlation: float | None = None,
) -> TradePlan:
    return TradePlan(
        signal=_make_signal(confidence, expected_return, correlation),
        proposed_size_usd=size_usd,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
    )


# ---------------------------------------------------------------------------
# NEV tests
# ---------------------------------------------------------------------------


class TestNEV:
    """Tests for the NEV (Net Expected Value) approval / rejection logic."""

    def test_nev_positive_approved(
        self,
        sample_portfolio: PortfolioState,
        sample_safety_rails: SafetyRails,
    ) -> None:
        """A trade with positive expected return should be approved."""
        rm = RiskManager(nev_min_threshold=0.0)
        plan = _make_plan(size_usd=500.0, expected_return=0.05)
        result = rm.check(plan, sample_portfolio, TraderConfig(), sample_safety_rails)
        assert result.approved is True

    def test_nev_negative_rejected(
        self,
        sample_portfolio: PortfolioState,
        sample_safety_rails: SafetyRails,
    ) -> None:
        """A trade with negative expected return should be rejected."""
        rm = RiskManager(nev_min_threshold=0.0)
        plan = _make_plan(size_usd=500.0, expected_return=-0.05)
        result = rm.check(plan, sample_portfolio, TraderConfig(), sample_safety_rails)
        assert result.approved is False
        assert "Expected return" in (result.reason or "")


# ---------------------------------------------------------------------------
# Position size tests
# ---------------------------------------------------------------------------


class TestPositionSizeLimit:
    """Tests for the position size check."""

    def test_position_size_limit_exceeded(
        self,
        sample_safety_rails: SafetyRails,
    ) -> None:
        """A trade exceeding max_single_trade_pct should be clamped, not rejected."""
        rm = RiskManager()
        portfolio = PortfolioState(
            total_balance=10_000.0,
            available_balance=10_000.0,
            open_position_count=0,
            current_drawdown=0.0,
            max_drawdown=0.0,
        )
        # max_single_trade_pct=0.10 => max $1000
        plan = _make_plan(size_usd=5_000.0)
        result = rm.check(plan, portfolio, TraderConfig(), sample_safety_rails)

        # The trade should be approved but the size clamped to $1000
        assert result.approved is True
        assert result.adjusted_size is not None
        assert result.adjusted_size <= portfolio.total_balance * sample_safety_rails.max_single_trade_pct


# ---------------------------------------------------------------------------
# Max concurrent positions test
# ---------------------------------------------------------------------------


class TestMaxConcurrentPositions:
    """Tests for the concurrent position cap."""

    def test_max_concurrent_positions(
        self,
        sample_safety_rails: SafetyRails,
    ) -> None:
        """When open_position_count >= max_concurrent_positions, the trade is rejected."""
        rm = RiskManager()
        portfolio = PortfolioState(
            total_balance=10_000.0,
            available_balance=5_000.0,
            open_position_count=10,  # matches the cap of 10
            current_drawdown=0.0,
            max_drawdown=0.0,
        )
        plan = _make_plan(size_usd=500.0)
        result = rm.check(plan, portfolio, TraderConfig(), sample_safety_rails)

        assert result.approved is False
        assert "concurrent positions" in (result.reason or "").lower()


# ---------------------------------------------------------------------------
# Drawdown limit test
# ---------------------------------------------------------------------------


class TestDrawdownLimit:
    """Tests for the daily drawdown proximity check."""

    def test_drawdown_limit(
        self,
        sample_safety_rails: SafetyRails,
    ) -> None:
        """When current drawdown is near the daily limit, trades are blocked."""
        rm = RiskManager()
        # max_daily_drawdown_pct=0.05, threshold = 0.05 * 0.80 = 0.04
        # Set current_drawdown to 0.045 which is >= 0.04
        portfolio = PortfolioState(
            total_balance=10_000.0,
            available_balance=5_000.0,
            open_position_count=0,
            current_drawdown=0.045,
            max_drawdown=0.045,
        )
        plan = _make_plan(size_usd=500.0)
        result = rm.check(plan, portfolio, TraderConfig(), sample_safety_rails)

        assert result.approved is False
        assert "drawdown" in (result.reason or "").lower()

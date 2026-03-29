"""Unit tests for ThroughputPlanner: goal-to-trades throughput calculation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from packages.core.models.portfolio_state import PortfolioState
from packages.core.models.strategy_config import SafetyRails, StrategistInput, TraderConfig
from packages.core.models.trade import Market
from packages.core.planning.throughput_planner import ThroughputPlanner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_strategist_input(
    *,
    current_balance: float = 10_000.0,
    initial_balance: float = 10_000.0,
    target_balance: float = 20_000.0,
    target_days_from_now: int = 90,
    markets: list[Market] | None = None,
    recent_results: list[dict] | None = None,
) -> StrategistInput:
    target_date = datetime.utcnow() + timedelta(days=target_days_from_now)
    config = TraderConfig(
        initial_balance=initial_balance,
        target_balance=target_balance,
        target_date=target_date,
        markets=markets or [Market.CRYPTO],
    )
    portfolio = PortfolioState(
        total_balance=current_balance,
        available_balance=current_balance * 0.7,
    )
    return StrategistInput(
        portfolio_state=portfolio,
        config=config,
        recent_trade_results=recent_results or [],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAggressiveGoal:
    """When the target is very ambitious relative to time, higher frequency is needed."""

    def test_aggressive_goal_high_frequency(self) -> None:
        """A 100x target in 15 days demands very high daily return and is infeasible."""
        planner = ThroughputPlanner(default_trades_per_day=5.0)
        si = _make_strategist_input(
            current_balance=1_000.0,
            target_balance=100_000.0,
            target_days_from_now=15,
        )
        plan = planner.plan(si)

        # 100x in 15 days requires >35% daily return -- clearly infeasible (>10%)
        assert plan.daily_compound_return_needed > 0.10
        assert plan.is_feasible is False
        assert plan.days_remaining > 0
        assert plan.daily_target_usd > 0.0


class TestConservativeGoal:
    """When the target is modest, the planner should produce a feasible plan."""

    def test_conservative_goal_low_frequency(self) -> None:
        """A 2x target in 365 days should be feasible with low daily return."""
        planner = ThroughputPlanner(default_trades_per_day=5.0)
        si = _make_strategist_input(
            current_balance=10_000.0,
            target_balance=20_000.0,
            target_days_from_now=365,
        )
        plan = planner.plan(si)

        # 2x in 365 days => ~0.19% daily return -- very achievable
        assert plan.daily_compound_return_needed < 0.01
        assert plan.is_feasible is True
        assert len(plan.per_trader) == 1  # one market (crypto)
        assert plan.per_trader[0].market == "crypto"
        assert plan.per_trader[0].allocation_pct == pytest.approx(1.0)


class TestZeroEdgeTrader:
    """A trader with zero or negative edge should get zero useful trades."""

    def test_zero_edge_trader_gets_zero_trades(self) -> None:
        """When historical win rate produces negative edge, the trader is infeasible."""
        planner = ThroughputPlanner(
            default_trades_per_day=5.0,
            default_win_rate=0.30,  # with 1.5 R:R => edge = 0.30*1.5 - 0.70 = -0.25
            default_avg_win_loss_ratio=1.5,
        )
        si = _make_strategist_input(
            current_balance=10_000.0,
            target_balance=20_000.0,
            target_days_from_now=90,
        )
        plan = planner.plan(si)

        # The per-trader requirement should be flagged infeasible
        assert len(plan.per_trader) >= 1
        for req in plan.per_trader:
            assert req.is_feasible is False
            assert "Negative edge" in req.notes
        assert plan.is_feasible is False

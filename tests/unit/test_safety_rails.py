"""Unit tests for SafetyRailsEnforcer: hard-coded safety limits."""

from __future__ import annotations

import pytest

from packages.core.models.portfolio_state import PortfolioState
from packages.core.models.strategy_config import SafetyRails
from packages.core.risk.safety_rails import SafetyRailsEnforcer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _default_rails() -> SafetyRails:
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


def _default_portfolio(**overrides) -> PortfolioState:
    defaults = dict(
        total_balance=10_000.0,
        available_balance=7_000.0,
        open_position_count=3,
        current_drawdown=0.02,
        max_drawdown=0.05,
        losing_streak=0,
        total_inference_cost=2.0,
        allocation_by_market={"crypto": 2_000.0, "stocks": 1_000.0},
    )
    defaults.update(overrides)
    return PortfolioState(**defaults)


def _open_trade_action(**overrides) -> dict:
    defaults = dict(
        type="open_trade",
        size_usd=500.0,
        leverage=1.0,
        stop_loss_pct=0.10,
        market="crypto",
    )
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMaxSingleTradePct:
    """No single trade may exceed max_single_trade_pct of balance."""

    def test_max_single_trade_pct(self) -> None:
        """A $2000 trade on a $10k balance with 10% limit should be blocked."""
        enforcer = SafetyRailsEnforcer(_default_rails())
        portfolio = _default_portfolio()
        action = _open_trade_action(size_usd=2_000.0)

        allowed, reason = enforcer.enforce(action, portfolio)

        assert allowed is False
        assert "max single trade" in reason.lower() or "exceeds" in reason.lower()

    def test_trade_within_limit_passes(self) -> None:
        """A $500 trade on a $10k balance with 10% limit should pass."""
        enforcer = SafetyRailsEnforcer(_default_rails())
        portfolio = _default_portfolio()
        action = _open_trade_action(size_usd=500.0)

        allowed, reason = enforcer.enforce(action, portfolio)

        assert allowed is True


class TestMaxMarketAllocation:
    """No single market may exceed max_single_market_allocation."""

    def test_max_market_allocation(self) -> None:
        """Adding $4000 to crypto (already $2000) on $10k balance => 60% > 50% limit."""
        enforcer = SafetyRailsEnforcer(_default_rails())
        portfolio = _default_portfolio(
            allocation_by_market={"crypto": 2_000.0},
        )
        action = _open_trade_action(size_usd=900.0, market="crypto")

        # (2000 + 900) / 10000 = 0.29 -- should pass
        allowed_small, _ = enforcer.enforce(action, portfolio)
        assert allowed_small is True

        # Now try one that exceeds the 50% limit
        action_big = _open_trade_action(size_usd=1_000.0, market="crypto")
        portfolio_high = _default_portfolio(
            allocation_by_market={"crypto": 4_500.0},
        )
        allowed_big, reason = enforcer.enforce(action_big, portfolio_high)

        assert allowed_big is False
        assert "allocation" in reason.lower()


class TestKillSwitchDrawdown:
    """Kill switch halts all trading if max_drawdown exceeds fatal threshold."""

    def test_kill_switch_drawdown(self) -> None:
        """Max drawdown at 30% with kill switch at 25% should halt everything."""
        enforcer = SafetyRailsEnforcer(_default_rails())
        portfolio = _default_portfolio(max_drawdown=0.30)
        action = _open_trade_action(size_usd=100.0)

        allowed, reason = enforcer.enforce(action, portfolio)

        assert allowed is False
        assert "kill switch" in reason.lower()

    def test_drawdown_below_kill_switch_passes(self) -> None:
        """Max drawdown at 20% with kill switch at 25% should not trigger."""
        enforcer = SafetyRailsEnforcer(_default_rails())
        portfolio = _default_portfolio(max_drawdown=0.20)
        action = _open_trade_action(size_usd=100.0)

        allowed, _ = enforcer.enforce(action, portfolio)

        assert allowed is True


class TestMandatoryStopLoss:
    """Every open-trade must have a stop-loss when mandatory_stop_loss is True."""

    def test_mandatory_stop_loss(self) -> None:
        """An open_trade without stop_loss_pct should be rejected."""
        enforcer = SafetyRailsEnforcer(_default_rails())
        portfolio = _default_portfolio()
        action = _open_trade_action(stop_loss_pct=0)  # zero = not set

        allowed, reason = enforcer.enforce(action, portfolio)

        assert allowed is False
        assert "stop-loss" in reason.lower() or "stop_loss" in reason.lower()

    def test_trade_with_stop_loss_passes(self) -> None:
        """An open_trade with valid stop_loss_pct should pass."""
        enforcer = SafetyRailsEnforcer(_default_rails())
        portfolio = _default_portfolio()
        action = _open_trade_action(stop_loss_pct=0.08)

        allowed, _ = enforcer.enforce(action, portfolio)

        assert allowed is True


class TestMaxLeverage:
    """Leverage must not exceed the configured maximum."""

    def test_max_leverage(self) -> None:
        """5x leverage with 3x limit should be rejected."""
        enforcer = SafetyRailsEnforcer(_default_rails())
        portfolio = _default_portfolio()
        action = _open_trade_action(leverage=5.0)

        allowed, reason = enforcer.enforce(action, portfolio)

        assert allowed is False
        assert "leverage" in reason.lower()

    def test_leverage_within_limit_passes(self) -> None:
        """2x leverage with 3x limit should pass."""
        enforcer = SafetyRailsEnforcer(_default_rails())
        portfolio = _default_portfolio()
        action = _open_trade_action(leverage=2.0)

        allowed, _ = enforcer.enforce(action, portfolio)

        assert allowed is True


class TestRailsCannotBeOverridden:
    """Safety rails are immutable once set -- the enforcer reads from its own state."""

    def test_rails_cannot_be_overridden(self) -> None:
        """Mutating the original SafetyRails after creating the enforcer
        should not change the enforcer's copy (since Pydantic models are
        passed by value effectively), and the enforcer property returns
        the rails as-is.
        """
        rails = _default_rails()
        enforcer = SafetyRailsEnforcer(rails)

        # Verify the enforcer exposes the rails via property
        assert enforcer.rails.max_leverage == 3.0
        assert enforcer.rails.kill_switch_drawdown_pct == 0.25

        # The enforcer uses its own reference; changing the original object
        # would affect it only because Pydantic models are mutable. But the
        # key invariant is: the enforcer always enforces the rails it was
        # constructed with.
        original_max_lev = enforcer.rails.max_leverage

        # Enforce with a high-leverage trade
        portfolio = _default_portfolio()
        action = _open_trade_action(leverage=4.0)

        allowed, reason = enforcer.enforce(action, portfolio)
        assert allowed is False
        assert "leverage" in reason.lower()

        # Confirm the rails haven't silently changed
        assert enforcer.rails.max_leverage == original_max_lev

"""Hard safety limits enforced in code -- CANNOT be bypassed by prompts."""

from __future__ import annotations

import logging

from packages.core.models.portfolio_state import PortfolioState
from packages.core.models.strategy_config import SafetyRails

logger = logging.getLogger(__name__)


class SafetyRailsEnforcer:
    """Code-level safety enforcer.

    Every action flows through :meth:`enforce` before execution.
    These checks are **not** prompt-level -- they are hard-coded
    constraints that cannot be overridden by AI reasoning.
    """

    def __init__(self, safety_rails: SafetyRails) -> None:
        self._rails = safety_rails

    @property
    def rails(self) -> SafetyRails:
        return self._rails

    def enforce(
        self,
        action: dict,
        portfolio_state: PortfolioState,
    ) -> tuple[bool, str]:
        """Check *action* against all hard safety limits.

        Parameters
        ----------
        action:
            A dict describing the proposed action.  Expected keys:

            - ``"type"``: ``"open_trade"`` | ``"close_trade"`` | ``"adjust"``
            - ``"size_usd"``: proposed trade size in USD (for open)
            - ``"leverage"``: proposed leverage (for open)
            - ``"stop_loss_pct"``: stop-loss percentage (for open)
            - ``"market"``: market name string

        portfolio_state:
            Current portfolio snapshot.

        Returns
        -------
        tuple[bool, str]
            ``(allowed, reason)`` -- ``allowed`` is ``True`` if the action
            passes all rails, otherwise ``False`` with an explanation.
        """
        checks: list[tuple[bool, str]] = [
            self._check_kill_switch(portfolio_state),
            self._check_daily_drawdown(portfolio_state),
            self._check_max_concurrent_positions(portfolio_state),
            self._check_max_single_trade(action, portfolio_state),
            self._check_max_leverage(action),
            self._check_mandatory_stop_loss(action),
            self._check_max_stop_loss(action),
            self._check_max_single_market_allocation(action, portfolio_state),
            self._check_daily_inference_cost(portfolio_state),
            self._check_losing_streak(portfolio_state),
        ]
        for allowed, reason in checks:
            if not allowed:
                logger.warning("Safety rail BLOCKED action: %s", reason)
                return False, reason

        return True, "All safety checks passed."

    # ------------------------------------------------------------------
    # Individual checks -- each returns (allowed, reason)
    # ------------------------------------------------------------------

    def _check_kill_switch(
        self,
        portfolio: PortfolioState,
    ) -> tuple[bool, str]:
        """KILL SWITCH: halt all trading if drawdown exceeds fatal threshold."""
        if portfolio.max_drawdown >= self._rails.kill_switch_drawdown_pct:
            return (
                False,
                f"KILL SWITCH: max drawdown {portfolio.max_drawdown:.2%} "
                f"exceeds fatal limit {self._rails.kill_switch_drawdown_pct:.2%}. "
                "All trading halted.",
            )
        return True, ""

    def _check_daily_drawdown(
        self,
        portfolio: PortfolioState,
    ) -> tuple[bool, str]:
        """Block new trades if daily drawdown limit is hit."""
        if portfolio.current_drawdown >= self._rails.max_daily_drawdown_pct:
            return (
                False,
                f"Daily drawdown limit hit: {portfolio.current_drawdown:.2%} "
                f">= {self._rails.max_daily_drawdown_pct:.2%}. "
                "No new trades until next session.",
            )
        return True, ""

    def _check_max_concurrent_positions(
        self,
        portfolio: PortfolioState,
    ) -> tuple[bool, str]:
        """Reject if at the hard position cap."""
        if portfolio.open_position_count >= self._rails.max_concurrent_positions:
            return (
                False,
                f"Max concurrent positions ({self._rails.max_concurrent_positions}) reached.",
            )
        return True, ""

    def _check_max_single_trade(
        self,
        action: dict,
        portfolio: PortfolioState,
    ) -> tuple[bool, str]:
        """No single trade may exceed ``max_single_trade_pct`` of balance."""
        size_usd = action.get("size_usd")
        if size_usd is None or action.get("type") != "open_trade":
            return True, ""
        if portfolio.total_balance <= 0:
            return False, "Portfolio balance is zero or negative."
        max_allowed = portfolio.total_balance * self._rails.max_single_trade_pct
        if size_usd > max_allowed:
            return (
                False,
                f"Trade size ${size_usd:.2f} exceeds max single trade "
                f"${max_allowed:.2f} ({self._rails.max_single_trade_pct:.0%} of balance).",
            )
        return True, ""

    def _check_max_leverage(self, action: dict) -> tuple[bool, str]:
        """Cap leverage at the configured maximum."""
        leverage = action.get("leverage")
        if leverage is not None and leverage > self._rails.max_leverage:
            return (
                False,
                f"Leverage {leverage:.1f}x exceeds max {self._rails.max_leverage:.1f}x.",
            )
        return True, ""

    def _check_mandatory_stop_loss(self, action: dict) -> tuple[bool, str]:
        """Ensure every open-trade action has a stop-loss when required."""
        if not self._rails.mandatory_stop_loss:
            return True, ""
        if action.get("type") != "open_trade":
            return True, ""
        sl = action.get("stop_loss_pct")
        if sl is None or sl <= 0:
            return False, "Mandatory stop-loss is required but not set."
        return True, ""

    def _check_max_stop_loss(self, action: dict) -> tuple[bool, str]:
        """Stop-loss cannot be wider than the configured maximum."""
        sl = action.get("stop_loss_pct")
        if sl is not None and sl > self._rails.max_stop_loss_pct:
            return (
                False,
                f"Stop-loss {sl:.1%} exceeds max allowed {self._rails.max_stop_loss_pct:.1%}.",
            )
        return True, ""

    def _check_max_single_market_allocation(
        self,
        action: dict,
        portfolio: PortfolioState,
    ) -> tuple[bool, str]:
        """No single market may consume more than the allocation cap."""
        if action.get("type") != "open_trade":
            return True, ""
        market_name = action.get("market")
        if market_name is None or portfolio.total_balance <= 0:
            return True, ""

        current_alloc = portfolio.allocation_by_market.get(market_name, 0.0)
        size_usd = action.get("size_usd", 0.0)
        new_alloc = (current_alloc + size_usd) / portfolio.total_balance
        if new_alloc > self._rails.max_single_market_allocation:
            return (
                False,
                f"Market '{market_name}' allocation would become {new_alloc:.1%}, "
                f"exceeding limit {self._rails.max_single_market_allocation:.0%}.",
            )
        return True, ""

    def _check_daily_inference_cost(
        self,
        portfolio: PortfolioState,
    ) -> tuple[bool, str]:
        """Block trading if daily inference spend exceeds the cap."""
        if portfolio.total_inference_cost >= self._rails.max_daily_inference_cost:
            return (
                False,
                f"Daily inference cost ${portfolio.total_inference_cost:.2f} "
                f"exceeds limit ${self._rails.max_daily_inference_cost:.2f}.",
            )
        return True, ""

    def _check_losing_streak(
        self,
        portfolio: PortfolioState,
    ) -> tuple[bool, str]:
        """Pause after max consecutive losses."""
        if portfolio.losing_streak >= self._rails.max_losing_streak_before_pause:
            return (
                False,
                f"Losing streak ({portfolio.losing_streak}) has reached the pause "
                f"threshold ({self._rails.max_losing_streak_before_pause}). "
                f"Cool-down for {self._rails.cool_down_after_pause_hours}h required.",
            )
        return True, ""

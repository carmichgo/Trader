"""Main risk manager: pre-trade checks and NEV calculation."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel, Field

from packages.core.models.cost import NetExpectedValue, TradeCostBreakdown
from packages.core.models.portfolio_state import PortfolioState
from packages.core.models.signal import NormalizedSignal
from packages.core.models.strategy_config import SafetyRails, TraderConfig
from packages.core.models.trade import Market, Position

logger = logging.getLogger(__name__)


class TradePlan(BaseModel):
    """A proposed trade awaiting risk approval."""

    signal: NormalizedSignal
    proposed_size_usd: float = 0.0
    proposed_leverage: float = 1.0
    stop_loss_pct: float = 0.10
    take_profit_pct: float = 0.20
    estimated_duration_hours: float = 24.0
    metadata: dict = Field(default_factory=dict)


class RiskCheckResult(BaseModel):
    """Result of a risk check on a proposed trade."""

    approved: bool = False
    reason: str | None = None
    adjusted_size: float | None = None


class RiskManager:
    """Orchestrates all pre-trade risk checks.

    Performs position size limits, max concurrent positions, correlation
    checks, daily drawdown proximity, and NEV filtering before any trade
    is allowed to proceed.
    """

    def __init__(self, *, nev_min_threshold: float = 0.0) -> None:
        self._nev_min_threshold = nev_min_threshold

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(
        self,
        trade_plan: TradePlan,
        portfolio: PortfolioState,
        trader_config: TraderConfig,
        safety_rails: SafetyRails,
    ) -> RiskCheckResult:
        """Run all risk checks on a proposed trade.

        Returns a :class:`RiskCheckResult` indicating whether the trade
        is approved, and if not, why.  When the trade is approved but
        the size was reduced, ``adjusted_size`` contains the new value.
        """
        # 1. Position size limit
        result = self._check_position_size(trade_plan, portfolio, safety_rails)
        if not result.approved:
            return result

        # 2. Max concurrent positions
        result = self._check_max_concurrent(portfolio, safety_rails)
        if not result.approved:
            return result

        # 3. Correlation with existing positions
        result = self._check_correlation(trade_plan, portfolio)
        if not result.approved:
            return result

        # 4. Daily drawdown proximity
        result = self._check_drawdown_proximity(portfolio, safety_rails)
        if not result.approved:
            return result

        # 5. NEV filter
        result = self._check_nev(trade_plan)
        if not result.approved:
            return result

        # All checks passed -- may have an adjusted size from step 1.
        adjusted = self._clamp_size(trade_plan, portfolio, safety_rails)
        return RiskCheckResult(
            approved=True,
            reason=None,
            adjusted_size=adjusted if adjusted != trade_plan.proposed_size_usd else None,
        )

    def calculate_nev(
        self,
        trade_plan: TradePlan,
        costs: TradeCostBreakdown,
    ) -> float:
        """Implement the full Net Expected Value formula.

        NEV = (P_win * avg_win) - (P_loss * avg_loss) - total_costs

        Where:
        - P_win  = signal confidence
        - avg_win  = proposed_size * take_profit_pct
        - P_loss = 1 - P_win
        - avg_loss = proposed_size * stop_loss_pct
        - total_costs = execution costs + inference costs
        """
        p_win = trade_plan.signal.normalized_confidence
        p_loss = 1.0 - p_win

        size = trade_plan.proposed_size_usd
        avg_win = size * trade_plan.take_profit_pct
        avg_loss = size * trade_plan.stop_loss_pct

        gross_ev = (p_win * avg_win) - (p_loss * avg_loss)
        total_costs = costs.total_cost
        nev = gross_ev - total_costs

        logger.debug(
            "NEV calc: p_win=%.3f, avg_win=%.2f, p_loss=%.3f, avg_loss=%.2f, "
            "gross_ev=%.2f, costs=%.2f, nev=%.2f",
            p_win,
            avg_win,
            p_loss,
            avg_loss,
            gross_ev,
            total_costs,
            nev,
        )
        return nev

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_position_size(
        self,
        trade_plan: TradePlan,
        portfolio: PortfolioState,
        safety_rails: SafetyRails,
    ) -> RiskCheckResult:
        """Ensure the trade does not exceed max single-trade allocation."""
        max_usd = portfolio.total_balance * safety_rails.max_single_trade_pct
        if max_usd <= 0:
            return RiskCheckResult(
                approved=False,
                reason="Portfolio balance is zero or negative; cannot allocate.",
            )
        if trade_plan.proposed_size_usd > max_usd:
            logger.info(
                "Position size $%.2f exceeds limit $%.2f (%.0f%% of balance). Clamping.",
                trade_plan.proposed_size_usd,
                max_usd,
                safety_rails.max_single_trade_pct * 100,
            )
            return RiskCheckResult(approved=True, adjusted_size=max_usd)
        return RiskCheckResult(approved=True)

    def _check_max_concurrent(
        self,
        portfolio: PortfolioState,
        safety_rails: SafetyRails,
    ) -> RiskCheckResult:
        """Reject if already at the concurrent-position cap."""
        if portfolio.open_position_count >= safety_rails.max_concurrent_positions:
            return RiskCheckResult(
                approved=False,
                reason=(
                    f"Max concurrent positions reached "
                    f"({portfolio.open_position_count}/{safety_rails.max_concurrent_positions})."
                ),
            )
        return RiskCheckResult(approved=True)

    def _check_correlation(
        self,
        trade_plan: TradePlan,
        portfolio: PortfolioState,
    ) -> RiskCheckResult:
        """Warn / reject if the new trade is highly correlated to existing.

        Uses the signal's ``correlation_to_portfolio`` field when available.
        A correlation above 0.85 is rejected to avoid concentration risk.
        """
        corr = trade_plan.signal.correlation_to_portfolio
        if corr is not None and corr > 0.85:
            return RiskCheckResult(
                approved=False,
                reason=(
                    f"Trade correlation to portfolio too high ({corr:.2f} > 0.85). "
                    "Reduces diversification."
                ),
            )
        return RiskCheckResult(approved=True)

    def _check_drawdown_proximity(
        self,
        portfolio: PortfolioState,
        safety_rails: SafetyRails,
    ) -> RiskCheckResult:
        """Reject new trades when close to the daily drawdown limit.

        If current drawdown is within 20% of the daily max, block new entries.
        """
        if safety_rails.max_daily_drawdown_pct <= 0:
            return RiskCheckResult(approved=True)

        headroom_pct = 0.80  # block when 80% of daily limit consumed
        threshold = safety_rails.max_daily_drawdown_pct * headroom_pct

        # current_drawdown is stored as a positive fraction (e.g. 0.08 = 8%).
        if portfolio.current_drawdown >= threshold:
            return RiskCheckResult(
                approved=False,
                reason=(
                    f"Daily drawdown ({portfolio.current_drawdown:.2%}) is near limit "
                    f"({safety_rails.max_daily_drawdown_pct:.2%}). "
                    "New trades blocked until next session."
                ),
            )
        return RiskCheckResult(approved=True)

    def _check_nev(self, trade_plan: TradePlan) -> RiskCheckResult:
        """Reject trades whose expected return (from signal) is negative."""
        expected = trade_plan.signal.expected_return
        if expected is not None and expected < self._nev_min_threshold:
            return RiskCheckResult(
                approved=False,
                reason=(
                    f"Expected return ({expected:.4f}) is below the NEV threshold "
                    f"({self._nev_min_threshold:.4f})."
                ),
            )
        return RiskCheckResult(approved=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _clamp_size(
        self,
        trade_plan: TradePlan,
        portfolio: PortfolioState,
        safety_rails: SafetyRails,
    ) -> float:
        """Return the effective trade size after applying all caps."""
        max_single = portfolio.total_balance * safety_rails.max_single_trade_pct
        size = min(trade_plan.proposed_size_usd, max_single)

        # Also respect available balance.
        size = min(size, portfolio.available_balance)
        return max(size, 0.0)

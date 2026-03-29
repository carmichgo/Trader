"""Goal-to-trades throughput calculation.

Works backwards from the portfolio goal to determine how many trades
each trader needs to execute per day at what edge to stay on track.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime

from pydantic import BaseModel, Field

from packages.core.models.strategy_config import StrategistInput, TraderConfig

logger = logging.getLogger(__name__)


class PerTraderRequirement(BaseModel):
    """Required throughput for a single trader (market)."""

    market: str
    allocation_pct: float = 0.0
    daily_target_usd: float = 0.0
    required_trades_per_day: float = 0.0
    required_avg_profit_per_trade: float = 0.0
    required_win_rate: float = 0.0
    historical_win_rate: float | None = None
    historical_avg_profit: float | None = None
    is_feasible: bool = True
    notes: str = ""


class ThroughputPlan(BaseModel):
    """Output of the throughput planner: daily requirements to hit the goal."""

    daily_compound_return_needed: float = 0.0
    daily_target_usd: float = 0.0
    total_days: int = 0
    days_elapsed: int = 0
    days_remaining: int = 0
    starting_capital: float = 0.0
    target_capital: float = 0.0
    current_capital: float = 0.0
    per_trader: list[PerTraderRequirement] = Field(default_factory=list)
    is_feasible: bool = True
    feasibility_notes: str = ""
    computed_at: datetime = Field(default_factory=datetime.utcnow)


class ThroughputPlanner:
    """Calculates required daily compound return from goal and builds per-trader targets.

    The core formula:
        daily_return = (target / current) ^ (1 / days_remaining) - 1

    Then allocates the daily USD target across traders (markets) based on
    configured allocation weights and historical edge.

    Parameters
    ----------
    default_trades_per_day:
        Assumed number of trades a single trader executes per day if no
        historical data is available.
    default_win_rate:
        Conservative default win rate assumption.
    default_avg_win_loss_ratio:
        Ratio of average win to average loss (e.g. 1.5 means wins are
        1.5x the size of losses).
    """

    def __init__(
        self,
        *,
        default_trades_per_day: float = 5.0,
        default_win_rate: float = 0.55,
        default_avg_win_loss_ratio: float = 1.5,
    ) -> None:
        self._default_trades_per_day = default_trades_per_day
        self._default_win_rate = default_win_rate
        self._default_avg_win_loss_ratio = default_avg_win_loss_ratio

    def plan(self, strategist_input: StrategistInput) -> ThroughputPlan:
        """Compute the throughput plan from current state and goals.

        Parameters
        ----------
        strategist_input:
            Contains the portfolio state, config (with target balance/date),
            and recent trade history for calibration.

        Returns
        -------
        ThroughputPlan
            Complete daily/per-trader requirements.
        """
        config = strategist_input.config
        portfolio = strategist_input.portfolio_state

        starting_capital = config.initial_balance
        current_capital = portfolio.total_balance or starting_capital
        target_capital = config.target_balance or current_capital * 2.0

        # Time horizon
        total_days, days_elapsed, days_remaining = self._compute_time_horizon(config)

        if days_remaining <= 0:
            return ThroughputPlan(
                starting_capital=starting_capital,
                current_capital=current_capital,
                target_capital=target_capital,
                total_days=total_days,
                days_elapsed=days_elapsed,
                days_remaining=0,
                is_feasible=False,
                feasibility_notes="No days remaining in the time horizon.",
            )

        # Required daily compound return
        if current_capital <= 0:
            return ThroughputPlan(
                starting_capital=starting_capital,
                current_capital=current_capital,
                target_capital=target_capital,
                total_days=total_days,
                days_elapsed=days_elapsed,
                days_remaining=days_remaining,
                is_feasible=False,
                feasibility_notes="Current capital is zero or negative.",
            )

        growth_factor = target_capital / current_capital
        daily_return = growth_factor ** (1.0 / days_remaining) - 1.0
        daily_target_usd = current_capital * daily_return

        # Build per-trader requirements
        market_allocations = self._get_market_allocations(config)
        per_trader = self._build_per_trader(
            market_allocations=market_allocations,
            daily_target_usd=daily_target_usd,
            recent_results=strategist_input.recent_trade_results,
        )

        # Feasibility check
        is_feasible = True
        feasibility_notes = ""
        if daily_return > 0.10:
            is_feasible = False
            feasibility_notes = (
                f"Required daily return of {daily_return:.2%} is unrealistically high. "
                "Consider extending the time horizon or reducing the target."
            )
        elif daily_return > 0.05:
            feasibility_notes = (
                f"Required daily return of {daily_return:.2%} is aggressive. "
                "High risk of drawdown."
            )

        for req in per_trader:
            if not req.is_feasible:
                is_feasible = False

        return ThroughputPlan(
            daily_compound_return_needed=daily_return,
            daily_target_usd=daily_target_usd,
            total_days=total_days,
            days_elapsed=days_elapsed,
            days_remaining=days_remaining,
            starting_capital=starting_capital,
            target_capital=target_capital,
            current_capital=current_capital,
            per_trader=per_trader,
            is_feasible=is_feasible,
            feasibility_notes=feasibility_notes,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_time_horizon(
        self,
        config: TraderConfig,
    ) -> tuple[int, int, int]:
        """Return (total_days, days_elapsed, days_remaining)."""
        if config.target_date is None:
            # Default to 90 days from now
            return 90, 0, 90

        now = datetime.utcnow()
        total_delta = config.target_date - now
        total_days = max(int(total_delta.total_seconds() / 86400), 0)

        # Days elapsed since the system started (approximate from balance history)
        days_elapsed = 0  # Will be refined when trade history is available
        days_remaining = max(total_days - days_elapsed, 0)

        return total_days, days_elapsed, days_remaining

    def _get_market_allocations(self, config: TraderConfig) -> dict[str, float]:
        """Derive per-market allocation weights from config.

        If no explicit allocations are set, distributes equally across
        enabled markets.
        """
        markets = [m.value for m in config.markets]
        if not markets:
            return {}
        equal_weight = 1.0 / len(markets)
        return {m: equal_weight for m in markets}

    def _build_per_trader(
        self,
        *,
        market_allocations: dict[str, float],
        daily_target_usd: float,
        recent_results: list[dict],
    ) -> list[PerTraderRequirement]:
        """Build per-trader requirements from allocations and historical edge."""
        # Aggregate recent results by market
        market_stats: dict[str, dict] = {}
        for result in recent_results:
            mkt = result.get("market", "unknown")
            if mkt not in market_stats:
                market_stats[mkt] = {"wins": 0, "losses": 0, "total_profit": 0.0}
            if result.get("pnl", 0) > 0:
                market_stats[mkt]["wins"] += 1
            else:
                market_stats[mkt]["losses"] += 1
            market_stats[mkt]["total_profit"] += result.get("pnl", 0.0)

        requirements: list[PerTraderRequirement] = []
        for market, alloc_pct in market_allocations.items():
            trader_daily_target = daily_target_usd * alloc_pct

            # Use historical stats if available, else defaults
            stats = market_stats.get(market)
            if stats and (stats["wins"] + stats["losses"]) > 0:
                total_trades = stats["wins"] + stats["losses"]
                hist_wr = stats["wins"] / total_trades
                hist_avg = stats["total_profit"] / total_trades
            else:
                hist_wr = None
                hist_avg = None

            win_rate = hist_wr if hist_wr is not None else self._default_win_rate
            avg_win_loss_ratio = self._default_avg_win_loss_ratio

            # Expected profit per trade = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)
            # With avg_win = R * avg_loss:
            # E[trade] = avg_loss * (win_rate * R - (1 - win_rate))
            # We need: trades_per_day * E[trade] = trader_daily_target
            edge_per_unit = win_rate * avg_win_loss_ratio - (1.0 - win_rate)

            if edge_per_unit <= 0:
                requirements.append(
                    PerTraderRequirement(
                        market=market,
                        allocation_pct=alloc_pct,
                        daily_target_usd=trader_daily_target,
                        required_win_rate=win_rate,
                        historical_win_rate=hist_wr,
                        historical_avg_profit=hist_avg,
                        is_feasible=False,
                        notes=f"Negative edge ({edge_per_unit:.4f}). Cannot meet target.",
                    )
                )
                continue

            # Solve for required trades at the default trade size assumption
            # This is illustrative; actual sizing uses the risk manager
            required_avg_profit = trader_daily_target / self._default_trades_per_day
            required_trades = self._default_trades_per_day

            # If historical avg profit is known, recalculate trades needed
            if hist_avg is not None and hist_avg > 0:
                required_trades = trader_daily_target / hist_avg
                required_avg_profit = hist_avg

            is_feasible = required_trades <= self._default_trades_per_day * 3
            notes = ""
            if not is_feasible:
                notes = (
                    f"Requires {required_trades:.1f} trades/day which exceeds "
                    f"3x the default ({self._default_trades_per_day * 3:.0f})."
                )

            requirements.append(
                PerTraderRequirement(
                    market=market,
                    allocation_pct=alloc_pct,
                    daily_target_usd=trader_daily_target,
                    required_trades_per_day=required_trades,
                    required_avg_profit_per_trade=required_avg_profit,
                    required_win_rate=win_rate,
                    historical_win_rate=hist_wr,
                    historical_avg_profit=hist_avg,
                    is_feasible=is_feasible,
                    notes=notes,
                )
            )

        return requirements

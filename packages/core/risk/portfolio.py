"""Cross-market exposure and correlation tracking."""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from typing import Optional

from packages.core.models.portfolio_state import PortfolioState
from packages.core.models.trade import Market, Position

logger = logging.getLogger(__name__)


class PortfolioRiskTracker:
    """Track cross-market position correlations and exposure.

    Maintains a running view of how capital is distributed across markets
    and symbols, and produces a simple correlation matrix based on
    co-movement of positions.
    """

    def __init__(self, max_single_market_allocation: float = 0.60) -> None:
        self._max_single_market_allocation = max_single_market_allocation
        # symbol -> list of daily return observations (simplified)
        self._return_history: dict[str, list[float]] = defaultdict(list)

    # ------------------------------------------------------------------
    # Exposure helpers
    # ------------------------------------------------------------------

    def get_total_exposure(self, portfolio: PortfolioState) -> float:
        """Return the total notional exposure across all open positions."""
        return sum(self._position_exposure(p) for p in portfolio.open_positions)

    def get_market_exposure(
        self,
        portfolio: PortfolioState,
        market: Market,
    ) -> float:
        """Return total notional exposure for a single market."""
        return sum(
            self._position_exposure(p)
            for p in portfolio.open_positions
            if p.market == market
        )

    def get_exposure_by_market(
        self,
        portfolio: PortfolioState,
    ) -> dict[Market, float]:
        """Return a mapping of market -> total exposure."""
        exposure: dict[Market, float] = defaultdict(float)
        for pos in portfolio.open_positions:
            exposure[pos.market] += self._position_exposure(pos)
        return dict(exposure)

    # ------------------------------------------------------------------
    # Correlation
    # ------------------------------------------------------------------

    def record_returns(self, symbol: str, daily_return: float) -> None:
        """Record a daily return observation for correlation tracking."""
        self._return_history[symbol].append(daily_return)

    def get_correlation_matrix(self) -> dict[tuple[str, str], float]:
        """Compute pairwise Pearson correlation for tracked symbols.

        Returns a dict keyed by ``(symbol_a, symbol_b)`` with correlation
        values in ``[-1, 1]``.  Only pairs with at least 5 overlapping
        observations are included.
        """
        symbols = sorted(self._return_history.keys())
        matrix: dict[tuple[str, str], float] = {}
        for i, sym_a in enumerate(symbols):
            for sym_b in symbols[i:]:
                corr = self._pearson(
                    self._return_history[sym_a],
                    self._return_history[sym_b],
                )
                if corr is not None:
                    matrix[(sym_a, sym_b)] = corr
                    if sym_a != sym_b:
                        matrix[(sym_b, sym_a)] = corr
        return matrix

    # ------------------------------------------------------------------
    # Concentration risk
    # ------------------------------------------------------------------

    def check_concentration_risk(
        self,
        portfolio: PortfolioState,
    ) -> list[str]:
        """Return a list of warning messages for concentrated exposures.

        Checks:
        - Any single market exceeding ``max_single_market_allocation``
        - Any single symbol exceeding 20% of total balance
        """
        warnings: list[str] = []
        total = portfolio.total_balance
        if total <= 0:
            return warnings

        # Per-market check
        by_market = self.get_exposure_by_market(portfolio)
        for mkt, exposure in by_market.items():
            ratio = exposure / total
            if ratio > self._max_single_market_allocation:
                warnings.append(
                    f"Market {mkt.value} exposure is {ratio:.1%} of portfolio "
                    f"(limit {self._max_single_market_allocation:.0%})."
                )

        # Per-symbol check (20% hard cap)
        symbol_exposure: dict[str, float] = defaultdict(float)
        for pos in portfolio.open_positions:
            symbol_exposure[pos.symbol] += self._position_exposure(pos)

        for sym, exposure in symbol_exposure.items():
            ratio = exposure / total
            if ratio > 0.20:
                warnings.append(
                    f"Symbol {sym} exposure is {ratio:.1%} of portfolio (>20%)."
                )

        return warnings

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _position_exposure(pos: Position) -> float:
        """Notional exposure = quantity * entry_price * leverage."""
        price = pos.current_price if pos.current_price is not None else pos.entry_price
        return abs(pos.quantity * price * pos.leverage)

    @staticmethod
    def _pearson(xs: list[float], ys: list[float]) -> float | None:
        """Compute Pearson correlation between two equal-length series.

        Returns ``None`` if fewer than 5 overlapping observations.
        """
        n = min(len(xs), len(ys))
        if n < 5:
            return None
        xs, ys = xs[:n], ys[:n]
        mean_x = sum(xs) / n
        mean_y = sum(ys) / n
        cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
        std_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
        std_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
        if std_x == 0 or std_y == 0:
            return None
        return cov / (std_x * std_y)

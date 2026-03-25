"""Pre-trade slippage estimation via order-book simulation."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from packages.core.models import Direction

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Order-book level representation
# ------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class OrderBookLevel:
    """A single price level in an order book."""

    price: float
    size_usd: float


@dataclass(slots=True)
class OrderBook:
    """Simplified order book with bid / ask sides."""

    bids: list[OrderBookLevel] = field(default_factory=list)  # best (highest) first
    asks: list[OrderBookLevel] = field(default_factory=list)  # best (lowest) first
    mid_price: Optional[float] = None

    def best_bid(self) -> Optional[float]:
        return self.bids[0].price if self.bids else None

    def best_ask(self) -> Optional[float]:
        return self.asks[0].price if self.asks else None

    def computed_mid(self) -> Optional[float]:
        if self.mid_price is not None:
            return self.mid_price
        bb, ba = self.best_bid(), self.best_ask()
        if bb is not None and ba is not None:
            return (bb + ba) / 2.0
        return None


# ------------------------------------------------------------------
# Historical slippage record
# ------------------------------------------------------------------

@dataclass(slots=True)
class SlippageRecord:
    """One observed slippage measurement for model calibration."""

    asset: str
    side: Direction
    size_usd: float
    estimated_slippage_pct: float
    actual_slippage_pct: Optional[float] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ------------------------------------------------------------------
# Estimator
# ------------------------------------------------------------------

class SlippageEstimator:
    """Estimates expected slippage by walking a snapshot of the order book.

    The model also stores historical estimate-vs-actual records so the
    estimation can be calibrated over time.
    """

    def __init__(self, *, default_slippage_pct: float = 0.10) -> None:
        """
        Parameters
        ----------
        default_slippage_pct:
            Fallback slippage (as a percentage, e.g. 0.10 = 0.10 %) used
            when the order book is empty or unavailable.
        """
        self._default_slippage_pct = default_slippage_pct
        self._history: list[SlippageRecord] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def estimate(
        self,
        asset: str,
        size_usd: float,
        side: Direction,
        order_book: Optional[OrderBook] = None,
    ) -> float:
        """Estimate slippage **as a percentage** for a market order.

        Parameters
        ----------
        asset:
            Symbol / ticker (used only for logging and history keying).
        size_usd:
            Notional order size in USD.
        side:
            Trade direction.  BUY / SHORT walk the *asks*; SELL walks the *bids*.
        order_book:
            Current order-book snapshot.  If ``None`` or empty the default
            slippage is returned.

        Returns
        -------
        float
            Estimated slippage as a **percentage** (e.g. 0.05 means 0.05 %).
        """
        if order_book is None:
            slippage = self._default_slippage_pct
        else:
            slippage = self._walk_book(size_usd, side, order_book)

        record = SlippageRecord(
            asset=asset,
            side=side,
            size_usd=size_usd,
            estimated_slippage_pct=slippage,
        )
        self._history.append(record)

        logger.debug(
            "Slippage estimate  asset=%s side=%s size=$%.2f  -> %.4f%%",
            asset,
            side.value,
            size_usd,
            slippage,
        )
        return slippage

    def record_actual(
        self,
        asset: str,
        side: Direction,
        size_usd: float,
        actual_slippage_pct: float,
    ) -> None:
        """Store an observed actual slippage for calibration.

        If a matching estimate exists in history (same asset, side, size)
        the *actual_slippage_pct* is attached; otherwise a standalone record
        is appended.
        """
        # Try to backfill the most recent matching estimate that has no actual.
        for record in reversed(self._history):
            if (
                record.asset == asset
                and record.side == side
                and record.size_usd == size_usd
                and record.actual_slippage_pct is None
            ):
                record.actual_slippage_pct = actual_slippage_pct
                logger.debug(
                    "Backfilled actual slippage for %s: est=%.4f%% actual=%.4f%%",
                    asset,
                    record.estimated_slippage_pct,
                    actual_slippage_pct,
                )
                return

        # No matching estimate – just record it as a standalone observation.
        self._history.append(
            SlippageRecord(
                asset=asset,
                side=side,
                size_usd=size_usd,
                estimated_slippage_pct=self._default_slippage_pct,
                actual_slippage_pct=actual_slippage_pct,
            )
        )

    def get_history(self, asset: Optional[str] = None) -> list[SlippageRecord]:
        """Return stored slippage records, optionally filtered by *asset*."""
        if asset is None:
            return list(self._history)
        return [r for r in self._history if r.asset == asset]

    def mean_estimation_error(self, asset: Optional[str] = None) -> Optional[float]:
        """Mean signed error (estimated - actual) across calibrated records.

        Returns ``None`` if there are no records with both estimated and
        actual values.
        """
        records = self.get_history(asset)
        paired = [
            r for r in records
            if r.actual_slippage_pct is not None
        ]
        if not paired:
            return None
        return sum(
            r.estimated_slippage_pct - r.actual_slippage_pct  # type: ignore[operator]
            for r in paired
        ) / len(paired)

    # ------------------------------------------------------------------
    # Internal: order-book walk
    # ------------------------------------------------------------------

    def _walk_book(
        self,
        size_usd: float,
        side: Direction,
        book: OrderBook,
    ) -> float:
        """Simulate filling *size_usd* against the order book.

        Returns slippage as a percentage relative to the mid price.
        """
        mid = book.computed_mid()
        if mid is None or mid == 0:
            return self._default_slippage_pct

        # Choose the relevant side of the book.
        levels = book.asks if side in (Direction.BUY, Direction.SHORT) else book.bids
        if not levels:
            return self._default_slippage_pct

        remaining_usd = size_usd
        total_cost = 0.0
        total_filled_usd = 0.0

        for level in levels:
            if remaining_usd <= 0:
                break
            fill = min(remaining_usd, level.size_usd)
            total_cost += fill * level.price
            total_filled_usd += fill
            remaining_usd -= fill

        if total_filled_usd == 0:
            return self._default_slippage_pct

        # If the book was not deep enough, the unfilled portion is priced
        # at the worst level seen + a penalty.
        if remaining_usd > 0 and levels:
            worst_price = levels[-1].price
            penalty = worst_price * 0.005  # 0.5 % beyond worst level
            total_cost += remaining_usd * (worst_price + penalty)
            total_filled_usd += remaining_usd

        vwap = total_cost / total_filled_usd
        slippage_pct = abs(vwap - mid) / mid * 100.0
        return slippage_pct

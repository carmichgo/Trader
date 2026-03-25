"""Intraday pace monitoring: compares actual P&L vs expected based on time elapsed.

IMPORTANT: FAR_BEHIND does NOT mean take worse trades.  It is purely
informational and may cause the cadence controller to scan more frequently,
but it must never lower quality thresholds.
"""

from __future__ import annotations

import logging
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class PaceStatus(str, Enum):
    """How actual progress compares to the required daily target."""

    WELL_AHEAD = "well_ahead"
    ON_TRACK = "on_track"
    BEHIND = "behind"
    FAR_BEHIND = "far_behind"


class PaceSnapshot(BaseModel):
    """Point-in-time pace information."""

    status: PaceStatus = PaceStatus.ON_TRACK
    pnl_today: float = 0.0
    daily_target_usd: float = 0.0
    expected_pnl_now: float = 0.0
    progress_pct: float = 0.0
    trades_today: int = 0
    time_elapsed_pct: float = 0.0
    checked_at: datetime = Field(default_factory=datetime.utcnow)


class PaceMonitor:
    """Tracks intraday progress against the daily P&L target.

    Compares ``actual P&L`` vs ``expected P&L`` based on the fraction of
    the trading day that has elapsed.

    Parameters
    ----------
    daily_target_usd:
        The USD target for the day (from the throughput planner).
    trading_hours:
        Number of hours in a trading day (default 24 for crypto/polymarket).
    day_start_hour:
        UTC hour when the trading day starts (default 0).
    """

    # Thresholds for pace classification (ratio of actual / expected)
    _WELL_AHEAD_RATIO = 1.50
    _ON_TRACK_MIN = 0.70
    _BEHIND_MIN = 0.40
    # Below _BEHIND_MIN = FAR_BEHIND

    def __init__(
        self,
        *,
        daily_target_usd: float = 0.0,
        trading_hours: float = 24.0,
        day_start_hour: int = 0,
    ) -> None:
        self._daily_target_usd = daily_target_usd
        self._trading_hours = trading_hours
        self._day_start_hour = day_start_hour

        self._pnl_today: float = 0.0
        self._trades_today: int = 0
        self._current_day: str = datetime.utcnow().strftime("%Y-%m-%d")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_daily_target(self, target_usd: float) -> None:
        """Update the daily target (called when the throughput plan refreshes)."""
        self._daily_target_usd = target_usd

    def record_trade(self, pnl: float, *, now: datetime | None = None) -> None:
        """Record a completed trade's P&L.

        Parameters
        ----------
        pnl:
            Net P&L of the trade (positive = profit, negative = loss).
        now:
            Optional timestamp override for testing.
        """
        now = now or datetime.utcnow()
        self._maybe_reset_day(now)
        self._pnl_today += pnl
        self._trades_today += 1

    def check_pace(self, *, now: datetime | None = None) -> PaceStatus:
        """Evaluate current pace against the daily target.

        Returns
        -------
        PaceStatus
            One of WELL_AHEAD, ON_TRACK, BEHIND, FAR_BEHIND.
        """
        return self.snapshot(now=now).status

    def snapshot(self, *, now: datetime | None = None) -> PaceSnapshot:
        """Return a full pace snapshot."""
        now = now or datetime.utcnow()
        self._maybe_reset_day(now)

        time_pct = self._time_elapsed_pct(now)
        expected_pnl = self._daily_target_usd * time_pct

        if self._daily_target_usd <= 0 or expected_pnl <= 0:
            # No target set or day hasn't started; default to on-track
            status = PaceStatus.ON_TRACK
            progress_pct = 0.0
        else:
            ratio = self._pnl_today / expected_pnl if expected_pnl > 0 else 0.0
            progress_pct = (
                self._pnl_today / self._daily_target_usd * 100.0
                if self._daily_target_usd > 0
                else 0.0
            )
            status = self._classify(ratio)

        return PaceSnapshot(
            status=status,
            pnl_today=self._pnl_today,
            daily_target_usd=self._daily_target_usd,
            expected_pnl_now=expected_pnl,
            progress_pct=progress_pct,
            trades_today=self._trades_today,
            time_elapsed_pct=time_pct * 100.0,
            checked_at=now,
        )

    def reset(self) -> None:
        """Manually reset all daily counters."""
        self._pnl_today = 0.0
        self._trades_today = 0
        self._current_day = datetime.utcnow().strftime("%Y-%m-%d")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _time_elapsed_pct(self, now: datetime) -> float:
        """Fraction of the trading day that has elapsed (0.0 to 1.0)."""
        hours_since_start = (
            (now.hour - self._day_start_hour) % 24
            + now.minute / 60.0
            + now.second / 3600.0
        )
        return min(max(hours_since_start / self._trading_hours, 0.0), 1.0)

    def _classify(self, ratio: float) -> PaceStatus:
        """Classify a pnl-to-expected ratio into a PaceStatus."""
        if ratio >= self._WELL_AHEAD_RATIO:
            return PaceStatus.WELL_AHEAD
        if ratio >= self._ON_TRACK_MIN:
            return PaceStatus.ON_TRACK
        if ratio >= self._BEHIND_MIN:
            return PaceStatus.BEHIND
        return PaceStatus.FAR_BEHIND

    def _maybe_reset_day(self, now: datetime) -> None:
        today = now.strftime("%Y-%m-%d")
        if today != self._current_day:
            logger.info(
                "New day %s: resetting pace monitor (prev P&L: $%.2f, trades: %d).",
                today,
                self._pnl_today,
                self._trades_today,
            )
            self._pnl_today = 0.0
            self._trades_today = 0
            self._current_day = today

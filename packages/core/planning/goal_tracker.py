"""Goal progress tracking: compound growth curve vs actual equity path."""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class GoalProgress(BaseModel):
    """Summary of progress toward the portfolio goal."""

    starting_capital: float = 0.0
    target_capital: float = 0.0
    current_capital: float = 0.0
    total_days: int = 0
    days_elapsed: int = 0
    days_remaining: int = 0
    progress_pct: float = 0.0
    days_ahead_or_behind: float = 0.0
    required_daily_return: float = 0.0
    actual_daily_return: float = 0.0
    on_track: bool = True
    checked_at: datetime = Field(default_factory=datetime.utcnow)


class GoalTracker:
    """Compares actual equity path vs required compound growth curve.

    Parameters
    ----------
    starting_capital:
        Capital at the beginning of the tracking period.
    target_capital:
        Target capital to reach.
    total_days:
        Total number of days in the plan.
    start_date:
        The date the plan began.  Defaults to now.
    """

    def __init__(
        self,
        *,
        starting_capital: float,
        target_capital: float,
        total_days: int,
        start_date: datetime | None = None,
    ) -> None:
        self._starting_capital = starting_capital
        self._target_capital = target_capital
        self._total_days = max(total_days, 1)
        self._start_date = start_date or datetime.utcnow()

        # Pre-compute the required daily compound return
        if starting_capital > 0 and target_capital > starting_capital:
            self._daily_return = (
                (target_capital / starting_capital) ** (1.0 / self._total_days) - 1.0
            )
        else:
            self._daily_return = 0.0

        # Equity history: list of (day_index, equity)
        self._equity_history: list[tuple[int, float]] = [(0, starting_capital)]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_equity(self, equity: float, *, now: datetime | None = None) -> None:
        """Record a daily equity observation.

        Parameters
        ----------
        equity:
            Current total portfolio equity.
        now:
            Optional timestamp override for testing.
        """
        day_idx = self._day_index(now)
        self._equity_history.append((day_idx, equity))

    def get_compound_curve(self) -> list[tuple[int, float]]:
        """Return the required compound growth curve as (day, equity) pairs.

        Returns one point per day from day 0 to ``total_days``.
        """
        curve: list[tuple[int, float]] = []
        for day in range(self._total_days + 1):
            expected = self._starting_capital * ((1.0 + self._daily_return) ** day)
            curve.append((day, expected))
        return curve

    def get_actual_curve(self) -> list[tuple[int, float]]:
        """Return the actual equity curve as recorded."""
        return list(self._equity_history)

    def get_progress_pct(self, *, now: datetime | None = None) -> float:
        """Return progress toward the goal as a percentage (0-100).

        Based on how much of the required growth has been achieved:
        ``(current - start) / (target - start) * 100``
        """
        current = self._latest_equity()
        total_needed = self._target_capital - self._starting_capital
        if total_needed <= 0:
            return 100.0
        achieved = current - self._starting_capital
        return max(0.0, min(100.0, (achieved / total_needed) * 100.0))

    def days_ahead_or_behind(self, *, now: datetime | None = None) -> float:
        """Return how many days ahead (+) or behind (-) schedule.

        Computes what day on the compound curve corresponds to the current
        equity, then compares that to the actual elapsed days.

        Positive = ahead of schedule, negative = behind.
        """
        current = self._latest_equity()
        day_elapsed = self._day_index(now)

        if self._daily_return <= 0 or current <= 0 or self._starting_capital <= 0:
            return 0.0

        # What day would the compound curve reach `current`?
        # current = start * (1 + r)^d  =>  d = log(current/start) / log(1+r)
        try:
            curve_day = math.log(current / self._starting_capital) / math.log(
                1.0 + self._daily_return
            )
        except (ValueError, ZeroDivisionError):
            return 0.0

        return curve_day - day_elapsed

    def get_progress(self, *, now: datetime | None = None) -> GoalProgress:
        """Return a full progress report."""
        now = now or datetime.utcnow()
        day_elapsed = self._day_index(now)
        days_remaining = max(self._total_days - day_elapsed, 0)
        current = self._latest_equity()

        # Actual daily return from start
        if day_elapsed > 0 and self._starting_capital > 0 and current > 0:
            actual_daily = (current / self._starting_capital) ** (1.0 / day_elapsed) - 1.0
        else:
            actual_daily = 0.0

        ahead_behind = self.days_ahead_or_behind(now=now)

        return GoalProgress(
            starting_capital=self._starting_capital,
            target_capital=self._target_capital,
            current_capital=current,
            total_days=self._total_days,
            days_elapsed=day_elapsed,
            days_remaining=days_remaining,
            progress_pct=self.get_progress_pct(now=now),
            days_ahead_or_behind=ahead_behind,
            required_daily_return=self._daily_return,
            actual_daily_return=actual_daily,
            on_track=ahead_behind >= -1.0,
            checked_at=now,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _day_index(self, now: datetime | None = None) -> int:
        """Return the current day index (0-based) from the start date."""
        now = now or datetime.utcnow()
        delta = now - self._start_date
        return max(int(delta.total_seconds() / 86400), 0)

    def _latest_equity(self) -> float:
        """Return the most recently recorded equity value."""
        if not self._equity_history:
            return self._starting_capital
        return self._equity_history[-1][1]

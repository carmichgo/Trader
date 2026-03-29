"""Overtrading prevention: trade frequency limits and losing-streak cool-downs."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class FrequencyStats(BaseModel):
    """Current frequency-limiter statistics."""

    trades_today: int = 0
    max_trades_per_day: int = 50
    wins_today: int = 0
    losses_today: int = 0
    current_losing_streak: int = 0
    max_losing_streak: int = 10
    is_at_limit: bool = False
    is_cooling_down: bool = False
    cool_down_remaining_seconds: float = 0.0
    last_trade_at: datetime | None = None


class FrequencyLimiter:
    """Prevents overtrading by limiting trade frequency and pausing on losing streaks.

    Parameters
    ----------
    max_trades_per_day:
        Hard cap on trades per calendar day.
    max_losing_streak:
        Number of consecutive losses before a mandatory cool-down.
    cool_down_hours:
        Hours to pause after hitting the losing-streak limit.
    """

    def __init__(
        self,
        *,
        max_trades_per_day: int = 50,
        max_losing_streak: int = 10,
        cool_down_hours: int = 4,
    ) -> None:
        self._max_trades_per_day = max_trades_per_day
        self._max_losing_streak = max_losing_streak
        self._cool_down_hours = cool_down_hours

        self._current_day: str = datetime.utcnow().strftime("%Y-%m-%d")
        self._trades_today: int = 0
        self._wins_today: int = 0
        self._losses_today: int = 0
        self._current_losing_streak: int = 0
        self._last_trade_at: datetime | None = None

        self._cool_down_until: datetime | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_trade(self, won: bool, *, now: datetime | None = None) -> None:
        """Record the outcome of a completed trade.

        Parameters
        ----------
        won:
            ``True`` if the trade was profitable, ``False`` otherwise.
        now:
            Optional timestamp override for testing.
        """
        now = now or datetime.utcnow()
        self._maybe_reset_day(now)

        self._trades_today += 1
        self._last_trade_at = now

        if won:
            self._wins_today += 1
            self._current_losing_streak = 0
        else:
            self._losses_today += 1
            self._current_losing_streak += 1

        # Trigger cool-down on losing streak
        if self._current_losing_streak >= self._max_losing_streak:
            self._cool_down_until = now + timedelta(hours=self._cool_down_hours)
            logger.warning(
                "Losing streak of %d reached. Cool-down until %s.",
                self._current_losing_streak,
                self._cool_down_until.isoformat(),
            )

    def is_at_limit(self, *, now: datetime | None = None) -> bool:
        """Return ``True`` if the daily trade limit has been reached."""
        now = now or datetime.utcnow()
        self._maybe_reset_day(now)
        return self._trades_today >= self._max_trades_per_day

    def should_cool_down(self, *, now: datetime | None = None) -> bool:
        """Return ``True`` if in a cool-down period from a losing streak."""
        now = now or datetime.utcnow()
        self._maybe_reset_day(now)
        if self._cool_down_until is None:
            return False
        if now >= self._cool_down_until:
            # Cool-down has expired
            self._cool_down_until = None
            self._current_losing_streak = 0
            logger.info("Cool-down period ended. Trading resumed.")
            return False
        return True

    def can_trade(self, *, now: datetime | None = None) -> tuple[bool, str]:
        """Convenience check combining limit and cool-down.

        Returns
        -------
        tuple[bool, str]
            ``(allowed, reason)``
        """
        now = now or datetime.utcnow()
        if self.should_cool_down(now=now):
            remaining = (self._cool_down_until - now).total_seconds() if self._cool_down_until else 0
            return False, (
                f"Cool-down active after {self._current_losing_streak} consecutive losses. "
                f"{remaining / 60:.0f} minutes remaining."
            )
        if self.is_at_limit(now=now):
            return False, (
                f"Daily trade limit reached ({self._trades_today}/{self._max_trades_per_day})."
            )
        return True, "OK"

    def get_stats(self, *, now: datetime | None = None) -> FrequencyStats:
        """Return current frequency-limiter statistics."""
        now = now or datetime.utcnow()
        self._maybe_reset_day(now)

        cool_down_remaining = 0.0
        if self._cool_down_until is not None and now < self._cool_down_until:
            cool_down_remaining = (self._cool_down_until - now).total_seconds()

        return FrequencyStats(
            trades_today=self._trades_today,
            max_trades_per_day=self._max_trades_per_day,
            wins_today=self._wins_today,
            losses_today=self._losses_today,
            current_losing_streak=self._current_losing_streak,
            max_losing_streak=self._max_losing_streak,
            is_at_limit=self._trades_today >= self._max_trades_per_day,
            is_cooling_down=self.should_cool_down(now=now),
            cool_down_remaining_seconds=cool_down_remaining,
            last_trade_at=self._last_trade_at,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _maybe_reset_day(self, now: datetime) -> None:
        """Reset daily counters when the calendar day rolls over."""
        today = now.strftime("%Y-%m-%d")
        if today != self._current_day:
            logger.info(
                "New day %s: resetting frequency counters (prev: %d trades, %d W / %d L).",
                today,
                self._trades_today,
                self._wins_today,
                self._losses_today,
            )
            self._current_day = today
            self._trades_today = 0
            self._wins_today = 0
            self._losses_today = 0
            # Don't reset losing streak -- it persists across days
            # Don't reset cool-down -- it persists by time

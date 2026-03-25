"""Drawdown tracking and automatic trading pause."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class DrawdownSnapshot(BaseModel):
    """Point-in-time drawdown state."""

    peak_equity: float = 0.0
    current_equity: float = 0.0
    drawdown_pct: float = 0.0
    daily_start_equity: float = 0.0
    daily_drawdown_pct: float = 0.0
    is_paused: bool = False
    pause_reason: str | None = None
    paused_at: datetime | None = None
    resume_at: datetime | None = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class DrawdownMonitor:
    """Tracks peak equity, current drawdown, and daily drawdown.

    Automatically pauses trading when the daily drawdown limit is hit
    and triggers the kill switch when the overall drawdown exceeds the
    fatal threshold.

    Parameters
    ----------
    max_daily_drawdown_pct:
        Maximum allowed drawdown within a single trading day (e.g. 0.10 = 10%).
    kill_switch_drawdown_pct:
        Overall drawdown that triggers a full trading halt (e.g. 0.50 = 50%).
    cool_down_hours:
        Hours to wait before resuming after a daily drawdown pause.
    initial_equity:
        Starting portfolio equity.  If not provided, the first call to
        :meth:`update` initialises it.
    """

    def __init__(
        self,
        *,
        max_daily_drawdown_pct: float = 0.10,
        kill_switch_drawdown_pct: float = 0.50,
        cool_down_hours: int = 4,
        initial_equity: float | None = None,
    ) -> None:
        self._max_daily_drawdown_pct = max_daily_drawdown_pct
        self._kill_switch_drawdown_pct = kill_switch_drawdown_pct
        self._cool_down_hours = cool_down_hours

        self._peak_equity: float = initial_equity or 0.0
        self._current_equity: float = initial_equity or 0.0
        self._daily_start_equity: float = initial_equity or 0.0
        self._current_day: str = datetime.utcnow().strftime("%Y-%m-%d")

        self._paused: bool = False
        self._pause_reason: str | None = None
        self._paused_at: datetime | None = None
        self._resume_at: datetime | None = None
        self._kill_switch_triggered: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, current_value: float, *, now: datetime | None = None) -> DrawdownSnapshot:
        """Update equity and recalculate drawdown metrics.

        Call this after every trade close or on a periodic timer.

        Parameters
        ----------
        current_value:
            Current total portfolio equity (balance + unrealised P&L).
        now:
            Optional timestamp override for testing.

        Returns
        -------
        DrawdownSnapshot
            The current drawdown state after the update.
        """
        now = now or datetime.utcnow()
        today = now.strftime("%Y-%m-%d")

        # Reset daily tracking on new day
        if today != self._current_day:
            self._daily_start_equity = self._current_equity
            self._current_day = today
            # Auto-resume on new day if paused from daily drawdown (not kill switch)
            if self._paused and not self._kill_switch_triggered:
                self._unpause()

        # Initialise peak if this is the first update
        if self._peak_equity <= 0:
            self._peak_equity = current_value
            self._daily_start_equity = current_value

        self._current_equity = current_value

        # Update peak
        if current_value > self._peak_equity:
            self._peak_equity = current_value

        # Check auto-resume by time
        if (
            self._paused
            and not self._kill_switch_triggered
            and self._resume_at is not None
            and now >= self._resume_at
        ):
            self._unpause()

        # Check kill switch (overall drawdown from peak)
        overall_dd = self.get_drawdown_pct()
        if overall_dd >= self._kill_switch_drawdown_pct:
            self._kill_switch_triggered = True
            self._pause(
                f"KILL SWITCH: overall drawdown {overall_dd:.2%} "
                f"exceeds {self._kill_switch_drawdown_pct:.2%}.",
                now=now,
                indefinite=True,
            )

        # Check daily drawdown
        daily_dd = self.get_daily_drawdown_pct()
        if (
            not self._kill_switch_triggered
            and not self._paused
            and daily_dd >= self._max_daily_drawdown_pct
        ):
            self._pause(
                f"Daily drawdown {daily_dd:.2%} hit limit "
                f"{self._max_daily_drawdown_pct:.2%}.",
                now=now,
            )

        return self.snapshot(now=now)

    def is_paused(self) -> bool:
        """Return ``True`` if trading is currently paused."""
        return self._paused

    def should_trigger_kill_switch(self) -> bool:
        """Return ``True`` if the kill switch has been triggered."""
        return self._kill_switch_triggered

    def get_drawdown_pct(self) -> float:
        """Return overall drawdown from peak as a positive fraction."""
        if self._peak_equity <= 0:
            return 0.0
        dd = (self._peak_equity - self._current_equity) / self._peak_equity
        return max(dd, 0.0)

    def get_daily_drawdown_pct(self) -> float:
        """Return today's drawdown from the day-start equity."""
        if self._daily_start_equity <= 0:
            return 0.0
        dd = (self._daily_start_equity - self._current_equity) / self._daily_start_equity
        return max(dd, 0.0)

    def snapshot(self, *, now: datetime | None = None) -> DrawdownSnapshot:
        """Return the current drawdown state as a snapshot."""
        return DrawdownSnapshot(
            peak_equity=self._peak_equity,
            current_equity=self._current_equity,
            drawdown_pct=self.get_drawdown_pct(),
            daily_start_equity=self._daily_start_equity,
            daily_drawdown_pct=self.get_daily_drawdown_pct(),
            is_paused=self._paused,
            pause_reason=self._pause_reason,
            paused_at=self._paused_at,
            resume_at=self._resume_at,
            updated_at=now or datetime.utcnow(),
        )

    def reset_daily(self) -> None:
        """Manually reset daily tracking (e.g. at session boundary)."""
        self._daily_start_equity = self._current_equity
        self._current_day = datetime.utcnow().strftime("%Y-%m-%d")
        if self._paused and not self._kill_switch_triggered:
            self._unpause()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _pause(
        self,
        reason: str,
        *,
        now: datetime | None = None,
        indefinite: bool = False,
    ) -> None:
        now = now or datetime.utcnow()
        self._paused = True
        self._pause_reason = reason
        self._paused_at = now
        self._resume_at = None if indefinite else now + timedelta(hours=self._cool_down_hours)
        logger.warning("Trading PAUSED: %s (resume at %s)", reason, self._resume_at)

    def _unpause(self) -> None:
        logger.info("Trading RESUMED (was paused: %s)", self._pause_reason)
        self._paused = False
        self._pause_reason = None
        self._paused_at = None
        self._resume_at = None

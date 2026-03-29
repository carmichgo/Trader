"""Dynamic scan interval controller.

Adjusts how frequently the system scans for new opportunities based on
market activity, current pace status, and recent trade quality.
"""

from __future__ import annotations

import logging
from datetime import datetime

from pydantic import BaseModel, Field

from packages.core.planning.pace_monitor import PaceStatus

logger = logging.getLogger(__name__)


class CadenceSnapshot(BaseModel):
    """Current cadence state."""

    current_interval_seconds: float = 1800.0
    min_interval_seconds: float = 300.0
    max_interval_seconds: float = 3600.0
    pace_status: PaceStatus = PaceStatus.ON_TRACK
    market_activity: str = "normal"
    recent_trade_quality: float = 0.5
    last_adjusted_at: datetime = Field(default_factory=datetime.utcnow)


class CadenceController:
    """Dynamically adjusts the scan interval based on conditions.

    When behind pace, scan more frequently (but never below min).
    When well ahead, scan less frequently (conserve inference budget).
    High market activity increases scan frequency.
    Poor recent trade quality slows scanning to avoid overtrading on noise.

    Parameters
    ----------
    default_interval_seconds:
        Default scan interval in seconds (e.g. 1800 = 30 minutes).
    min_interval_seconds:
        Absolute minimum scan interval per market.
    max_interval_seconds:
        Absolute maximum scan interval per market.
    """

    def __init__(
        self,
        *,
        default_interval_seconds: float = 1800.0,
        min_interval_seconds: float = 300.0,
        max_interval_seconds: float = 3600.0,
    ) -> None:
        self._default_interval = default_interval_seconds
        self._min_interval = min_interval_seconds
        self._max_interval = max_interval_seconds

        self._current_interval = default_interval_seconds
        self._pace_status = PaceStatus.ON_TRACK
        self._market_activity: str = "normal"
        self._recent_trade_quality: float = 0.5
        self._last_adjusted_at = datetime.utcnow()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_current_interval(self) -> float:
        """Return the current scan interval in seconds."""
        return self._current_interval

    def adjust(
        self,
        pace_status: PaceStatus,
        market_activity: str = "normal",
        *,
        recent_trade_quality: float | None = None,
    ) -> float:
        """Recalculate the scan interval based on current conditions.

        Parameters
        ----------
        pace_status:
            Current pace relative to the daily target.
        market_activity:
            One of ``"low"``, ``"normal"``, ``"high"``, ``"extreme"``.
        recent_trade_quality:
            Float in [0, 1] representing the quality of recent trades.
            Lower values mean more bad trades; causes slower scanning.

        Returns
        -------
        float
            The new scan interval in seconds.
        """
        self._pace_status = pace_status
        self._market_activity = market_activity
        if recent_trade_quality is not None:
            self._recent_trade_quality = max(0.0, min(1.0, recent_trade_quality))

        # Start from default
        interval = self._default_interval

        # Pace adjustment
        pace_multiplier = self._pace_multiplier(pace_status)
        interval *= pace_multiplier

        # Market activity adjustment
        activity_multiplier = self._activity_multiplier(market_activity)
        interval *= activity_multiplier

        # Trade quality adjustment: poor quality -> scan slower
        if self._recent_trade_quality < 0.3:
            interval *= 1.5  # Slow down when trades are low quality
        elif self._recent_trade_quality > 0.7:
            interval *= 0.85  # Speed up slightly when quality is high

        # Clamp to bounds
        interval = max(self._min_interval, min(self._max_interval, interval))
        self._current_interval = interval
        self._last_adjusted_at = datetime.utcnow()

        logger.debug(
            "Cadence adjusted: interval=%.0fs (pace=%s, activity=%s, quality=%.2f)",
            interval,
            pace_status.value,
            market_activity,
            self._recent_trade_quality,
        )

        return interval

    def snapshot(self) -> CadenceSnapshot:
        """Return current cadence state."""
        return CadenceSnapshot(
            current_interval_seconds=self._current_interval,
            min_interval_seconds=self._min_interval,
            max_interval_seconds=self._max_interval,
            pace_status=self._pace_status,
            market_activity=self._market_activity,
            recent_trade_quality=self._recent_trade_quality,
            last_adjusted_at=self._last_adjusted_at,
        )

    # ------------------------------------------------------------------
    # Internal multipliers
    # ------------------------------------------------------------------

    @staticmethod
    def _pace_multiplier(pace_status: PaceStatus) -> float:
        """Pace -> interval multiplier.  Lower = scan more often."""
        return {
            PaceStatus.WELL_AHEAD: 1.5,    # Conserve budget, scan less
            PaceStatus.ON_TRACK: 1.0,       # Default pace
            PaceStatus.BEHIND: 0.7,         # Scan more frequently
            PaceStatus.FAR_BEHIND: 0.5,     # Scan much more frequently
        }.get(pace_status, 1.0)

    @staticmethod
    def _activity_multiplier(market_activity: str) -> float:
        """Market activity -> interval multiplier.  Lower = scan more often."""
        return {
            "low": 1.3,       # Quiet market, no rush
            "normal": 1.0,
            "high": 0.7,      # Active market, scan more
            "extreme": 0.5,   # Very active, scan aggressively
        }.get(market_activity, 1.0)

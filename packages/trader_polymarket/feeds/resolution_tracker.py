"""Polymarket event resolution tracking.

Monitors prediction markets approaching resolution deadlines and
tracks resolution outcomes for P&L calculation and strategy
performance evaluation.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import structlog

from packages.core.data.base_feed import BaseDataFeed
from packages.core.models import Direction, Market, NormalizedSignal

logger = structlog.get_logger(__name__)


class ResolutionStatus:
    """Resolution state for a prediction market."""

    ACTIVE = "active"
    APPROACHING = "approaching"  # Within resolution window
    RESOLVING = "resolving"      # Resolution in progress
    RESOLVED = "resolved"        # Final outcome known


class ResolutionTracker(BaseDataFeed):
    """Tracks prediction market resolution timelines and outcomes.

    Monitors markets approaching their resolution dates, detects early
    resolution signals, and records final outcomes for performance
    tracking.

    Parameters
    ----------
    clob_feed:
        Reference to the CLOB feed for market metadata access.
    approaching_threshold_hours:
        Hours before resolution when a market is flagged as
        "approaching".
    poll_interval_seconds:
        Polling frequency for resolution status checks.
    """

    def __init__(
        self,
        clob_feed: Any = None,
        approaching_threshold_hours: int = 48,
        poll_interval_seconds: int = 60,
    ) -> None:
        super().__init__()
        self.clob_feed = clob_feed
        self.approaching_threshold_hours = approaching_threshold_hours
        self.poll_interval_seconds = poll_interval_seconds

        # condition_id -> resolution info
        self._resolution_status: dict[str, dict[str, Any]] = {}
        self._resolved_markets: dict[str, dict[str, Any]] = {}
        self._approaching_markets: list[str] = []
        self._poll_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Start resolution tracking."""
        self._connected = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info(
            "resolution_tracker_connected",
            threshold_hours=self.approaching_threshold_hours,
            poll_interval=self.poll_interval_seconds,
        )

    async def disconnect(self) -> None:
        """Stop tracking."""
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        self._connected = False
        logger.info("resolution_tracker_disconnected")

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        """Periodically check market resolution statuses."""
        while self._connected:
            try:
                await self._update_resolution_statuses()
                self._last_update_time = datetime.now(timezone.utc)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("resolution_poll_error")

            await asyncio.sleep(self.poll_interval_seconds)

    async def _update_resolution_statuses(self) -> None:
        """Check all tracked markets for resolution status changes."""
        if self.clob_feed is None:
            return

        now = datetime.now(timezone.utc)
        threshold = timedelta(hours=self.approaching_threshold_hours)
        self._approaching_markets = []

        for condition_id in self.clob_feed.tracked_markets:
            market_info = self.clob_feed.get_market_info(condition_id)
            if not market_info:
                continue

            end_date_str = market_info.get("end_date_iso")
            if not end_date_str:
                continue

            try:
                end_date = datetime.fromisoformat(
                    end_date_str.replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                continue

            time_until_resolution = end_date - now

            # Determine status
            if market_info.get("closed"):
                status = ResolutionStatus.RESOLVED
            elif time_until_resolution <= timedelta(0):
                status = ResolutionStatus.RESOLVING
            elif time_until_resolution <= threshold:
                status = ResolutionStatus.APPROACHING
                self._approaching_markets.append(condition_id)
            else:
                status = ResolutionStatus.ACTIVE

            prev_status = self._resolution_status.get(condition_id, {}).get("status")

            self._resolution_status[condition_id] = {
                "status": status,
                "end_date": end_date.isoformat(),
                "hours_until_resolution": max(
                    time_until_resolution.total_seconds() / 3600, 0
                ),
                "question": market_info.get("question", ""),
                "last_checked": now.isoformat(),
            }

            # Log status transitions
            if prev_status and prev_status != status:
                logger.info(
                    "resolution_status_changed",
                    condition_id=condition_id,
                    old_status=prev_status,
                    new_status=status,
                    question=market_info.get("question", "")[:100],
                )

                if status == ResolutionStatus.RESOLVED:
                    self._resolved_markets[condition_id] = {
                        "resolved_at": now.isoformat(),
                        "question": market_info.get("question", ""),
                    }

    # ------------------------------------------------------------------
    # Data retrieval -- BaseDataFeed interface
    # ------------------------------------------------------------------

    async def get_latest(self) -> list[NormalizedSignal]:
        """Return signals for markets approaching resolution.

        Markets nearing resolution often see increased volatility
        and price convergence toward the expected outcome.  This
        generates signals for potential trading opportunities.
        """
        signals: list[NormalizedSignal] = []

        for condition_id in self._approaching_markets:
            res_info = self._resolution_status.get(condition_id, {})
            hours_remaining = res_info.get("hours_until_resolution", 999)

            # Higher urgency = higher confidence in mean-reversion
            if hours_remaining < 4:
                confidence = 0.7
            elif hours_remaining < 12:
                confidence = 0.5
            elif hours_remaining < 24:
                confidence = 0.3
            else:
                confidence = 0.2

            signals.append(
                NormalizedSignal(
                    market=Market.POLYMARKET,
                    symbol=condition_id,
                    direction=Direction.BUY,  # Placeholder; screener decides
                    normalized_confidence=round(confidence, 4),
                    expected_duration_hours=hours_remaining,
                    metadata={
                        "source": "resolution_tracker",
                        "status": res_info.get("status"),
                        "hours_remaining": round(hours_remaining, 1),
                        "question": res_info.get("question", "")[:200],
                    },
                )
            )

        return signals

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    def get_status(self, condition_id: str) -> dict[str, Any]:
        """Return the resolution status for a specific market."""
        return self._resolution_status.get(condition_id, {})

    def get_approaching_markets(self) -> list[str]:
        """Return condition IDs of markets approaching resolution."""
        return list(self._approaching_markets)

    def get_resolved_markets(self) -> dict[str, dict[str, Any]]:
        """Return all markets that have resolved."""
        return dict(self._resolved_markets)

    def is_approaching_resolution(self, condition_id: str) -> bool:
        """Check if a market is within the resolution threshold."""
        return condition_id in self._approaching_markets

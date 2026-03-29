"""Data normalization: convert raw feed data into NormalizedSignal instances."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from packages.core.models import Direction, Market, NormalizedSignal, TradeSignal

logger = logging.getLogger(__name__)


class DataNormalizer:
    """Standardises heterogeneous data-source payloads into ``NormalizedSignal``.

    Every feed produces data in its own format.  The normalizer maps each
    payload to the common ``NormalizedSignal`` schema, computes a signal
    strength score (0-1) and a freshness indicator so downstream consumers
    can compare signals across markets on an equal footing.
    """

    # Maximum age (in seconds) before a signal's freshness drops to zero.
    DEFAULT_FRESHNESS_HORIZON_SECS: float = 3600.0  # 1 hour

    def __init__(
        self,
        *,
        freshness_horizon_secs: float = DEFAULT_FRESHNESS_HORIZON_SECS,
    ) -> None:
        """
        Parameters
        ----------
        freshness_horizon_secs:
            Signals older than this many seconds receive a freshness of 0.0.
        """
        self._freshness_horizon = max(freshness_horizon_secs, 1.0)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def normalize(
        self,
        raw_data: dict[str, Any],
        source: str,
        market: Market,
    ) -> NormalizedSignal:
        """Convert *raw_data* from *source* into a ``NormalizedSignal``.

        Parameters
        ----------
        raw_data:
            Arbitrary dict coming from a data feed.  Expected keys vary by
            source but the normalizer handles missing keys gracefully with
            sensible defaults.
        source:
            Human-readable name of the feed (e.g. ``"polymarket_ws"``,
            ``"binance_rest"``).
        market:
            The market enum value for this data.

        Returns
        -------
        NormalizedSignal
            A fully populated, schema-compliant signal ready for downstream
            consumption.
        """
        now = datetime.now(timezone.utc)

        # ---- Extract core fields ------------------------------------------
        symbol: str = str(raw_data.get("symbol", raw_data.get("asset", "UNKNOWN")))
        direction = self._extract_direction(raw_data)
        confidence = self._clamp(float(raw_data.get("confidence", 0.0)))
        expected_return: Optional[float] = raw_data.get("expected_return")
        expected_duration: Optional[float] = raw_data.get("expected_duration_hours")

        # ---- Signal strength -----------------------------------------------
        strength = self._compute_signal_strength(
            confidence=confidence,
            expected_return=expected_return,
            raw_data=raw_data,
        )

        # ---- Freshness -----------------------------------------------------
        created_at = self._parse_timestamp(raw_data.get("timestamp")) or now
        freshness = self._compute_freshness(created_at, now)

        # ---- Build source TradeSignal if enough info -----------------------
        source_signals: list[TradeSignal] = []
        if "signal_id" in raw_data or "reasoning" in raw_data:
            source_signals.append(
                TradeSignal(
                    id=raw_data.get("signal_id"),
                    source=source,
                    market=market,
                    symbol=symbol,
                    direction=direction,
                    confidence=confidence,
                    strength=strength,
                    decision_type=raw_data.get("decision_type", "screener"),
                    reasoning=raw_data.get("reasoning"),
                    suggested_entry=raw_data.get("entry_price"),
                    suggested_stop_loss=raw_data.get("stop_loss"),
                    suggested_take_profit=raw_data.get("take_profit"),
                    created_at=created_at,
                )
            )

        signal = NormalizedSignal(
            id=f"ns-{uuid.uuid4().hex[:12]}",
            original_signal_id=raw_data.get("signal_id"),
            market=market,
            symbol=symbol,
            direction=direction,
            normalized_confidence=confidence,
            expected_return=expected_return,
            expected_duration_hours=expected_duration,
            risk_adjusted_score=raw_data.get("risk_adjusted_score"),
            sharpe_estimate=raw_data.get("sharpe_estimate"),
            max_drawdown_estimate=raw_data.get("max_drawdown_estimate"),
            correlation_to_portfolio=raw_data.get("correlation_to_portfolio"),
            inference_cost=float(raw_data.get("inference_cost", 0.0)),
            source_signals=source_signals,
            created_at=created_at,
            metadata={
                "source": source,
                "signal_strength": strength,
                "freshness": freshness,
                "raw_keys": list(raw_data.keys()),
            },
        )

        logger.debug(
            "Normalised signal  id=%s source=%s market=%s symbol=%s "
            "confidence=%.3f strength=%.3f freshness=%.3f",
            signal.id,
            source,
            market.value,
            symbol,
            confidence,
            strength,
            freshness,
        )
        return signal

    # ------------------------------------------------------------------
    # Signal strength & freshness
    # ------------------------------------------------------------------

    def _compute_signal_strength(
        self,
        *,
        confidence: float,
        expected_return: Optional[float],
        raw_data: dict[str, Any],
    ) -> float:
        """Derive a 0-1 strength score from available signal attributes.

        The score blends confidence with any additional quality indicators
        present in *raw_data* (volume, liquidity, multiple-source agreement).
        """
        components: list[float] = [confidence]

        # Reward positive expected return (cap contribution at 0.5).
        if expected_return is not None and expected_return > 0:
            components.append(min(expected_return / 0.10, 1.0) * 0.5)

        # Volume / liquidity bonus if present.
        volume = raw_data.get("volume_24h")
        if volume is not None and volume > 0:
            # Logarithmic scaling: $100k volume -> ~0.3, $1M -> ~0.6
            import math
            vol_score = min(math.log10(max(volume, 1)) / 7.0, 1.0)
            components.append(vol_score * 0.3)

        # Multi-source agreement bonus.
        source_count = raw_data.get("source_count", 1)
        if source_count > 1:
            components.append(min(source_count / 5.0, 1.0) * 0.4)

        # Weighted average (first component – confidence – has double weight).
        if len(components) == 1:
            return self._clamp(components[0])

        weighted = components[0] * 2.0 + sum(components[1:])
        total_weight = 2.0 + len(components) - 1
        return self._clamp(weighted / total_weight)

    def _compute_freshness(self, created_at: datetime, now: datetime) -> float:
        """Return a 0-1 freshness score.  1 = brand-new, 0 = stale."""
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        age_secs = max((now - created_at).total_seconds(), 0.0)
        return max(1.0 - age_secs / self._freshness_horizon, 0.0)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_direction(raw_data: dict[str, Any]) -> Direction:
        """Best-effort extraction of direction from raw data."""
        raw = raw_data.get("direction") or raw_data.get("side") or "buy"
        raw_lower = str(raw).lower().strip()
        for member in Direction:
            if member.value == raw_lower:
                return member
        return Direction.BUY

    @staticmethod
    def _parse_timestamp(value: Any) -> Optional[datetime]:
        """Try to coerce *value* into a timezone-aware datetime."""
        if value is None:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        if isinstance(value, str):
            try:
                dt = datetime.fromisoformat(value)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                return None
        return None

    @staticmethod
    def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
        return max(lo, min(hi, value))

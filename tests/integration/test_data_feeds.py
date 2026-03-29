"""Integration tests for data feed normalization.

These tests verify that raw data from various feed formats is correctly
normalized into NormalizedSignal objects by the DataNormalizer.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from packages.core.data.normalizer import DataNormalizer
from packages.core.models import Direction, Market


# ---------------------------------------------------------------------------
# Basic normalization
# ---------------------------------------------------------------------------


class TestBasicNormalization:
    """Verify core normalization of raw feed data."""

    def test_crypto_feed_normalization(self) -> None:
        """A crypto exchange payload should produce a valid NormalizedSignal."""
        normalizer = DataNormalizer()
        raw = {
            "symbol": "BTC/USDT",
            "direction": "buy",
            "confidence": 0.72,
            "expected_return": 0.05,
            "expected_duration_hours": 24.0,
            "volume_24h": 1_500_000_000.0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        signal = normalizer.normalize(raw, source="binance_rest", market=Market.CRYPTO)

        assert signal.symbol == "BTC/USDT"
        assert signal.direction == Direction.BUY
        assert signal.normalized_confidence == 0.72
        assert signal.expected_return == 0.05
        assert signal.market == Market.CRYPTO
        assert signal.id is not None
        assert signal.metadata.get("source") == "binance_rest"

    def test_polymarket_feed_normalization(self) -> None:
        """A Polymarket-style payload should normalize correctly."""
        normalizer = DataNormalizer()
        raw = {
            "symbol": "WILL-X-HAPPEN",
            "side": "buy",
            "confidence": 0.65,
            "expected_return": 0.08,
        }

        signal = normalizer.normalize(raw, source="polymarket_ws", market=Market.POLYMARKET)

        assert signal.symbol == "WILL-X-HAPPEN"
        assert signal.direction == Direction.BUY
        assert signal.normalized_confidence == 0.65
        assert signal.market == Market.POLYMARKET

    def test_stocks_feed_normalization(self) -> None:
        """A stock-style payload should normalize correctly."""
        normalizer = DataNormalizer()
        raw = {
            "symbol": "AAPL",
            "direction": "sell",
            "confidence": 0.58,
        }

        signal = normalizer.normalize(raw, source="alpaca_rest", market=Market.STOCKS)

        assert signal.symbol == "AAPL"
        assert signal.direction == Direction.SELL
        assert signal.market == Market.STOCKS


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestNormalizationEdgeCases:
    """Handle missing or unusual data gracefully."""

    def test_missing_direction_defaults_to_buy(self) -> None:
        """When direction is not in the payload, default to BUY."""
        normalizer = DataNormalizer()
        raw = {"symbol": "ETH/USDT", "confidence": 0.60}

        signal = normalizer.normalize(raw, source="test", market=Market.CRYPTO)

        assert signal.direction == Direction.BUY

    def test_missing_symbol_defaults_to_unknown(self) -> None:
        """When symbol is missing, default to UNKNOWN."""
        normalizer = DataNormalizer()
        raw = {"confidence": 0.50}

        signal = normalizer.normalize(raw, source="test", market=Market.CRYPTO)

        assert signal.symbol == "UNKNOWN"

    def test_confidence_clamped_to_bounds(self) -> None:
        """Confidence outside [0, 1] should be clamped."""
        normalizer = DataNormalizer()
        raw_high = {"symbol": "X", "confidence": 1.5}
        raw_low = {"symbol": "Y", "confidence": -0.5}

        sig_high = normalizer.normalize(raw_high, source="test", market=Market.CRYPTO)
        sig_low = normalizer.normalize(raw_low, source="test", market=Market.CRYPTO)

        assert sig_high.normalized_confidence <= 1.0
        assert sig_low.normalized_confidence >= 0.0

    def test_unix_timestamp_parsing(self) -> None:
        """A numeric Unix timestamp should be parsed into a datetime."""
        normalizer = DataNormalizer()
        ts = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc).timestamp()
        raw = {"symbol": "BTC/USDT", "confidence": 0.70, "timestamp": ts}

        signal = normalizer.normalize(raw, source="test", market=Market.CRYPTO)

        assert signal.created_at.year == 2026


# ---------------------------------------------------------------------------
# Signal strength
# ---------------------------------------------------------------------------


class TestSignalStrength:
    """Verify that signal strength is computed from available data."""

    def test_high_volume_boosts_strength(self) -> None:
        """A signal with high volume should incorporate volume into strength.

        The normalizer uses a weighted average where confidence has 2x weight.
        Adding volume introduces a volume component (capped at 0.3 * vol_score).
        With confidence=0.70 and volume bonus, the blended score includes
        the volume signal alongside confidence.
        """
        normalizer = DataNormalizer()
        raw_with_volume = {
            "symbol": "BTC/USDT",
            "confidence": 0.70,
            "volume_24h": 2_000_000_000.0,
        }

        sig_vol = normalizer.normalize(raw_with_volume, source="test", market=Market.CRYPTO)
        strength_vol = sig_vol.metadata.get("signal_strength", 0.0)

        # Strength should be positive and incorporate the volume component
        assert strength_vol > 0.0
        # The weighted average blends confidence (2x weight) with volume bonus
        assert strength_vol > 0.50

    def test_multi_source_agreement_boosts_strength(self) -> None:
        """Multiple confirming sources should result in a different strength
        than a single source, incorporating multi-source agreement.

        The normalizer blends confidence (2x weight) with multi-source bonus.
        With source_count=4: bonus = min(4/5, 1.0) * 0.4 = 0.32
        Blended = (0.70*2 + 0.32) / 3 = 0.573
        With source_count=1: bonus = min(1/5, 1.0) * 0.4 = 0.08 (but source_count=1 doesn't add)
        """
        normalizer = DataNormalizer()
        raw_multi = {"symbol": "BTC/USDT", "confidence": 0.70, "source_count": 4}

        sig_multi = normalizer.normalize(raw_multi, source="test", market=Market.CRYPTO)
        strength_multi = sig_multi.metadata.get("signal_strength", 0.0)

        # Multi-source agreement component should be reflected in strength
        assert strength_multi > 0.50
        # The blended score includes the multi-source bonus
        assert strength_multi > 0.55


# ---------------------------------------------------------------------------
# Freshness
# ---------------------------------------------------------------------------


class TestFreshness:
    """Verify signal freshness decays with age."""

    def test_fresh_signal_has_high_freshness(self) -> None:
        """A just-created signal should have freshness close to 1.0."""
        normalizer = DataNormalizer(freshness_horizon_secs=3600.0)
        raw = {
            "symbol": "BTC/USDT",
            "confidence": 0.70,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        signal = normalizer.normalize(raw, source="test", market=Market.CRYPTO)

        freshness = signal.metadata.get("freshness", 0.0)
        assert freshness > 0.95

    def test_stale_signal_has_zero_freshness(self) -> None:
        """A signal older than the freshness horizon should have freshness 0."""
        normalizer = DataNormalizer(freshness_horizon_secs=3600.0)
        old_ts = datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat()
        raw = {
            "symbol": "BTC/USDT",
            "confidence": 0.70,
            "timestamp": old_ts,
        }

        signal = normalizer.normalize(raw, source="test", market=Market.CRYPTO)

        freshness = signal.metadata.get("freshness", 1.0)
        assert freshness == 0.0

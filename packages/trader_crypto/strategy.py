"""Crypto market data preprocessing for AI consumption.

Transforms raw exchange data, on-chain metrics, and sentiment scores
into structured context objects that the Screener (Sonnet) and Analyst
(Opus) can efficiently process.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from packages.core.models import (
    Market,
    MarketSnapshot,
    Opportunity,
    PortfolioState,
    TraderConfig,
)

logger = structlog.get_logger(__name__)


class CryptoStrategy:
    """Prepares crypto market data for AI analysis.

    Combines exchange data (OHLCV, order book, funding rates),
    on-chain metrics, and sentiment indicators into a unified
    context that can be consumed by the screener and analyst.

    Parameters
    ----------
    config:
        Trader configuration for market-specific parameters.
    """

    def __init__(self, config: TraderConfig) -> None:
        self.config = config

    # ------------------------------------------------------------------
    # Snapshot building
    # ------------------------------------------------------------------

    def build_snapshot(
        self,
        ticker_data: dict[str, Any],
        ohlcv_data: list[list] | None = None,
        orderbook_data: dict[str, Any] | None = None,
        funding_rate: float | None = None,
        onchain_data: dict[str, Any] | None = None,
        sentiment_data: dict[str, Any] | None = None,
    ) -> MarketSnapshot:
        """Build a :class:`MarketSnapshot` from multiple data sources.

        Parameters
        ----------
        ticker_data:
            Ticker dict from CCXT (keys: last, bid, ask, quoteVolume, etc.).
        ohlcv_data:
            List of OHLCV candles ``[ts, o, h, l, c, v]``.
        orderbook_data:
            Order book dict with ``bids`` and ``asks``.
        funding_rate:
            Current funding rate for perpetual futures.
        onchain_data:
            On-chain metrics (exchange flows, whale alerts).
        sentiment_data:
            Sentiment scores (Fear & Greed, social).
        """
        symbol = ticker_data.get("symbol", "UNKNOWN/USDT")
        price = ticker_data.get("last", 0.0)

        # Build metadata from supplementary sources
        metadata: dict[str, Any] = {}

        if ohlcv_data:
            metadata["ohlcv_summary"] = self._summarize_ohlcv(ohlcv_data)

        if orderbook_data:
            metadata["orderbook_summary"] = self._summarize_orderbook(orderbook_data)

        if onchain_data:
            metadata["onchain"] = onchain_data

        if sentiment_data:
            metadata["sentiment"] = sentiment_data

        # Calculate spread
        bid = ticker_data.get("bid")
        ask = ticker_data.get("ask")
        spread = (ask - bid) if (bid and ask) else None

        return MarketSnapshot(
            market=Market.CRYPTO,
            symbol=symbol,
            price=price,
            bid=bid,
            ask=ask,
            spread=spread,
            volume_24h=ticker_data.get("quoteVolume"),
            change_24h_pct=ticker_data.get("percentage"),
            high_24h=ticker_data.get("high"),
            low_24h=ticker_data.get("low"),
            funding_rate=funding_rate,
            timestamp=datetime.now(timezone.utc),
            source="crypto_strategy",
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Analyst context building
    # ------------------------------------------------------------------

    def build_analysis_context(
        self,
        opportunity: Opportunity,
        snapshots: list[MarketSnapshot],
        portfolio_state: PortfolioState,
        recent_trades: list[dict[str, Any]],
        ohlcv_data: dict[str, list[list]] | None = None,
        orderbook_data: dict[str, dict[str, Any]] | None = None,
        onchain_data: dict[str, dict[str, Any]] | None = None,
        sentiment_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Assemble the full context dictionary for Opus analyst evaluation.

        Returns a comprehensive context with all relevant data the analyst
        needs to make an informed trade decision.

        Parameters
        ----------
        opportunity:
            The screener-identified opportunity to analyze.
        snapshots:
            Current market snapshots for all tracked symbols.
        portfolio_state:
            Current portfolio state including balances, open positions.
        recent_trades:
            List of recent trade results with outcomes.
        ohlcv_data:
            OHLCV candle data keyed by symbol.
        orderbook_data:
            Order book depth keyed by symbol.
        onchain_data:
            On-chain metrics keyed by symbol.
        sentiment_data:
            Market sentiment indicators.
        """
        symbol = opportunity.symbol

        # Find the matching snapshot for this opportunity
        target_snapshot = next(
            (s for s in snapshots if s.symbol == symbol),
            None,
        )

        # Build technical analysis summary from OHLCV
        technical_analysis = {}
        if ohlcv_data and symbol in ohlcv_data:
            technical_analysis = self._compute_technical_indicators(
                ohlcv_data[symbol]
            )

        # Build order book analysis
        orderbook_analysis = {}
        if orderbook_data and symbol in orderbook_data:
            orderbook_analysis = self._summarize_orderbook(orderbook_data[symbol])

        # Cross-asset context: BTC and ETH as market barometers
        market_context = {}
        for snapshot in snapshots:
            if snapshot.symbol in ("BTC/USDT", "ETH/USDT"):
                market_context[snapshot.symbol] = {
                    "price": snapshot.price,
                    "change_24h": snapshot.change_24h_pct,
                    "volume_24h": snapshot.volume_24h,
                    "funding_rate": snapshot.funding_rate,
                }

        return {
            "opportunity": {
                "symbol": opportunity.symbol,
                "title": opportunity.title,
                "description": opportunity.description,
                "current_price": opportunity.current_price,
                "estimated_edge": opportunity.estimated_edge,
                "confidence": opportunity.confidence,
                "volume_24h": opportunity.volume_24h,
                "volatility": opportunity.volatility,
                "category": opportunity.category,
            },
            "current_snapshot": target_snapshot.model_dump() if target_snapshot else None,
            "technical_analysis": technical_analysis,
            "orderbook_analysis": orderbook_analysis,
            "onchain_data": onchain_data.get(symbol, {}) if onchain_data else {},
            "sentiment": sentiment_data or {},
            "market_context": market_context,
            "portfolio_state": portfolio_state.model_dump(),
            "recent_trades": recent_trades[-10:],  # Last 10 trades for context
            "risk_limits": {
                "max_position_pct": self.config.safety_rails.max_single_trade_pct,
                "max_leverage": self.config.safety_rails.max_leverage,
                "max_stop_loss_pct": self.config.safety_rails.max_stop_loss_pct,
                "max_concurrent_positions": self.config.safety_rails.max_concurrent_positions,
            },
            "available_balance": portfolio_state.available_balance,
            "max_position_pct": self.config.safety_rails.max_single_trade_pct,
        }

    # ------------------------------------------------------------------
    # Screener compression
    # ------------------------------------------------------------------

    def compress_for_screener(
        self,
        snapshots: list[MarketSnapshot],
    ) -> list[dict[str, Any]]:
        """Compress market snapshots into a token-efficient format for the screener.

        Strips out verbose metadata and keeps only the essential fields
        the Sonnet screener needs to score opportunities.
        """
        compressed: list[dict[str, Any]] = []

        for s in snapshots:
            entry: dict[str, Any] = {
                "sym": s.symbol,
                "px": round(s.price, 6),
                "chg24": round(s.change_24h_pct, 2) if s.change_24h_pct else None,
                "vol": round(s.volume_24h, 0) if s.volume_24h else None,
                "spread": round(s.spread, 6) if s.spread else None,
                "fr": round(s.funding_rate, 6) if s.funding_rate else None,
            }

            # Include compact technical summary if present
            ohlcv_summary = s.metadata.get("ohlcv_summary")
            if ohlcv_summary:
                entry["ta"] = {
                    "trend": ohlcv_summary.get("trend"),
                    "vol_trend": ohlcv_summary.get("volume_trend"),
                    "atr_pct": ohlcv_summary.get("atr_pct"),
                }

            # Include compact sentiment if present
            sentiment = s.metadata.get("sentiment")
            if sentiment:
                entry["sent"] = {
                    "fgi": sentiment.get("fear_greed_index"),
                    "social": sentiment.get("social_score"),
                }

            compressed.append(entry)

        return compressed

    # ------------------------------------------------------------------
    # Technical indicator helpers
    # ------------------------------------------------------------------

    def _summarize_ohlcv(self, candles: list[list]) -> dict[str, Any]:
        """Compute a compact summary from OHLCV candle data."""
        if not candles or len(candles) < 2:
            return {}

        closes = [c[4] for c in candles if len(c) > 4]
        volumes = [c[5] for c in candles if len(c) > 5]
        highs = [c[2] for c in candles if len(c) > 2]
        lows = [c[3] for c in candles if len(c) > 3]

        if not closes:
            return {}

        current = closes[-1]
        sma_20 = sum(closes[-20:]) / min(len(closes), 20) if len(closes) >= 2 else current
        sma_50 = sum(closes[-50:]) / min(len(closes), 50) if len(closes) >= 2 else current

        # ATR approximation
        true_ranges = []
        for i in range(1, len(candles)):
            h, l, prev_c = highs[i], lows[i], closes[i - 1]
            tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
            true_ranges.append(tr)
        atr = sum(true_ranges[-14:]) / min(len(true_ranges), 14) if true_ranges else 0

        # Trend detection
        trend = "neutral"
        if current > sma_20 > sma_50:
            trend = "bullish"
        elif current < sma_20 < sma_50:
            trend = "bearish"

        # Volume trend
        recent_vol = sum(volumes[-5:]) / 5 if len(volumes) >= 5 else 0
        older_vol = sum(volumes[-20:-5]) / 15 if len(volumes) >= 20 else recent_vol
        volume_trend = "rising" if recent_vol > older_vol * 1.2 else (
            "falling" if recent_vol < older_vol * 0.8 else "stable"
        )

        return {
            "sma_20": round(sma_20, 6),
            "sma_50": round(sma_50, 6),
            "atr": round(atr, 6),
            "atr_pct": round(atr / current * 100, 2) if current > 0 else 0,
            "trend": trend,
            "volume_trend": volume_trend,
            "candle_count": len(candles),
        }

    def _summarize_orderbook(self, book: dict[str, Any]) -> dict[str, Any]:
        """Compute order book summary: bid/ask depth imbalance."""
        bids = book.get("bids", [])
        asks = book.get("asks", [])

        if not bids or not asks:
            return {}

        # Sum top N levels of depth
        n = min(10, len(bids), len(asks))
        bid_depth = sum(level[1] for level in bids[:n])
        ask_depth = sum(level[1] for level in asks[:n])
        total_depth = bid_depth + ask_depth

        imbalance = (bid_depth - ask_depth) / total_depth if total_depth > 0 else 0

        return {
            "bid_depth_top10": round(bid_depth, 4),
            "ask_depth_top10": round(ask_depth, 4),
            "imbalance": round(imbalance, 4),  # >0 = more buy pressure
            "best_bid": bids[0][0] if bids else None,
            "best_ask": asks[0][0] if asks else None,
            "spread_bps": (
                round((asks[0][0] - bids[0][0]) / bids[0][0] * 10000, 2)
                if bids and asks and bids[0][0] > 0
                else None
            ),
        }

    def _compute_technical_indicators(self, candles: list[list]) -> dict[str, Any]:
        """Compute technical indicators for analyst context."""
        summary = self._summarize_ohlcv(candles)
        if not summary or not candles:
            return summary

        closes = [c[4] for c in candles if len(c) > 4]
        if len(closes) < 14:
            return summary

        # RSI (14-period)
        gains: list[float] = []
        losses: list[float] = []
        for i in range(1, len(closes)):
            delta = closes[i] - closes[i - 1]
            gains.append(max(delta, 0))
            losses.append(max(-delta, 0))

        if len(gains) >= 14:
            avg_gain = sum(gains[-14:]) / 14
            avg_loss = sum(losses[-14:]) / 14
            if avg_loss > 0:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
            else:
                rsi = 100.0
            summary["rsi_14"] = round(rsi, 2)

        # MACD approximation (12, 26, 9)
        if len(closes) >= 26:
            ema_12 = self._ema(closes, 12)
            ema_26 = self._ema(closes, 26)
            macd_line = ema_12 - ema_26
            summary["macd"] = round(macd_line, 6)
            summary["macd_signal"] = "bullish" if macd_line > 0 else "bearish"

        # Bollinger Bands (20, 2)
        if len(closes) >= 20:
            sma_20 = sum(closes[-20:]) / 20
            variance = sum((c - sma_20) ** 2 for c in closes[-20:]) / 20
            std_dev = variance ** 0.5
            summary["bb_upper"] = round(sma_20 + 2 * std_dev, 6)
            summary["bb_lower"] = round(sma_20 - 2 * std_dev, 6)
            summary["bb_width_pct"] = round(4 * std_dev / sma_20 * 100, 2) if sma_20 > 0 else 0

        return summary

    @staticmethod
    def _ema(values: list[float], period: int) -> float:
        """Compute Exponential Moving Average of the last *period* values."""
        if not values:
            return 0.0
        k = 2.0 / (period + 1)
        ema = values[0]
        for v in values[1:]:
            ema = v * k + ema * (1 - k)
        return ema

"""Stock market data preprocessing for AI consumption.

Transforms Alpaca market data, fundamental metrics, macro indicators,
and options flow into structured contexts for the Screener (Sonnet)
and Analyst (Opus).
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


class StockStrategy:
    """Prepares stock market data for AI analysis.

    Combines price data, technical indicators, fundamentals, macro
    conditions, and options flow into AI-consumable contexts.

    Parameters
    ----------
    config:
        Trader configuration for stock-specific parameters.
    """

    def __init__(self, config: TraderConfig) -> None:
        self.config = config

    # ------------------------------------------------------------------
    # Snapshot building
    # ------------------------------------------------------------------

    def build_snapshot(
        self,
        ticker_data: dict[str, Any],
        bars: list[dict[str, Any]] | None = None,
        fundamentals: dict[str, Any] | None = None,
        macro_data: dict[str, Any] | None = None,
    ) -> MarketSnapshot:
        """Build a :class:`MarketSnapshot` from multiple stock data sources.

        Parameters
        ----------
        ticker_data:
            Snapshot dict from Alpaca (price, bid, ask, volume, etc.).
        bars:
            Historical OHLCV bar data for technical analysis.
        fundamentals:
            Fundamental metrics (P/E, earnings, revenue growth).
        macro_data:
            Macro environment summary (regime, yield curve, VIX).
        """
        symbol = ticker_data.get("symbol", "UNKNOWN")
        price = ticker_data.get("latest_trade_price", 0.0)

        metadata: dict[str, Any] = {}

        if bars:
            metadata["technical_summary"] = self._summarize_bars(bars)

        if fundamentals:
            metadata["fundamentals"] = fundamentals

        if macro_data:
            metadata["macro"] = macro_data

        bid = ticker_data.get("latest_quote_bid")
        ask = ticker_data.get("latest_quote_ask")
        prev_close = ticker_data.get("prev_daily_close", price)
        change_pct = (
            (price - prev_close) / prev_close * 100
            if prev_close and prev_close > 0
            else 0.0
        )

        return MarketSnapshot(
            market=Market.STOCKS,
            symbol=symbol,
            price=price,
            bid=bid,
            ask=ask,
            spread=(ask - bid) if (bid and ask) else None,
            volume_24h=ticker_data.get("daily_bar_volume"),
            change_24h_pct=change_pct,
            high_24h=ticker_data.get("daily_bar_high"),
            low_24h=ticker_data.get("daily_bar_low"),
            timestamp=datetime.now(timezone.utc),
            source="stock_strategy",
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
        bars_data: dict[str, list[dict[str, Any]]] | None = None,
        fundamentals_data: dict[str, dict[str, Any]] | None = None,
        macro_summary: dict[str, Any] | None = None,
        options_flow: dict[str, dict[str, Any]] | None = None,
        analyst_ratings: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Assemble the full context for Opus analyst evaluation.

        Returns a comprehensive context with all relevant stock data
        the analyst needs to make an informed trade decision.
        """
        symbol = opportunity.symbol

        # Find the matching snapshot
        target_snapshot = next(
            (s for s in snapshots if s.symbol == symbol),
            None,
        )

        # Build technical analysis from bars
        technical_analysis = {}
        if bars_data and symbol in bars_data:
            technical_analysis = self._compute_technical_indicators(
                bars_data[symbol]
            )

        # Sector context: how are sector ETFs performing?
        sector_context = {}
        for snapshot in snapshots:
            if snapshot.symbol in ("SPY", "QQQ", "IWM", "DIA"):
                sector_context[snapshot.symbol] = {
                    "price": snapshot.price,
                    "change_24h": snapshot.change_24h_pct,
                    "volume": snapshot.volume_24h,
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
            "fundamentals": (
                fundamentals_data.get(symbol, {}) if fundamentals_data else {}
            ),
            "macro_environment": macro_summary or {},
            "options_flow": (
                options_flow.get(symbol, {}) if options_flow else {}
            ),
            "analyst_ratings": (
                analyst_ratings.get(symbol, {}) if analyst_ratings else {}
            ),
            "sector_context": sector_context,
            "portfolio_state": portfolio_state.model_dump(),
            "recent_trades": recent_trades[-10:],
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
        """Compress market snapshots into a token-efficient format for the screener."""
        compressed: list[dict[str, Any]] = []

        for s in snapshots:
            meta = s.metadata or {}
            entry: dict[str, Any] = {
                "sym": s.symbol,
                "px": round(s.price, 2),
                "chg24": round(s.change_24h_pct, 2) if s.change_24h_pct else None,
                "vol": round(s.volume_24h, 0) if s.volume_24h else None,
                "spread": round(s.spread, 4) if s.spread else None,
            }

            ta_summary = meta.get("technical_summary")
            if ta_summary:
                entry["ta"] = {
                    "trend": ta_summary.get("trend"),
                    "rsi": ta_summary.get("rsi_14"),
                    "vol_trend": ta_summary.get("volume_trend"),
                }

            fundamentals = meta.get("fundamentals")
            if fundamentals:
                entry["fun"] = {
                    "pe": fundamentals.get("pe_ratio"),
                    "rev_growth": fundamentals.get("revenue_growth"),
                }

            macro = meta.get("macro")
            if macro:
                entry["macro"] = macro.get("regime")

            compressed.append(entry)

        return compressed

    # ------------------------------------------------------------------
    # Technical indicator helpers
    # ------------------------------------------------------------------

    def _summarize_bars(self, bars: list[dict[str, Any]]) -> dict[str, Any]:
        """Compute a compact summary from OHLCV bar data."""
        if not bars or len(bars) < 2:
            return {}

        closes = [b["close"] for b in bars if "close" in b]
        volumes = [b.get("volume", 0) for b in bars]
        highs = [b.get("high", 0) for b in bars]
        lows = [b.get("low", 0) for b in bars]

        if not closes:
            return {}

        current = closes[-1]
        sma_20 = sum(closes[-20:]) / min(len(closes), 20) if len(closes) >= 2 else current
        sma_50 = sum(closes[-50:]) / min(len(closes), 50) if len(closes) >= 2 else current

        # ATR approximation
        true_ranges = []
        for i in range(1, len(bars)):
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
            "sma_20": round(sma_20, 2),
            "sma_50": round(sma_50, 2),
            "atr": round(atr, 2),
            "atr_pct": round(atr / current * 100, 2) if current > 0 else 0,
            "trend": trend,
            "volume_trend": volume_trend,
            "bar_count": len(bars),
        }

    def _compute_technical_indicators(
        self, bars: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Compute technical indicators for analyst context."""
        summary = self._summarize_bars(bars)
        if not summary or not bars:
            return summary

        closes = [b["close"] for b in bars if "close" in b]
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
            summary["macd"] = round(macd_line, 4)
            summary["macd_signal"] = "bullish" if macd_line > 0 else "bearish"

        # Bollinger Bands (20, 2)
        if len(closes) >= 20:
            sma_20 = sum(closes[-20:]) / 20
            variance = sum((c - sma_20) ** 2 for c in closes[-20:]) / 20
            std_dev = variance ** 0.5
            summary["bb_upper"] = round(sma_20 + 2 * std_dev, 2)
            summary["bb_lower"] = round(sma_20 - 2 * std_dev, 2)
            summary["bb_width_pct"] = (
                round(4 * std_dev / sma_20 * 100, 2) if sma_20 > 0 else 0
            )

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

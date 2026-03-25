"""Stock market data preprocessing for AI consumption.

Transforms market data, fundamentals, and macro indicators into
structured contexts for the Screener (Sonnet) and Analyst (Opus).
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

    Combines price data, technical indicators, fundamental metrics,
    and macroeconomic context into AI-consumable formats.

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
        macro_context: dict[str, Any] | None = None,
    ) -> MarketSnapshot:
        """Build a :class:`MarketSnapshot` from stock market data.

        Parameters
        ----------
        ticker_data:
            Current price/quote data.
        bars:
            Historical OHLCV bars.
        fundamentals:
            Fundamental ratios (P/E, P/S, ROE, etc.).
        macro_context:
            Macroeconomic regime and indicators.
        """
        symbol = ticker_data.get("symbol", "UNKNOWN")
        price = ticker_data.get("price", 0.0)

        metadata: dict[str, Any] = {}

        if bars:
            metadata["technical"] = self._compute_technicals(bars)

        if fundamentals:
            metadata["fundamentals"] = fundamentals

        if macro_context:
            metadata["macro"] = macro_context

        prev_close = ticker_data.get("prev_close", price)
        change_pct = (
            (price - prev_close) / prev_close * 100
            if prev_close and prev_close > 0
            else 0.0
        )

        return MarketSnapshot(
            market=Market.STOCKS,
            symbol=symbol,
            price=price,
            bid=ticker_data.get("bid"),
            ask=ticker_data.get("ask"),
            spread=(
                ticker_data["ask"] - ticker_data["bid"]
                if ticker_data.get("ask") and ticker_data.get("bid")
                else None
            ),
            volume_24h=ticker_data.get("volume"),
            change_24h_pct=change_pct,
            high_24h=ticker_data.get("high"),
            low_24h=ticker_data.get("low"),
            market_cap=ticker_data.get("market_cap"),
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
        macro_data: dict[str, Any] | None = None,
        sector_performance: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        """Assemble the full context for Opus analyst evaluation.

        Provides comprehensive stock analysis context including
        technicals, fundamentals, macro backdrop, and sector data.
        """
        symbol = opportunity.symbol

        target_snapshot = next(
            (s for s in snapshots if s.symbol == symbol),
            None,
        )

        # Technical analysis from bars
        technical_analysis = {}
        if bars_data and symbol in bars_data:
            technical_analysis = self._compute_technicals(bars_data[symbol])

        # Peer comparison
        peers = self._find_peers(symbol, snapshots)

        # Market breadth: how many stocks are up vs down
        up_count = sum(
            1 for s in snapshots if s.change_24h_pct and s.change_24h_pct > 0
        )
        down_count = sum(
            1 for s in snapshots if s.change_24h_pct and s.change_24h_pct < 0
        )
        total = up_count + down_count

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
            "macro_context": macro_data or {},
            "sector_performance": sector_performance or {},
            "market_breadth": {
                "advancing": up_count,
                "declining": down_count,
                "breadth_ratio": (
                    up_count / total if total > 0 else 0.5
                ),
            },
            "peers": peers,
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
        """Compress stock snapshots for token-efficient screener input."""
        compressed: list[dict[str, Any]] = []

        for s in snapshots:
            meta = s.metadata or {}
            entry: dict[str, Any] = {
                "sym": s.symbol,
                "px": round(s.price, 2),
                "chg": round(s.change_24h_pct, 2) if s.change_24h_pct else None,
                "vol": round(s.volume_24h, 0) if s.volume_24h else None,
                "mcap": s.market_cap,
            }

            # Include compact technicals
            ta = meta.get("technical", {})
            if ta:
                entry["ta"] = {
                    "rsi": ta.get("rsi_14"),
                    "trend": ta.get("trend"),
                    "sma50_dist": ta.get("sma50_distance_pct"),
                }

            # Include compact fundamentals
            fund = meta.get("fundamentals", {})
            if fund:
                entry["fund"] = {
                    "pe": fund.get("pe_ratio"),
                    "ps": fund.get("ps_ratio"),
                    "roe": fund.get("roe"),
                }

            # Include macro regime
            macro = meta.get("macro", {})
            if macro:
                entry["macro"] = macro.get("regime")

            compressed.append(entry)

        return compressed

    # ------------------------------------------------------------------
    # Technical analysis helpers
    # ------------------------------------------------------------------

    def _compute_technicals(self, bars: list[dict[str, Any]]) -> dict[str, Any]:
        """Compute technical indicators from bar data."""
        if not bars or len(bars) < 2:
            return {}

        closes = [b.get("close", 0) for b in bars if b.get("close")]
        volumes = [b.get("volume", 0) for b in bars if b.get("volume")]

        if not closes:
            return {}

        current = closes[-1]
        result: dict[str, Any] = {}

        # SMAs
        if len(closes) >= 20:
            sma_20 = sum(closes[-20:]) / 20
            result["sma_20"] = round(sma_20, 2)
            result["sma20_distance_pct"] = round(
                (current - sma_20) / sma_20 * 100, 2
            ) if sma_20 > 0 else 0

        if len(closes) >= 50:
            sma_50 = sum(closes[-50:]) / 50
            result["sma_50"] = round(sma_50, 2)
            result["sma50_distance_pct"] = round(
                (current - sma_50) / sma_50 * 100, 2
            ) if sma_50 > 0 else 0

        # Trend
        sma_20 = result.get("sma_20", current)
        sma_50 = result.get("sma_50", current)
        if current > sma_20 > sma_50:
            result["trend"] = "bullish"
        elif current < sma_20 < sma_50:
            result["trend"] = "bearish"
        else:
            result["trend"] = "neutral"

        # RSI (14-period)
        if len(closes) >= 15:
            gains = []
            losses = []
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
                result["rsi_14"] = round(rsi, 2)

        # Volume trend
        if len(volumes) >= 20:
            recent_vol = sum(volumes[-5:]) / 5
            older_vol = sum(volumes[-20:-5]) / 15 if len(volumes) >= 20 else recent_vol
            if older_vol > 0:
                result["volume_ratio"] = round(recent_vol / older_vol, 2)
                result["volume_trend"] = (
                    "rising" if recent_vol > older_vol * 1.2
                    else "falling" if recent_vol < older_vol * 0.8
                    else "stable"
                )

        return result

    def _find_peers(
        self,
        symbol: str,
        snapshots: list[MarketSnapshot],
    ) -> list[dict[str, Any]]:
        """Find peer stocks for comparison.

        Groups stocks by sector/category from snapshot metadata.
        """
        target = next((s for s in snapshots if s.symbol == symbol), None)
        if target is None:
            return []

        target_category = target.metadata.get("sector") or target.metadata.get("category")

        peers: list[dict[str, Any]] = []
        for s in snapshots:
            if s.symbol == symbol:
                continue
            s_category = s.metadata.get("sector") or s.metadata.get("category")
            if target_category and s_category == target_category:
                peers.append({
                    "symbol": s.symbol,
                    "price": s.price,
                    "change_24h": s.change_24h_pct,
                })

        return peers[:5]

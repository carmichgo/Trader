"""Polymarket data preprocessing for AI consumption.

Transforms CLOB data, news signals, and resolution timelines into
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


class PolymarketStrategy:
    """Prepares Polymarket data for AI analysis.

    Combines CLOB market data, news headlines, and resolution
    timeline information into AI-consumable contexts.

    Parameters
    ----------
    config:
        Trader configuration for Polymarket-specific parameters.
    """

    def __init__(self, config: TraderConfig) -> None:
        self.config = config

    # ------------------------------------------------------------------
    # Snapshot building
    # ------------------------------------------------------------------

    def build_snapshot(
        self,
        market_data: dict[str, Any],
        yes_price: float,
        orderbook: dict[str, Any] | None = None,
        news_context: list[dict[str, Any]] | None = None,
        resolution_info: dict[str, Any] | None = None,
    ) -> MarketSnapshot:
        """Build a :class:`MarketSnapshot` from Polymarket data.

        Parameters
        ----------
        market_data:
            Market metadata from the CLOB (question, outcomes, etc.).
        yes_price:
            Current YES token price (0.00-1.00).
        orderbook:
            Order book with bids/asks.
        news_context:
            Related news headlines.
        resolution_info:
            Resolution timeline and status.
        """
        condition_id = market_data.get("condition_id", "")

        metadata: dict[str, Any] = {
            "question": market_data.get("question", ""),
            "description": market_data.get("description", "")[:500],
            "outcomes": market_data.get("outcomes", ["Yes", "No"]),
            "no_price": round(1.0 - yes_price, 4),
            "end_date": market_data.get("end_date_iso"),
            "liquidity": market_data.get("liquidity", 0),
        }

        if news_context:
            metadata["related_news"] = [
                {"title": n.get("title", ""), "source": n.get("source", "")}
                for n in news_context[:5]
            ]

        if resolution_info:
            metadata["resolution"] = {
                "status": resolution_info.get("status"),
                "hours_remaining": resolution_info.get("hours_until_resolution"),
            }

        if orderbook:
            bids = orderbook.get("bids", [])
            asks = orderbook.get("asks", [])
            metadata["orderbook_depth"] = {
                "bid_levels": len(bids),
                "ask_levels": len(asks),
                "best_bid": float(bids[0]["price"]) if bids else None,
                "best_ask": float(asks[0]["price"]) if asks else None,
            }

        bid = metadata.get("orderbook_depth", {}).get("best_bid")
        ask = metadata.get("orderbook_depth", {}).get("best_ask")

        return MarketSnapshot(
            market=Market.POLYMARKET,
            symbol=condition_id,
            price=yes_price,
            bid=bid,
            ask=ask,
            spread=(ask - bid) if (bid is not None and ask is not None) else None,
            volume_24h=market_data.get("volume"),
            timestamp=datetime.now(timezone.utc),
            source="polymarket_strategy",
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
        news_headlines: list[dict[str, Any]] | None = None,
        resolution_info: dict[str, Any] | None = None,
        related_markets: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Assemble the full context for Opus analyst evaluation.

        Provides the analyst with market data, news, resolution
        timeline, and portfolio context for informed decision-making.
        """
        target_snapshot = next(
            (s for s in snapshots if s.symbol == opportunity.symbol),
            None,
        )

        return {
            "opportunity": {
                "condition_id": opportunity.symbol,
                "question": opportunity.title or opportunity.description,
                "current_yes_price": opportunity.current_price,
                "current_no_price": (
                    1.0 - opportunity.current_price
                    if opportunity.current_price is not None
                    else None
                ),
                "estimated_edge": opportunity.estimated_edge,
                "confidence": opportunity.confidence,
                "volume_24h": opportunity.volume_24h,
                "liquidity": opportunity.liquidity,
                "category": opportunity.category,
                "url": opportunity.url,
            },
            "current_snapshot": target_snapshot.model_dump() if target_snapshot else None,
            "news_context": (news_headlines or [])[:10],
            "resolution_info": resolution_info or {},
            "related_markets": (related_markets or [])[:5],
            "portfolio_state": portfolio_state.model_dump(),
            "recent_trades": recent_trades[-10:],
            "risk_limits": {
                "max_position_pct": self.config.safety_rails.max_single_trade_pct,
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
        """Compress market snapshots for token-efficient screener input.

        Strips verbose metadata and keeps essential fields for the
        Sonnet screener to quickly evaluate many markets.
        """
        compressed: list[dict[str, Any]] = []

        for s in snapshots:
            meta = s.metadata or {}
            entry: dict[str, Any] = {
                "id": s.symbol,
                "q": meta.get("question", "")[:100],
                "yes": round(s.price, 3),
                "no": round(1.0 - s.price, 3),
                "vol": round(s.volume_24h, 0) if s.volume_24h else None,
                "liq": meta.get("liquidity"),
                "spread": round(s.spread, 4) if s.spread else None,
            }

            # Resolution info
            res = meta.get("resolution", {})
            if res:
                entry["hrs_left"] = res.get("hours_remaining")
                entry["res_status"] = res.get("status")

            # News count
            news = meta.get("related_news", [])
            if news:
                entry["news_n"] = len(news)

            compressed.append(entry)

        return compressed

"""Sonnet-based opportunity scanner.

Feeds a market snapshot through a market-type-specific prompt template,
parses the structured JSON response, and returns scored opportunities.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

import structlog

from packages.core.ai.client import AIClient
from packages.core.ai.cost_tracker import CostTracker
from packages.core.models import (
    Market,
    MarketSnapshot,
    Opportunity,
    ScreenerResult,
    TraderConfig,
)

logger = structlog.get_logger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

# Mapping from Market enum to prompt template filename
_PROMPT_MAP: dict[Market, str] = {
    Market.POLYMARKET: "screener_poly.md",
    Market.CRYPTO: "screener_crypto.md",
    Market.STOCKS: "screener_stocks.md",
}


def _load_prompt(market_type: Market) -> str:
    """Load the screener prompt template for the given market type."""
    filename = _PROMPT_MAP.get(market_type)
    if filename is None:
        raise ValueError(f"No screener prompt template for market type: {market_type}")
    path = PROMPTS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    return path.read_text()


def _format_snapshots(snapshots: list[MarketSnapshot]) -> str:
    """Serialise a list of market snapshots into a readable text block."""
    lines: list[str] = []
    for snap in snapshots:
        parts = [
            f"Symbol: {snap.symbol}",
            f"Price: {snap.price}",
        ]
        if snap.volume_24h is not None:
            parts.append(f"Volume24h: {snap.volume_24h}")
        if snap.change_24h_pct is not None:
            parts.append(f"Change24h: {snap.change_24h_pct:.2f}%")
        if snap.bid is not None and snap.ask is not None:
            parts.append(f"Bid/Ask: {snap.bid}/{snap.ask}")
        if snap.spread is not None:
            parts.append(f"Spread: {snap.spread}")
        if snap.open_interest is not None:
            parts.append(f"OI: {snap.open_interest}")
        if snap.funding_rate is not None:
            parts.append(f"FundingRate: {snap.funding_rate}")
        if snap.market_cap is not None:
            parts.append(f"MarketCap: {snap.market_cap}")
        if snap.metadata:
            for k, v in snap.metadata.items():
                parts.append(f"{k}: {v}")
        lines.append(" | ".join(parts))
    return "\n".join(lines)


class Screener:
    """Sonnet-powered market opportunity scanner.

    Usage::

        screener = Screener(ai_client, cost_tracker, trader_id="t1")
        result = await screener.scan(snapshots, config, Market.CRYPTO)
    """

    def __init__(
        self,
        ai_client: AIClient,
        cost_tracker: CostTracker,
        trader_id: str = "default",
    ) -> None:
        self._ai = ai_client
        self._cost = cost_tracker
        self._trader_id = trader_id

    async def scan(
        self,
        market_snapshots: list[MarketSnapshot],
        trader_config: TraderConfig,
        market_type: Market,
    ) -> ScreenerResult:
        """Run the screener against a batch of market snapshots.

        Returns a :class:`ScreenerResult` containing discovered opportunities.
        """
        start = time.perf_counter()

        # Check budget before calling AI
        if await self._cost.is_budget_exhausted(self._trader_id):
            logger.warning("screener_budget_exhausted", trader_id=self._trader_id)
            return ScreenerResult(
                market=market_type,
                screener_name=f"sonnet-{market_type.value}",
                total_scanned=len(market_snapshots),
                total_passed=0,
            )

        # Build prompt
        template = _load_prompt(market_type)
        system_prompt = "You are an expert market screener for the AI trading system. You identify high-quality trading opportunities by analyzing market data. Always respond with valid JSON."
        user_prompt = template.format(
            market_data=_format_snapshots(market_snapshots),
            num_markets=len(market_snapshots),
            market_type=market_type.value,
            max_positions=trader_config.max_positions_per_market,
            available_balance=trader_config.initial_balance,
            risk_tolerance=trader_config.default_stop_loss_pct,
            enabled_strategies=", ".join(trader_config.enabled_strategies) or "all",
        )

        # Call Sonnet
        response = await self._ai.call_sonnet(system_prompt, user_prompt)

        # Record cost
        await self._cost.record_call(
            trader_id=self._trader_id,
            response=response,
            purpose=f"screener_{market_type.value}",
        )

        # Parse opportunities from JSON response
        opportunities = self._parse_opportunities(response.content, market_type)
        duration = time.perf_counter() - start

        result = ScreenerResult(
            id=str(uuid.uuid4()),
            market=market_type,
            screener_name=f"sonnet-{market_type.value}",
            opportunities=opportunities,
            total_scanned=len(market_snapshots),
            total_passed=len(opportunities),
            inference_cost=response.cost_usd,
            duration_seconds=round(duration, 2),
        )

        logger.info(
            "screener_complete",
            market=market_type.value,
            scanned=len(market_snapshots),
            opportunities=len(opportunities),
            cost_usd=response.cost_usd,
            latency_ms=response.latency_ms,
        )

        return result

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_opportunities(content: str, market_type: Market) -> list[Opportunity]:
        """Extract a list of Opportunity objects from the AI JSON response."""
        try:
            # Handle both bare JSON and markdown-fenced JSON
            text = content.strip()
            if text.startswith("```"):
                # Strip code fences
                lines = text.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                text = "\n".join(lines)
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.error("screener_json_parse_failed", content_preview=content[:200])
            return []

        # Accept both {"opportunities": [...]} and bare [...]
        items: list[dict[str, Any]] = []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict) and "opportunities" in data:
            items = data["opportunities"]
        else:
            logger.warning("screener_unexpected_json_shape", keys=list(data.keys()) if isinstance(data, dict) else type(data).__name__)
            return []

        opportunities: list[Opportunity] = []
        for item in items:
            try:
                opp = Opportunity(
                    id=str(uuid.uuid4()),
                    market=market_type,
                    symbol=item.get("symbol", "UNKNOWN"),
                    title=item.get("title"),
                    description=item.get("description") or item.get("reasoning"),
                    current_price=item.get("current_price") or item.get("price"),
                    estimated_edge=item.get("estimated_edge") or item.get("edge"),
                    confidence=float(item.get("confidence", 0.5)),
                    volume_24h=item.get("volume_24h") or item.get("volume"),
                    liquidity=item.get("liquidity"),
                    volatility=item.get("volatility"),
                    category=item.get("category"),
                    tags=item.get("tags", []),
                    source="screener-sonnet",
                    url=item.get("url"),
                    metadata=item.get("metadata", {}),
                )
                opportunities.append(opp)
            except Exception:
                logger.warning("screener_opportunity_parse_failed", item=item, exc_info=True)
                continue

        return opportunities

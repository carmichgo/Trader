"""Opus-based deep analysis for high-conviction trade opportunities.

When the screener surfaces a promising opportunity, the Analyst runs a
thorough evaluation using Claude Opus.  It applies a pre-call cost gate
(NEV check, position-size threshold, remaining budget) so expensive Opus
calls are only made when justified.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import structlog
from pydantic import BaseModel, Field

from packages.core.ai.client import AIClient
from packages.core.ai.cost_tracker import CostTracker
from packages.core.models import (
    Direction,
    Market,
    NetExpectedValue,
    Opportunity,
    TraderConfig,
)

if TYPE_CHECKING:
    from packages.core.db.supabase_client import SupabaseDB

logger = structlog.get_logger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

# Mapping from Market enum to analyst prompt template filename
_PROMPT_MAP: dict[Market, str] = {
    Market.POLYMARKET: "analyst_poly.md",
    Market.CRYPTO: "analyst_crypto.md",
    Market.STOCKS: "analyst_stocks.md",
}


# ---------------------------------------------------------------------------
# TradePlan model
# ---------------------------------------------------------------------------


class TradePlan(BaseModel):
    """Structured output from the Analyst when it approves a trade."""

    id: Optional[str] = None
    opportunity_id: Optional[str] = None
    market: Market
    symbol: str
    direction: Direction
    confidence: float = Field(ge=0.0, le=1.0)
    entry_price: float
    stop_loss_price: float
    take_profit_price: float
    position_size_usd: float
    leverage: float = 1.0
    timeframe: Optional[str] = None
    expected_return_pct: Optional[float] = None
    risk_reward_ratio: Optional[float] = None
    max_holding_hours: Optional[int] = None
    reasoning: str = ""
    key_risks: list[str] = Field(default_factory=list)
    catalysts: list[str] = Field(default_factory=list)
    invalidation_conditions: list[str] = Field(default_factory=list)
    inference_cost: float = 0.0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------


def _load_prompt(market_type: Market) -> str:
    """Load the analyst prompt template for the given market type."""
    filename = _PROMPT_MAP.get(market_type)
    if filename is None:
        raise ValueError(f"No analyst prompt template for market type: {market_type}")
    path = PROMPTS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    return path.read_text()


# ---------------------------------------------------------------------------
# Analyst
# ---------------------------------------------------------------------------


class Analyst:
    """Opus-powered deep-analysis engine.

    Usage::

        analyst = Analyst(ai_client, cost_tracker, trader_id="t1")
        plan = await analyst.analyze(opportunity, context, Market.CRYPTO)
        if plan is not None:
            # execute the trade
            ...
    """

    # Minimum NEV (in USD) an opportunity must have before we spend on Opus
    MIN_NEV_THRESHOLD: float = 0.50
    # Minimum position size (USD) that warrants an Opus call
    MIN_POSITION_SIZE_THRESHOLD: float = 20.0
    # Estimated cost of a single Opus call (for budget gating)
    ESTIMATED_OPUS_COST: float = 0.15

    def __init__(
        self,
        ai_client: AIClient,
        cost_tracker: CostTracker,
        trader_id: str = "default",
        supabase_db: SupabaseDB | None = None,
    ) -> None:
        self._ai = ai_client
        self._cost = cost_tracker
        self._trader_id = trader_id
        self._supabase_db = supabase_db

    # ------------------------------------------------------------------
    # Pre-Opus cost gate
    # ------------------------------------------------------------------

    async def should_call_opus(
        self,
        opportunity: Opportunity,
        trader_config: TraderConfig,
        nev: NetExpectedValue | None = None,
    ) -> bool:
        """Decide whether an Opus call is justified for this opportunity.

        Checks three conditions:
        1. Net Expected Value exceeds ``MIN_NEV_THRESHOLD``
        2. Likely position size exceeds ``MIN_POSITION_SIZE_THRESHOLD``
        3. Remaining daily budget can cover the estimated Opus cost

        Returns ``True`` only if all three pass.
        """
        # 1. NEV check
        if nev is not None and nev.net_expected_value < self.MIN_NEV_THRESHOLD:
            logger.info(
                "analyst_gate_nev_too_low",
                symbol=opportunity.symbol,
                nev=nev.net_expected_value,
                threshold=self.MIN_NEV_THRESHOLD,
            )
            return False

        # 2. Position size check -- estimate from available balance & confidence
        estimated_position = (
            trader_config.initial_balance
            * trader_config.safety_rails.max_single_trade_pct
            * opportunity.confidence
        )
        if estimated_position < self.MIN_POSITION_SIZE_THRESHOLD:
            logger.info(
                "analyst_gate_position_too_small",
                symbol=opportunity.symbol,
                estimated_position=estimated_position,
                threshold=self.MIN_POSITION_SIZE_THRESHOLD,
            )
            return False

        # 3. Budget check
        remaining = await self._cost.remaining_budget(self._trader_id)
        if remaining < self.ESTIMATED_OPUS_COST:
            logger.warning(
                "analyst_gate_budget_insufficient",
                symbol=opportunity.symbol,
                remaining=remaining,
                estimated_cost=self.ESTIMATED_OPUS_COST,
            )
            return False

        return True

    # ------------------------------------------------------------------
    # Core analysis
    # ------------------------------------------------------------------

    async def analyze(
        self,
        opportunity: Opportunity,
        full_context: dict[str, Any],
        market_type: Market,
    ) -> TradePlan | None:
        """Run deep Opus analysis on a single opportunity.

        Parameters
        ----------
        opportunity:
            The screened opportunity to evaluate.
        full_context:
            Dictionary with supporting data: ``portfolio_state``,
            ``recent_trades``, ``market_conditions``, ``trader_config``, etc.
        market_type:
            Which market the opportunity belongs to.

        Returns
        -------
        TradePlan | None
            A structured trade plan if Opus recommends the trade,
            ``None`` if rejected.
        """
        start = time.perf_counter()

        # Build prompt
        template = _load_prompt(market_type)
        system_prompt = (
            "You are an elite quantitative analyst for the AI trading system. "
            "You perform deep fundamental and technical analysis on opportunities "
            "surfaced by the screener. Your job is to either approve with a detailed "
            "trade plan or reject with a clear reason. Always respond with valid JSON."
        )

        user_prompt = template.format(
            symbol=opportunity.symbol,
            market_type=market_type.value,
            current_price=opportunity.current_price or "N/A",
            estimated_edge=opportunity.estimated_edge or "N/A",
            screener_confidence=opportunity.confidence,
            title=opportunity.title or opportunity.symbol,
            description=opportunity.description or "N/A",
            volume_24h=opportunity.volume_24h or "N/A",
            liquidity=opportunity.liquidity or "N/A",
            volatility=opportunity.volatility or "N/A",
            category=opportunity.category or "N/A",
            tags=", ".join(opportunity.tags) if opportunity.tags else "none",
            portfolio_state=json.dumps(
                full_context.get("portfolio_state", {}), default=str, indent=2
            ),
            recent_trades=json.dumps(
                full_context.get("recent_trades", []), default=str, indent=2
            ),
            market_conditions=json.dumps(
                full_context.get("market_conditions", {}), default=str, indent=2
            ),
            risk_limits=json.dumps(
                full_context.get("risk_limits", {}), default=str, indent=2
            ),
            available_balance=full_context.get("available_balance", 0),
            max_position_pct=full_context.get("max_position_pct", 0.25),
        )

        # Call Opus
        response = await self._ai.call_opus(system_prompt, user_prompt)

        # Record cost
        await self._cost.record_call(
            trader_id=self._trader_id,
            response=response,
            purpose=f"analyst_{market_type.value}",
            signal_id=opportunity.id,
        )

        duration = time.perf_counter() - start

        # Parse response
        plan = self._parse_trade_plan(
            response.content, opportunity, market_type, response.cost_usd
        )

        logger.info(
            "analyst_complete",
            symbol=opportunity.symbol,
            market=market_type.value,
            approved=plan is not None,
            cost_usd=response.cost_usd,
            latency_ms=response.latency_ms,
            duration_s=round(duration, 2),
        )

        # Persist analyst AI decision to Supabase
        if self._supabase_db:
            try:
                await self._supabase_db.insert_ai_decision({
                    "trader": self._trader_id,
                    "decision_type": "analyst",
                    "symbol": opportunity.symbol,
                    "market": market_type.value,
                    "decision": "approve" if plan is not None else "reject",
                    "confidence": plan.confidence if plan else opportunity.confidence,
                    "reasoning": plan.reasoning if plan else "Rejected by analyst",
                    "inference_cost": response.cost_usd,
                    "created_at": datetime.utcnow().isoformat(),
                    "metadata": {
                        "latency_ms": response.latency_ms,
                        "duration_s": round(duration, 2),
                        "opportunity_id": opportunity.id,
                    },
                })
            except Exception:
                logger.exception("supabase_analyst_decision_failed")

        return plan

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_trade_plan(
        content: str,
        opportunity: Opportunity,
        market_type: Market,
        inference_cost: float,
    ) -> TradePlan | None:
        """Parse the Opus JSON response into a TradePlan or None."""
        try:
            text = content.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                text = "\n".join(lines)
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.error("analyst_json_parse_failed", content_preview=content[:300])
            return None

        # Check if the AI rejected the opportunity
        decision = data.get("decision", "").lower()
        if decision in ("reject", "skip", "pass", "no"):
            logger.info(
                "analyst_rejected",
                symbol=opportunity.symbol,
                reason=data.get("reasoning", "no reason given"),
            )
            return None

        # Build TradePlan from the approved response
        try:
            direction_str = data.get("direction", "buy").lower()
            direction_map = {"buy": Direction.BUY, "sell": Direction.SELL, "short": Direction.SHORT}
            direction = direction_map.get(direction_str, Direction.BUY)

            plan = TradePlan(
                id=str(uuid.uuid4()),
                opportunity_id=opportunity.id,
                market=market_type,
                symbol=opportunity.symbol,
                direction=direction,
                confidence=float(data.get("confidence", opportunity.confidence)),
                entry_price=float(data.get("entry_price", opportunity.current_price or 0)),
                stop_loss_price=float(data.get("stop_loss_price", 0)),
                take_profit_price=float(data.get("take_profit_price", 0)),
                position_size_usd=float(data.get("position_size_usd", 0)),
                leverage=float(data.get("leverage", 1.0)),
                timeframe=data.get("timeframe"),
                expected_return_pct=data.get("expected_return_pct"),
                risk_reward_ratio=data.get("risk_reward_ratio"),
                max_holding_hours=data.get("max_holding_hours"),
                reasoning=data.get("reasoning", ""),
                key_risks=data.get("key_risks", []),
                catalysts=data.get("catalysts", []),
                invalidation_conditions=data.get("invalidation_conditions", []),
                inference_cost=inference_cost,
            )
            return plan
        except Exception:
            logger.error(
                "analyst_trade_plan_build_failed",
                symbol=opportunity.symbol,
                exc_info=True,
            )
            return None

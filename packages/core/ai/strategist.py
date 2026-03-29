"""Daily Opus meta-brain -- the Strategist.

Runs once per day (and on-demand for emergencies) to set portfolio-level
strategy: market allocations, risk posture, position sizing guidance, and
whether to pause or resume trading.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from packages.core.ai.client import AIClient
from packages.core.ai.cost_tracker import CostTracker
from packages.core.models import (
    NormalizedSignal,
    Opportunity,
    StrategistInput,
    StrategistOutput,
)

if TYPE_CHECKING:
    from packages.core.db.supabase_client import SupabaseDB

logger = structlog.get_logger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def _load_prompt(filename: str) -> str:
    """Load a prompt template by filename from the prompts directory."""
    path = PROMPTS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    return path.read_text()


class Strategist:
    """Opus-powered daily meta-brain for portfolio-level decisions.

    Usage::

        strategist = Strategist(ai_client, cost_tracker, trader_id="t1")
        output = await strategist.run_daily(strategist_input)
    """

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
    # Daily run
    # ------------------------------------------------------------------

    async def run_daily(self, input: StrategistInput) -> StrategistOutput:
        """Execute the daily strategist planning session.

        Parameters
        ----------
        input:
            Comprehensive snapshot of portfolio state, open opportunities,
            signals, config, and recent results.

        Returns
        -------
        StrategistOutput
            Portfolio-level instructions for the day.
        """
        start = time.perf_counter()

        system_prompt = _load_prompt("strategist_system.md")
        daily_template = _load_prompt("strategist_daily.md")

        user_prompt = daily_template.format(
            current_date=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            total_balance=input.portfolio_state.total_balance,
            available_balance=input.portfolio_state.available_balance,
            allocated_balance=input.portfolio_state.allocated_balance,
            unrealized_pnl=input.portfolio_state.unrealized_pnl,
            realized_pnl_today=input.portfolio_state.realized_pnl_today,
            realized_pnl_total=input.portfolio_state.realized_pnl_total,
            open_position_count=input.portfolio_state.open_position_count,
            win_rate=input.portfolio_state.win_rate,
            current_drawdown=input.portfolio_state.current_drawdown,
            max_drawdown=input.portfolio_state.max_drawdown,
            peak_balance=input.portfolio_state.peak_balance,
            sharpe_ratio=input.portfolio_state.sharpe_ratio or "N/A",
            sortino_ratio=input.portfolio_state.sortino_ratio or "N/A",
            profit_factor=input.portfolio_state.profit_factor or "N/A",
            total_trades=input.portfolio_state.total_trades,
            winning_trades=input.portfolio_state.winning_trades,
            losing_trades=input.portfolio_state.losing_trades,
            avg_win=input.portfolio_state.avg_win,
            avg_loss=input.portfolio_state.avg_loss,
            largest_win=input.portfolio_state.largest_win,
            largest_loss=input.portfolio_state.largest_loss,
            current_streak=input.portfolio_state.current_streak,
            losing_streak=input.portfolio_state.losing_streak,
            allocation_by_market=json.dumps(
                input.portfolio_state.allocation_by_market, indent=2
            ),
            open_positions=json.dumps(
                [p.model_dump(mode="json") for p in input.portfolio_state.open_positions],
                default=str,
                indent=2,
            ),
            daily_pnl_history=json.dumps(input.portfolio_state.daily_pnl_history[-14:]),
            total_fees_paid=input.portfolio_state.total_fees_paid,
            total_inference_cost=input.portfolio_state.total_inference_cost,
            opportunities_count=len(input.opportunities),
            opportunities_summary=self._summarize_opportunities(input.opportunities),
            signals_count=len(input.normalized_signals),
            signals_summary=self._summarize_signals(input.normalized_signals),
            recent_trade_results=json.dumps(
                input.recent_trade_results[-20:], default=str, indent=2
            ),
            config_name=input.config.name,
            config_mode=input.config.mode,
            config_markets=", ".join(m.value for m in input.config.markets),
            target_balance=input.config.target_balance or "N/A",
            target_date=str(input.config.target_date or "N/A"),
            max_daily_drawdown_pct=input.config.safety_rails.max_daily_drawdown_pct,
            kill_switch_drawdown_pct=input.config.safety_rails.kill_switch_drawdown_pct,
            max_single_trade_pct=input.config.safety_rails.max_single_trade_pct,
            max_concurrent_positions=input.config.safety_rails.max_concurrent_positions,
            max_daily_inference_cost=input.config.safety_rails.max_daily_inference_cost,
            inference_cost_today=input.current_inference_cost_today,
            budget_remaining=input.budget_remaining or "N/A",
        )

        # Call Opus
        response = await self._ai.call_opus(system_prompt, user_prompt)

        # Record cost
        await self._cost.record_call(
            trader_id=self._trader_id,
            response=response,
            purpose="strategist_daily",
        )

        duration = time.perf_counter() - start

        # Parse structured output
        output = self._parse_output(response.content, response.cost_usd, duration)

        logger.info(
            "strategist_daily_complete",
            trader_id=self._trader_id,
            recommended_trades=len(output.recommended_trades),
            positions_to_close=len(output.positions_to_close),
            confidence=output.confidence,
            cost_usd=response.cost_usd,
            latency_ms=response.latency_ms,
        )

        # Persist strategist plan to Supabase
        if self._supabase_db:
            try:
                await self._supabase_db.insert_strategist_plan({
                    "trader": self._trader_id,
                    "plan_type": "daily",
                    "confidence": output.confidence,
                    "reasoning": output.reasoning,
                    "recommended_trades": output.recommended_trades,
                    "positions_to_close": output.positions_to_close,
                    "positions_to_adjust": output.positions_to_adjust,
                    "rebalance_actions": output.rebalance_actions,
                    "risk_assessment": output.risk_assessment,
                    "inference_cost": output.inference_cost,
                    "created_at": datetime.utcnow().isoformat(),
                })
            except Exception:
                logger.exception("supabase_strategist_plan_failed")

        return output

    # ------------------------------------------------------------------
    # Emergency rerun
    # ------------------------------------------------------------------

    async def run_emergency(
        self, input: StrategistInput, reason: str
    ) -> StrategistOutput:
        """Trigger an emergency mid-day strategist rerun.

        This is invoked when the system detects unusual conditions such as
        a sudden drawdown, market crash, or kill-switch proximity.

        Parameters
        ----------
        input:
            Current portfolio state and context.
        reason:
            Human-readable reason for the emergency rerun (e.g.
            ``"drawdown exceeded 8% in 2 hours"``).
        """
        start = time.perf_counter()

        system_prompt = _load_prompt("strategist_system.md")
        daily_template = _load_prompt("strategist_daily.md")

        # Build the same daily context but prepend the emergency header
        emergency_header = (
            f"**EMERGENCY RERUN**\n"
            f"Reason: {reason}\n"
            f"Timestamp: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
            f"This is a mid-day emergency strategy review. Prioritize capital preservation. "
            f"Evaluate whether positions should be closed immediately. "
            f"Be more conservative than a normal daily plan.\n\n"
            f"---\n\n"
        )

        user_prompt = emergency_header + daily_template.format(
            current_date=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            total_balance=input.portfolio_state.total_balance,
            available_balance=input.portfolio_state.available_balance,
            allocated_balance=input.portfolio_state.allocated_balance,
            unrealized_pnl=input.portfolio_state.unrealized_pnl,
            realized_pnl_today=input.portfolio_state.realized_pnl_today,
            realized_pnl_total=input.portfolio_state.realized_pnl_total,
            open_position_count=input.portfolio_state.open_position_count,
            win_rate=input.portfolio_state.win_rate,
            current_drawdown=input.portfolio_state.current_drawdown,
            max_drawdown=input.portfolio_state.max_drawdown,
            peak_balance=input.portfolio_state.peak_balance,
            sharpe_ratio=input.portfolio_state.sharpe_ratio or "N/A",
            sortino_ratio=input.portfolio_state.sortino_ratio or "N/A",
            profit_factor=input.portfolio_state.profit_factor or "N/A",
            total_trades=input.portfolio_state.total_trades,
            winning_trades=input.portfolio_state.winning_trades,
            losing_trades=input.portfolio_state.losing_trades,
            avg_win=input.portfolio_state.avg_win,
            avg_loss=input.portfolio_state.avg_loss,
            largest_win=input.portfolio_state.largest_win,
            largest_loss=input.portfolio_state.largest_loss,
            current_streak=input.portfolio_state.current_streak,
            losing_streak=input.portfolio_state.losing_streak,
            allocation_by_market=json.dumps(
                input.portfolio_state.allocation_by_market, indent=2
            ),
            open_positions=json.dumps(
                [p.model_dump(mode="json") for p in input.portfolio_state.open_positions],
                default=str,
                indent=2,
            ),
            daily_pnl_history=json.dumps(input.portfolio_state.daily_pnl_history[-14:]),
            total_fees_paid=input.portfolio_state.total_fees_paid,
            total_inference_cost=input.portfolio_state.total_inference_cost,
            opportunities_count=len(input.opportunities),
            opportunities_summary=self._summarize_opportunities(input.opportunities),
            signals_count=len(input.normalized_signals),
            signals_summary=self._summarize_signals(input.normalized_signals),
            recent_trade_results=json.dumps(
                input.recent_trade_results[-20:], default=str, indent=2
            ),
            config_name=input.config.name,
            config_mode=input.config.mode,
            config_markets=", ".join(m.value for m in input.config.markets),
            target_balance=input.config.target_balance or "N/A",
            target_date=str(input.config.target_date or "N/A"),
            max_daily_drawdown_pct=input.config.safety_rails.max_daily_drawdown_pct,
            kill_switch_drawdown_pct=input.config.safety_rails.kill_switch_drawdown_pct,
            max_single_trade_pct=input.config.safety_rails.max_single_trade_pct,
            max_concurrent_positions=input.config.safety_rails.max_concurrent_positions,
            max_daily_inference_cost=input.config.safety_rails.max_daily_inference_cost,
            inference_cost_today=input.current_inference_cost_today,
            budget_remaining=input.budget_remaining or "N/A",
        )

        response = await self._ai.call_opus(system_prompt, user_prompt)

        await self._cost.record_call(
            trader_id=self._trader_id,
            response=response,
            purpose="strategist_emergency",
        )

        duration = time.perf_counter() - start
        output = self._parse_output(response.content, response.cost_usd, duration)

        logger.warning(
            "strategist_emergency_complete",
            trader_id=self._trader_id,
            reason=reason,
            recommended_trades=len(output.recommended_trades),
            positions_to_close=len(output.positions_to_close),
            confidence=output.confidence,
            cost_usd=response.cost_usd,
        )

        return output

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _summarize_opportunities(opportunities: list[Opportunity]) -> str:
        """Build a concise text summary of current opportunities."""
        if not opportunities:
            return "No opportunities currently available."
        lines: list[str] = []
        for opp in opportunities[:30]:  # Cap at 30 to manage token usage
            edge = f"edge={opp.estimated_edge:.2%}" if opp.estimated_edge else "edge=N/A"
            lines.append(
                f"- {opp.symbol} ({opp.market.value}): "
                f"price={opp.current_price}, conf={opp.confidence:.2f}, {edge}"
                f"{', ' + opp.title if opp.title else ''}"
            )
        return "\n".join(lines)

    @staticmethod
    def _summarize_signals(signals: list[NormalizedSignal]) -> str:
        """Build a concise text summary of normalized signals."""
        if not signals:
            return "No normalized signals."
        lines: list[str] = []
        for sig in signals[:20]:
            lines.append(
                f"- {sig.symbol} ({sig.market.value}): "
                f"direction={sig.direction.value}, "
                f"conf={sig.normalized_confidence:.2f}, "
                f"expected_return={sig.expected_return or 'N/A'}"
            )
        return "\n".join(lines)

    @staticmethod
    def _parse_output(
        content: str, inference_cost: float, duration: float
    ) -> StrategistOutput:
        """Parse Opus JSON response into a StrategistOutput."""
        try:
            text = content.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                text = "\n".join(lines)
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.error("strategist_json_parse_failed", content_preview=content[:400])
            return StrategistOutput(
                reasoning="Failed to parse strategist output.",
                confidence=0.0,
                inference_cost=inference_cost,
                duration_seconds=round(duration, 2),
            )

        try:
            output = StrategistOutput(
                id=str(uuid.uuid4()),
                recommended_trades=data.get("recommended_trades", []),
                positions_to_close=data.get("positions_to_close", []),
                positions_to_adjust=data.get("positions_to_adjust", []),
                rebalance_actions=data.get("rebalance_actions", []),
                reasoning=data.get("reasoning", ""),
                risk_assessment=data.get("risk_assessment"),
                confidence=float(data.get("confidence", 0.5)),
                estimated_portfolio_impact=data.get("estimated_portfolio_impact"),
                inference_cost=inference_cost,
                duration_seconds=round(duration, 2),
                metadata=data.get("metadata", {}),
            )
            return output
        except Exception:
            logger.error("strategist_output_build_failed", exc_info=True)
            return StrategistOutput(
                reasoning="Failed to build strategist output from parsed data.",
                confidence=0.0,
                inference_cost=inference_cost,
                duration_seconds=round(duration, 2),
            )

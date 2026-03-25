"""AI decision log routes: query AI inference history and strategist plans."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, desc, and_
from sqlalchemy.ext.asyncio import AsyncSession

from packages.core.db.models import AIDecision, StrategistPlan
from api.deps import get_db_session

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.get("/decisions")
async def list_ai_decisions(
    decision_type: str | None = Query(None, description="Filter by type (screener, analyst, strategist)"),
    trader: str | None = Query(None, description="Filter by trader name"),
    since_hours: int = Query(24, ge=1, le=720, description="Return decisions from the last N hours"),
    limit: int = Query(50, ge=1, le=500, description="Max decisions to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Return AI inference decisions with optional filters.

    Each decision includes the model used, token counts, cost, latency,
    and the summarised input/output.
    """
    since = datetime.utcnow() - timedelta(hours=since_hours)

    conditions = [AIDecision.created_at >= since]
    if decision_type:
        conditions.append(AIDecision.decision_type == decision_type)
    if trader:
        conditions.append(AIDecision.trader == trader)

    query = (
        select(AIDecision)
        .where(and_(*conditions))
        .order_by(desc(AIDecision.created_at))
        .limit(limit)
        .offset(offset)
    )

    result = await session.execute(query)
    decisions = result.scalars().all()

    return {
        "decisions": [
            {
                "id": str(d.id),
                "decision_type": d.decision_type,
                "trader": d.trader,
                "model": d.model,
                "prompt_tokens": d.prompt_tokens,
                "completion_tokens": d.completion_tokens,
                "cost_usd": float(d.cost_usd),
                "latency_ms": d.latency_ms,
                "input_summary": d.input_summary,
                "output_raw": d.output_raw,
                "related_trade_id": str(d.related_trade_id) if d.related_trade_id else None,
                "created_at": d.created_at.isoformat(),
            }
            for d in decisions
        ],
        "limit": limit,
        "offset": offset,
    }


@router.get("/strategist/latest")
async def get_latest_strategist_plan(
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Return the most recent strategist plan with allocations and reasoning.

    The strategist runs once daily (or on-demand during drawdown events)
    and produces market allocations, trader configs, and a daily P&L target.
    """
    query = (
        select(StrategistPlan)
        .order_by(desc(StrategistPlan.created_at))
        .limit(1)
    )
    result = await session.execute(query)
    plan = result.scalar_one_or_none()

    if plan is None:
        return {"plan": None, "message": "No strategist plan has been generated yet."}

    return {
        "plan": {
            "id": str(plan.id),
            "goal_id": str(plan.goal_id),
            "plan_date": str(plan.plan_date),
            "allocations": plan.allocations,
            "trader_configs": plan.trader_configs,
            "daily_target": float(plan.daily_target),
            "reasoning": plan.reasoning,
            "goal_feasibility": float(plan.goal_feasibility) if plan.goal_feasibility else None,
            "inference_cost": float(plan.inference_cost) if plan.inference_cost else None,
            "tokens_in": plan.tokens_in,
            "tokens_out": plan.tokens_out,
            "created_at": plan.created_at.isoformat(),
        },
    }

"""Cost tracking routes: inference costs, trading fees, and daily summaries."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, desc, and_, cast, Date
from sqlalchemy.ext.asyncio import AsyncSession

from packages.core.db.models import AIDecision, DailyPerformance, Trade
from api.deps import get_db_session

router = APIRouter(prefix="/api/costs", tags=["costs"])


@router.get("")
async def get_costs(
    days: int = Query(7, ge=1, le=365, description="Number of days of cost history"),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Return cost breakdown over the requested window.

    Aggregates AI inference costs and trading fees per day from
    the daily_performance and ai_decisions tables.
    """
    since_date = (datetime.utcnow() - timedelta(days=days)).date()

    # Daily performance costs (already aggregated per trader per day)
    perf_q = (
        select(
            DailyPerformance.date,
            func.sum(DailyPerformance.total_inference_cost).label("inference_cost"),
            func.sum(DailyPerformance.total_trading_fees).label("trading_fees"),
            func.sum(DailyPerformance.total_slippage).label("slippage"),
        )
        .where(DailyPerformance.date >= since_date)
        .group_by(DailyPerformance.date)
        .order_by(DailyPerformance.date.asc())
    )
    perf_result = await session.execute(perf_q)
    daily_costs = perf_result.all()

    # AI cost breakdown by model
    model_q = (
        select(
            AIDecision.model,
            func.count().label("call_count"),
            func.sum(AIDecision.prompt_tokens).label("total_prompt_tokens"),
            func.sum(AIDecision.completion_tokens).label("total_completion_tokens"),
            func.sum(AIDecision.cost_usd).label("total_cost"),
        )
        .where(AIDecision.created_at >= datetime.utcnow() - timedelta(days=days))
        .group_by(AIDecision.model)
        .order_by(desc("total_cost"))
    )
    model_result = await session.execute(model_q)
    model_breakdown = model_result.all()

    # Totals
    total_inference = sum(float(r.inference_cost or 0) for r in daily_costs)
    total_fees = sum(float(r.trading_fees or 0) for r in daily_costs)
    total_slippage = sum(float(r.slippage or 0) for r in daily_costs)

    return {
        "summary": {
            "days": days,
            "total_inference_cost": round(total_inference, 6),
            "total_trading_fees": round(total_fees, 6),
            "total_slippage": round(total_slippage, 6),
            "total_all_costs": round(total_inference + total_fees + total_slippage, 6),
        },
        "daily": [
            {
                "date": str(r.date),
                "inference_cost": float(r.inference_cost or 0),
                "trading_fees": float(r.trading_fees or 0),
                "slippage": float(r.slippage or 0),
            }
            for r in daily_costs
        ],
        "by_model": [
            {
                "model": r.model,
                "call_count": r.call_count,
                "total_prompt_tokens": r.total_prompt_tokens,
                "total_completion_tokens": r.total_completion_tokens,
                "total_cost": float(r.total_cost or 0),
            }
            for r in model_breakdown
        ],
    }


@router.get("/today")
async def get_costs_today(
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Return cost data for today only.

    Useful for dashboard widgets showing real-time cost burn rate and
    comparing against the daily AI budget limit.
    """
    today = date.today()
    today_start = datetime.combine(today, datetime.min.time())

    # Today's AI inference costs
    ai_q = (
        select(
            func.count().label("call_count"),
            func.sum(AIDecision.cost_usd).label("total_cost"),
            func.sum(AIDecision.prompt_tokens).label("prompt_tokens"),
            func.sum(AIDecision.completion_tokens).label("completion_tokens"),
        )
        .where(AIDecision.created_at >= today_start)
    )
    ai_result = (await session.execute(ai_q)).one()

    # Today's AI costs by decision type
    by_type_q = (
        select(
            AIDecision.decision_type,
            func.count().label("count"),
            func.sum(AIDecision.cost_usd).label("cost"),
        )
        .where(AIDecision.created_at >= today_start)
        .group_by(AIDecision.decision_type)
    )
    by_type_result = await session.execute(by_type_q)
    by_type = by_type_result.all()

    # Today's trading fees from closed trades
    fee_q = (
        select(
            func.sum(Trade.exchange_fee).label("exchange_fees"),
            func.sum(Trade.slippage).label("slippage"),
            func.sum(Trade.total_cost).label("total_trade_cost"),
        )
        .where(
            and_(
                Trade.closed_at >= today_start,
                Trade.status == "closed",
            )
        )
    )
    fee_result = (await session.execute(fee_q)).one()

    inference_cost = float(ai_result.total_cost or 0)
    exchange_fees = float(fee_result.exchange_fees or 0)
    slippage = float(fee_result.slippage or 0)

    return {
        "date": str(today),
        "inference": {
            "total_cost": round(inference_cost, 6),
            "call_count": ai_result.call_count or 0,
            "prompt_tokens": ai_result.prompt_tokens or 0,
            "completion_tokens": ai_result.completion_tokens or 0,
            "by_type": [
                {
                    "decision_type": r.decision_type,
                    "count": r.count,
                    "cost": float(r.cost or 0),
                }
                for r in by_type
            ],
        },
        "trading": {
            "exchange_fees": round(exchange_fees, 6),
            "slippage": round(slippage, 6),
            "total_trade_costs": float(fee_result.total_trade_cost or 0),
        },
        "total_all_costs": round(inference_cost + exchange_fees + slippage, 6),
    }

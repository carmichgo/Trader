"""Goal and pace routes: view/update trading goal, check pace status."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, desc, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from packages.core.db.models import Goal, StrategistPlan, PortfolioSnapshot, DailyPerformance
from api.deps import get_db_session

router = APIRouter(prefix="/api", tags=["goal"])


class GoalUpdate(BaseModel):
    """Request body for updating the active goal."""

    starting_capital: float | None = Field(None, gt=0)
    target_capital: float | None = Field(None, gt=0)
    time_horizon_days: int | None = Field(None, gt=0)


@router.get("/goal")
async def get_goal(
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Return the currently active trading goal with progress info."""
    query = (
        select(Goal)
        .where(Goal.is_active.is_(True))
        .order_by(desc(Goal.created_at))
        .limit(1)
    )
    result = await session.execute(query)
    goal = result.scalar_one_or_none()

    if goal is None:
        return {"goal": None, "message": "No active goal set."}

    # Calculate progress
    days_elapsed = (datetime.utcnow().date() - goal.start_date).days
    days_remaining = max(goal.time_horizon_days - days_elapsed, 0)

    # Get current capital from latest snapshot
    snap_q = select(PortfolioSnapshot).order_by(desc(PortfolioSnapshot.time)).limit(1)
    snap_result = await session.execute(snap_q)
    latest_snap = snap_result.scalar_one_or_none()
    current_capital = float(latest_snap.total_capital) if latest_snap else float(goal.starting_capital)

    # Progress calculation
    total_needed = float(goal.target_capital) - float(goal.starting_capital)
    achieved = current_capital - float(goal.starting_capital)
    progress_pct = (achieved / total_needed * 100.0) if total_needed > 0 else 0.0

    # Required daily return to stay on track
    if days_remaining > 0 and current_capital > 0:
        required_daily = (float(goal.target_capital) / current_capital) ** (1.0 / days_remaining) - 1.0
    else:
        required_daily = 0.0

    return {
        "goal": {
            "id": str(goal.id),
            "starting_capital": float(goal.starting_capital),
            "target_capital": float(goal.target_capital),
            "time_horizon_days": goal.time_horizon_days,
            "start_date": str(goal.start_date),
            "is_active": goal.is_active,
            "created_at": goal.created_at.isoformat(),
        },
        "progress": {
            "current_capital": current_capital,
            "days_elapsed": days_elapsed,
            "days_remaining": days_remaining,
            "progress_pct": round(progress_pct, 2),
            "achieved_pnl": round(achieved, 2),
            "remaining_pnl": round(total_needed - achieved, 2),
            "required_daily_return_pct": round(required_daily * 100, 4),
        },
    }


@router.put("/goal")
async def update_goal(
    body: GoalUpdate,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Update the active goal, or create a new one if none is active.

    Deactivates the previous goal and creates a fresh one with the
    provided parameters. Any missing fields inherit from the old goal
    or use system defaults.
    """
    # Find current active goal
    query = (
        select(Goal)
        .where(Goal.is_active.is_(True))
        .order_by(desc(Goal.created_at))
        .limit(1)
    )
    result = await session.execute(query)
    old_goal = result.scalar_one_or_none()

    # Determine values (use provided or fall back to old goal / defaults)
    starting = body.starting_capital or (float(old_goal.starting_capital) if old_goal else 1000.0)
    target = body.target_capital or (float(old_goal.target_capital) if old_goal else 10000.0)
    horizon = body.time_horizon_days or (old_goal.time_horizon_days if old_goal else 90)

    if target <= starting:
        raise HTTPException(status_code=400, detail="target_capital must be greater than starting_capital")

    # Deactivate old goal
    if old_goal:
        old_goal.is_active = False

    # Create new goal
    new_goal = Goal(
        starting_capital=Decimal(str(starting)),
        target_capital=Decimal(str(target)),
        time_horizon_days=horizon,
        start_date=datetime.utcnow().date(),
        is_active=True,
    )
    session.add(new_goal)
    await session.flush()

    return {
        "goal": {
            "id": str(new_goal.id),
            "starting_capital": float(new_goal.starting_capital),
            "target_capital": float(new_goal.target_capital),
            "time_horizon_days": new_goal.time_horizon_days,
            "start_date": str(new_goal.start_date),
            "is_active": True,
        },
        "message": "Goal updated successfully.",
    }


@router.get("/pace")
async def get_pace(
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Return intraday pace status: actual P&L vs daily target.

    Compares today's realised P&L against the daily target from the
    latest strategist plan, broken down by trader.
    """
    today = datetime.utcnow().date()
    today_start = datetime.combine(today, datetime.min.time())

    # Get daily target from latest strategist plan
    plan_q = select(StrategistPlan).order_by(desc(StrategistPlan.created_at)).limit(1)
    plan_result = await session.execute(plan_q)
    plan = plan_result.scalar_one_or_none()
    daily_target = float(plan.daily_target) if plan else 0.0

    # Today's performance by trader
    perf_q = (
        select(DailyPerformance)
        .where(DailyPerformance.date == today)
    )
    perf_result = await session.execute(perf_q)
    perf_rows = perf_result.scalars().all()

    total_pnl_today = sum(float(p.net_pnl) for p in perf_rows)
    total_trades_today = sum(p.trades_count for p in perf_rows)

    # Time elapsed in trading day (approximate 24h cycle)
    now = datetime.utcnow()
    hours_elapsed = (now - today_start).total_seconds() / 3600.0
    time_elapsed_pct = min(hours_elapsed / 24.0, 1.0)

    # Expected P&L at this point in the day (linear interpolation)
    expected_pnl_now = daily_target * time_elapsed_pct

    # Determine pace status
    if daily_target <= 0:
        status = "no_target"
    elif total_pnl_today >= daily_target:
        status = "well_ahead"
    elif total_pnl_today >= expected_pnl_now * 0.8:
        status = "on_track"
    elif total_pnl_today >= expected_pnl_now * 0.4:
        status = "behind"
    else:
        status = "far_behind"

    return {
        "status": status,
        "daily_target_usd": daily_target,
        "pnl_today": round(total_pnl_today, 2),
        "expected_pnl_now": round(expected_pnl_now, 2),
        "progress_pct": round((total_pnl_today / daily_target * 100) if daily_target > 0 else 0, 2),
        "time_elapsed_pct": round(time_elapsed_pct * 100, 2),
        "trades_today": total_trades_today,
        "by_trader": [
            {
                "trader": p.trader,
                "net_pnl": float(p.net_pnl),
                "trades_count": p.trades_count,
                "winning_trades": p.winning_trades,
                "losing_trades": p.losing_trades,
                "inference_cost": float(p.total_inference_cost),
            }
            for p in perf_rows
        ],
    }

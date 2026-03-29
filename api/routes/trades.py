"""Trade routes: list trades with filters, get trade by ID."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, desc, and_
from sqlalchemy.ext.asyncio import AsyncSession

from packages.core.db.models import Trade
from api.deps import get_db_session

router = APIRouter(prefix="/api/trades", tags=["trades"])


def _serialize_trade(t: Trade) -> dict[str, Any]:
    """Convert a Trade ORM instance to a JSON-friendly dict."""
    return {
        "id": str(t.id),
        "trader": t.trader,
        "asset": t.asset,
        "direction": t.direction,
        "position_size_usd": float(t.position_size_usd),
        "quantity": float(t.quantity) if t.quantity else None,
        "entry_price": float(t.entry_price) if t.entry_price else None,
        "exit_price": float(t.exit_price) if t.exit_price else None,
        "stop_loss": float(t.stop_loss) if t.stop_loss else None,
        "take_profit": float(t.take_profit) if t.take_profit else None,
        "status": t.status,
        "close_reason": t.close_reason,
        "gross_pnl": float(t.gross_pnl) if t.gross_pnl else None,
        "net_pnl": float(t.net_pnl) if t.net_pnl else None,
        "exchange_fee": float(t.exchange_fee) if t.exchange_fee else None,
        "slippage": float(t.slippage) if t.slippage else None,
        "ai_confidence": float(t.ai_confidence) if t.ai_confidence else None,
        "ai_model_used": t.ai_model_used,
        "screener_cost": float(t.screener_cost) if t.screener_cost else None,
        "analyst_cost": float(t.analyst_cost) if t.analyst_cost else None,
        "total_cost": float(t.total_cost) if t.total_cost else None,
        "opened_at": t.opened_at.isoformat() if t.opened_at else None,
        "closed_at": t.closed_at.isoformat() if t.closed_at else None,
    }


@router.get("")
async def list_trades(
    trader: str | None = Query(None, description="Filter by trader name (polymarket, crypto, stocks)"),
    status: str | None = Query(None, description="Filter by status (pending, open, closed, cancelled)"),
    asset: str | None = Query(None, description="Filter by asset symbol"),
    direction: str | None = Query(None, description="Filter by direction (long, short)"),
    since_hours: int = Query(24, ge=1, le=8760, description="Return trades from the last N hours"),
    limit: int = Query(100, ge=1, le=1000, description="Max trades to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Return trades with optional filters, ordered by most recent first."""
    since = datetime.utcnow() - timedelta(hours=since_hours)

    conditions = []
    if trader:
        conditions.append(Trade.trader == trader)
    if status:
        conditions.append(Trade.status == status)
    if asset:
        conditions.append(Trade.asset.ilike(f"%{asset}%"))
    if direction:
        conditions.append(Trade.direction == direction)

    # Always filter by time window for open_at or creation
    conditions.append(
        (Trade.opened_at >= since) | (Trade.opened_at.is_(None))
    )

    query = (
        select(Trade)
        .where(and_(*conditions) if conditions else True)
        .order_by(desc(Trade.opened_at))
        .limit(limit)
        .offset(offset)
    )

    result = await session.execute(query)
    trades = result.scalars().all()

    # Total count for pagination
    count_query = (
        select(func.count())
        .select_from(Trade)
        .where(and_(*conditions) if conditions else True)
    )
    total = (await session.execute(count_query)).scalar() or 0

    return {
        "trades": [_serialize_trade(t) for t in trades],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{trade_id}")
async def get_trade(
    trade_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Return a single trade by ID, including AI decision details."""
    query = select(Trade).where(Trade.id == trade_id)
    result = await session.execute(query)
    trade = result.scalar_one_or_none()

    if trade is None:
        raise HTTPException(status_code=404, detail=f"Trade {trade_id} not found")

    data = _serialize_trade(trade)

    # Include related AI decisions (loaded via selectin relationship)
    data["ai_decisions"] = [
        {
            "id": str(d.id),
            "decision_type": d.decision_type,
            "model": d.model,
            "prompt_tokens": d.prompt_tokens,
            "completion_tokens": d.completion_tokens,
            "cost_usd": float(d.cost_usd),
            "latency_ms": d.latency_ms,
            "input_summary": d.input_summary,
            "output_raw": d.output_raw,
            "created_at": d.created_at.isoformat(),
        }
        for d in (trade.ai_decisions or [])
    ]

    # Include screener/analyst outputs if available
    data["screener_output"] = trade.screener_output
    data["analyst_output"] = trade.analyst_output

    return data

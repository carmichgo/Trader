"""Risk monitoring routes: exposure, drawdown, and correlations."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, desc, and_
from sqlalchemy.ext.asyncio import AsyncSession

from packages.core.db.models import Trade, PortfolioSnapshot, DailyPerformance
from api.deps import get_db_session

router = APIRouter(prefix="/api/risk", tags=["risk"])


@router.get("")
async def get_risk_overview(
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Return current risk metrics: exposure by market, drawdown, open position stats.

    Combines the latest portfolio snapshot with open trade analysis to
    provide a comprehensive risk dashboard view.
    """
    # Latest portfolio snapshot for drawdown info
    snap_q = select(PortfolioSnapshot).order_by(desc(PortfolioSnapshot.time)).limit(1)
    snap_result = await session.execute(snap_q)
    latest_snap = snap_result.scalar_one_or_none()

    # Open trades grouped by trader
    exposure_q = (
        select(
            Trade.trader,
            func.count().label("open_count"),
            func.sum(Trade.position_size_usd).label("total_exposure"),
            func.avg(Trade.ai_confidence).label("avg_confidence"),
        )
        .where(Trade.status == "open")
        .group_by(Trade.trader)
    )
    exposure_result = await session.execute(exposure_q)
    exposure_rows = exposure_result.all()

    # Open trades by direction
    direction_q = (
        select(
            Trade.direction,
            func.count().label("count"),
            func.sum(Trade.position_size_usd).label("exposure"),
        )
        .where(Trade.status == "open")
        .group_by(Trade.direction)
    )
    direction_result = await session.execute(direction_q)
    direction_rows = direction_result.all()

    # Largest open positions
    largest_q = (
        select(Trade)
        .where(Trade.status == "open")
        .order_by(desc(Trade.position_size_usd))
        .limit(10)
    )
    largest_result = await session.execute(largest_q)
    largest_trades = largest_result.scalars().all()

    # Recent drawdown history (last 24h of snapshots)
    since = datetime.utcnow() - timedelta(hours=24)
    drawdown_q = (
        select(
            PortfolioSnapshot.time,
            PortfolioSnapshot.drawdown_from_peak,
            PortfolioSnapshot.total_capital,
        )
        .where(PortfolioSnapshot.time >= since)
        .order_by(PortfolioSnapshot.time.asc())
    )
    drawdown_result = await session.execute(drawdown_q)
    drawdown_history = drawdown_result.all()

    total_open_exposure = sum(float(r.total_exposure or 0) for r in exposure_rows)

    return {
        "drawdown": {
            "current_pct": float(latest_snap.drawdown_from_peak) if latest_snap and latest_snap.drawdown_from_peak else 0.0,
            "total_capital": float(latest_snap.total_capital) if latest_snap else 0.0,
            "history": [
                {
                    "time": r.time.isoformat(),
                    "drawdown_pct": float(r.drawdown_from_peak) if r.drawdown_from_peak else 0.0,
                    "capital": float(r.total_capital),
                }
                for r in drawdown_history
            ],
        },
        "exposure": {
            "total_usd": total_open_exposure,
            "by_trader": [
                {
                    "trader": r.trader,
                    "open_positions": r.open_count,
                    "total_exposure_usd": float(r.total_exposure or 0),
                    "avg_confidence": float(r.avg_confidence or 0),
                }
                for r in exposure_rows
            ],
            "by_direction": [
                {
                    "direction": r.direction,
                    "count": r.count,
                    "exposure_usd": float(r.exposure or 0),
                }
                for r in direction_rows
            ],
        },
        "largest_positions": [
            {
                "id": str(t.id),
                "trader": t.trader,
                "asset": t.asset,
                "direction": t.direction,
                "size_usd": float(t.position_size_usd),
                "entry_price": float(t.entry_price) if t.entry_price else None,
                "stop_loss": float(t.stop_loss) if t.stop_loss else None,
                "opened_at": t.opened_at.isoformat() if t.opened_at else None,
            }
            for t in largest_trades
        ],
    }


@router.get("/correlations")
async def get_correlations(
    days: int = Query(30, ge=7, le=365, description="Days of history for correlation calculation"),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Return cross-asset and cross-market correlation data.

    Computes pairwise P&L correlations between assets that have been traded
    in the requested time window. Useful for assessing diversification.
    """
    since_date = (datetime.utcnow() - timedelta(days=days)).date()

    # Get daily P&L by asset from closed trades
    pnl_q = (
        select(
            func.date(Trade.closed_at).label("trade_date"),
            Trade.asset,
            Trade.trader,
            func.sum(Trade.net_pnl).label("daily_pnl"),
        )
        .where(
            and_(
                Trade.status == "closed",
                Trade.closed_at >= datetime.combine(since_date, datetime.min.time()),
                Trade.net_pnl.isnot(None),
            )
        )
        .group_by(func.date(Trade.closed_at), Trade.asset, Trade.trader)
        .order_by(func.date(Trade.closed_at))
    )
    pnl_result = await session.execute(pnl_q)
    pnl_rows = pnl_result.all()

    # Build per-asset return series
    asset_returns: dict[str, list[float]] = {}
    for row in pnl_rows:
        key = f"{row.trader}:{row.asset}"
        if key not in asset_returns:
            asset_returns[key] = []
        asset_returns[key].append(float(row.daily_pnl or 0))

    # Compute pairwise correlations (only for assets with 5+ observations)
    import math

    def pearson(xs: list[float], ys: list[float]) -> float | None:
        n = min(len(xs), len(ys))
        if n < 5:
            return None
        xs, ys = xs[:n], ys[:n]
        mx = sum(xs) / n
        my = sum(ys) / n
        cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
        sy = math.sqrt(sum((y - my) ** 2 for y in ys))
        if sx == 0 or sy == 0:
            return None
        return cov / (sx * sy)

    pairs: list[dict[str, Any]] = []
    symbols = sorted(asset_returns.keys())
    for i, sym_a in enumerate(symbols):
        for sym_b in symbols[i + 1:]:
            corr = pearson(asset_returns[sym_a], asset_returns[sym_b])
            if corr is not None:
                pairs.append({
                    "asset_a": sym_a,
                    "asset_b": sym_b,
                    "correlation": round(corr, 4),
                    "observations": min(len(asset_returns[sym_a]), len(asset_returns[sym_b])),
                })

    # Sort by absolute correlation descending (most correlated first)
    pairs.sort(key=lambda p: abs(p["correlation"]), reverse=True)

    # Cross-market correlation: daily P&L by trader
    trader_q = (
        select(
            DailyPerformance.date,
            DailyPerformance.trader,
            DailyPerformance.net_pnl,
        )
        .where(DailyPerformance.date >= since_date)
        .order_by(DailyPerformance.date)
    )
    trader_result = await session.execute(trader_q)
    trader_rows = trader_result.all()

    trader_returns: dict[str, list[float]] = {}
    for row in trader_rows:
        if row.trader not in trader_returns:
            trader_returns[row.trader] = []
        trader_returns[row.trader].append(float(row.net_pnl))

    market_pairs: list[dict[str, Any]] = []
    traders = sorted(trader_returns.keys())
    for i, t_a in enumerate(traders):
        for t_b in traders[i + 1:]:
            corr = pearson(trader_returns[t_a], trader_returns[t_b])
            if corr is not None:
                market_pairs.append({
                    "trader_a": t_a,
                    "trader_b": t_b,
                    "correlation": round(corr, 4),
                    "observations": min(len(trader_returns[t_a]), len(trader_returns[t_b])),
                })

    return {
        "days": days,
        "asset_correlations": pairs,
        "market_correlations": market_pairs,
        "assets_tracked": len(symbols),
        "traders_tracked": len(traders),
    }

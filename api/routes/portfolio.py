"""Portfolio routes: current holdings, snapshots, per-trader breakdowns."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from packages.core.db.models import PortfolioSnapshot, Trade, DailyPerformance
from api.deps import get_db_session

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("")
async def get_portfolio(
    hours: int = Query(24, ge=1, le=720, description="Hours of snapshot history"),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Return the latest portfolio snapshot and recent history.

    Includes total capital, per-market breakdown, unrealised P&L, and
    historical snapshots for the requested time window.
    """
    # Latest snapshot
    latest_q = select(PortfolioSnapshot).order_by(desc(PortfolioSnapshot.time)).limit(1)
    result = await session.execute(latest_q)
    latest = result.scalar_one_or_none()

    if latest is None:
        return {
            "current": None,
            "history": [],
            "open_trades_count": 0,
        }

    # History window
    since = datetime.utcnow() - timedelta(hours=hours)
    history_q = (
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.time >= since)
        .order_by(PortfolioSnapshot.time.asc())
    )
    history_result = await session.execute(history_q)
    snapshots = history_result.scalars().all()

    # Open trade count
    open_count_q = select(func.count()).select_from(Trade).where(Trade.status == "open")
    open_count = (await session.execute(open_count_q)).scalar() or 0

    return {
        "current": {
            "time": latest.time.isoformat(),
            "total_capital": float(latest.total_capital),
            "polymarket_capital": float(latest.polymarket_capital) if latest.polymarket_capital else None,
            "crypto_capital": float(latest.crypto_capital) if latest.crypto_capital else None,
            "stocks_capital": float(latest.stocks_capital) if latest.stocks_capital else None,
            "total_unrealized_pnl": float(latest.total_unrealized_pnl) if latest.total_unrealized_pnl else 0.0,
            "total_realized_pnl_today": float(latest.total_realized_pnl_today) if latest.total_realized_pnl_today else 0.0,
            "open_positions_count": latest.open_positions_count or 0,
            "daily_inference_cost": float(latest.daily_inference_cost) if latest.daily_inference_cost else 0.0,
            "daily_trading_fees": float(latest.daily_trading_fees) if latest.daily_trading_fees else 0.0,
            "drawdown_from_peak": float(latest.drawdown_from_peak) if latest.drawdown_from_peak else 0.0,
        },
        "history": [
            {
                "time": s.time.isoformat(),
                "total_capital": float(s.total_capital),
                "polymarket_capital": float(s.polymarket_capital) if s.polymarket_capital else None,
                "crypto_capital": float(s.crypto_capital) if s.crypto_capital else None,
                "stocks_capital": float(s.stocks_capital) if s.stocks_capital else None,
            }
            for s in snapshots
        ],
        "open_trades_count": open_count,
    }


@router.get("/{trader}")
async def get_portfolio_by_trader(
    trader: str,
    days: int = Query(7, ge=1, le=365, description="Days of daily performance history"),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Return portfolio data for a specific trader (e.g., 'polymarket', 'crypto', 'stocks').

    Includes daily performance history, open trades, and aggregate stats.
    """
    valid_traders = {"polymarket", "crypto", "stocks"}
    if trader not in valid_traders:
        raise HTTPException(status_code=404, detail=f"Unknown trader: {trader}. Must be one of {valid_traders}")

    # Daily performance
    since_date = (datetime.utcnow() - timedelta(days=days)).date()
    perf_q = (
        select(DailyPerformance)
        .where(DailyPerformance.trader == trader, DailyPerformance.date >= since_date)
        .order_by(DailyPerformance.date.asc())
    )
    perf_result = await session.execute(perf_q)
    daily_rows = perf_result.scalars().all()

    # Open trades for this trader
    open_trades_q = (
        select(Trade)
        .where(Trade.trader == trader, Trade.status == "open")
        .order_by(desc(Trade.opened_at))
    )
    open_result = await session.execute(open_trades_q)
    open_trades = open_result.scalars().all()

    # Aggregate stats
    total_pnl = sum(float(d.net_pnl) for d in daily_rows)
    total_trades = sum(d.trades_count for d in daily_rows)
    total_wins = sum(d.winning_trades for d in daily_rows)
    win_rate = (total_wins / total_trades * 100.0) if total_trades > 0 else 0.0

    return {
        "trader": trader,
        "summary": {
            "total_pnl": total_pnl,
            "total_trades": total_trades,
            "total_wins": total_wins,
            "total_losses": total_trades - total_wins,
            "win_rate_pct": round(win_rate, 2),
        },
        "daily_performance": [
            {
                "date": str(d.date),
                "trades_count": d.trades_count,
                "winning_trades": d.winning_trades,
                "losing_trades": d.losing_trades,
                "gross_pnl": float(d.gross_pnl),
                "net_pnl": float(d.net_pnl),
                "total_inference_cost": float(d.total_inference_cost),
                "total_trading_fees": float(d.total_trading_fees),
                "win_rate": float(d.win_rate) if d.win_rate else None,
                "sharpe_ratio": float(d.sharpe_ratio) if d.sharpe_ratio else None,
            }
            for d in daily_rows
        ],
        "open_trades": [
            {
                "id": str(t.id),
                "asset": t.asset,
                "direction": t.direction,
                "position_size_usd": float(t.position_size_usd),
                "entry_price": float(t.entry_price) if t.entry_price else None,
                "stop_loss": float(t.stop_loss) if t.stop_loss else None,
                "take_profit": float(t.take_profit) if t.take_profit else None,
                "opened_at": t.opened_at.isoformat() if t.opened_at else None,
            }
            for t in open_trades
        ],
    }

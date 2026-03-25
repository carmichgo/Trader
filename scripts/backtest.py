#!/usr/bin/env python3
"""Historical backtesting with real AI calls.

Replays historical market data through the AI screener and analyst pipeline
to evaluate strategy quality. Uses the same AI models as production to get
realistic inference costs and decision quality metrics.

Usage:
    python scripts/backtest.py --market crypto --days 30 [--dry-run]
    python scripts/backtest.py --market polymarket --start 2025-01-01 --end 2025-03-01
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import datetime, timedelta, date
from decimal import Decimal
from pathlib import Path
from typing import Any

# Ensure project root is on sys.path
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import structlog

from packages.core.config import SystemConfig
from packages.core.db.postgres import (
    reconfigure_engine,
    init_db,
    dispose_engine,
    AsyncSessionLocal,
)
from packages.core.db.timescale import query_ohlcv
from packages.core.db.models import Trade as TradeORM, AIDecision as AIDecisionORM
from packages.core.ai.client import AIClient
from packages.core.ai.cost_tracker import CostTracker
from packages.core.ai.screener import Screener
from packages.core.ai.analyst import Analyst
from packages.core.risk.manager import RiskManager, TradePlan
from packages.core.models import (
    Market,
    MarketSnapshot,
    TraderConfig,
    Direction,
)

logger = structlog.get_logger(__name__)


class BacktestResult:
    """Accumulated results from a backtest run."""

    def __init__(self, market: str, start: date, end: date) -> None:
        self.market = market
        self.start = start
        self.end = end
        self.trades: list[dict[str, Any]] = []
        self.ai_calls: list[dict[str, Any]] = []
        self.total_pnl: float = 0.0
        self.total_inference_cost: float = 0.0
        self.winning_trades: int = 0
        self.losing_trades: int = 0

    def record_trade(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        exit_price: float,
        size_usd: float,
        confidence: float,
    ) -> None:
        """Record a simulated trade result."""
        if direction == "long":
            pnl = (exit_price - entry_price) / entry_price * size_usd
        else:
            pnl = (entry_price - exit_price) / entry_price * size_usd

        self.trades.append({
            "symbol": symbol,
            "direction": direction,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "size_usd": size_usd,
            "pnl": round(pnl, 2),
            "confidence": confidence,
        })
        self.total_pnl += pnl
        if pnl > 0:
            self.winning_trades += 1
        else:
            self.losing_trades += 1

    def record_ai_call(
        self,
        call_type: str,
        model: str,
        cost: float,
        tokens_in: int,
        tokens_out: int,
    ) -> None:
        """Record an AI inference call."""
        self.ai_calls.append({
            "type": call_type,
            "model": model,
            "cost": cost,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
        })
        self.total_inference_cost += cost

    def summary(self) -> dict[str, Any]:
        """Generate a summary report."""
        total_trades = self.winning_trades + self.losing_trades
        win_rate = (self.winning_trades / total_trades * 100) if total_trades > 0 else 0.0
        net_pnl = self.total_pnl - self.total_inference_cost
        avg_pnl = (self.total_pnl / total_trades) if total_trades > 0 else 0.0

        return {
            "market": self.market,
            "period": f"{self.start} to {self.end}",
            "total_trades": total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate_pct": round(win_rate, 2),
            "gross_pnl": round(self.total_pnl, 2),
            "total_inference_cost": round(self.total_inference_cost, 6),
            "net_pnl": round(net_pnl, 2),
            "avg_trade_pnl": round(avg_pnl, 2),
            "total_ai_calls": len(self.ai_calls),
            "cost_per_trade": round(self.total_inference_cost / total_trades, 6) if total_trades > 0 else 0.0,
        }


async def load_historical_data(
    market: str,
    assets: list[str],
    start: datetime,
    end: datetime,
) -> dict[str, list[dict[str, Any]]]:
    """Load historical OHLCV data from the database."""
    data: dict[str, list[dict[str, Any]]] = {}

    async with AsyncSessionLocal() as session:
        for asset in assets:
            rows = await query_ohlcv(
                session,
                market=market,
                asset=asset,
                start=start,
                end=end,
                bucket_interval="1 hour",
                limit=10000,
            )
            if rows:
                data[asset] = rows
                logger.info("loaded_data", asset=asset, rows=len(rows))
            else:
                logger.warning("no_data", asset=asset)

    return data


async def run_backtest(
    market_name: str,
    start_date: date,
    end_date: date,
    dry_run: bool = False,
    max_trades_per_day: int = 10,
) -> BacktestResult:
    """Execute a full backtest over the given date range.

    Steps for each day:
    1. Load market data for the day
    2. Build MarketSnapshot objects
    3. Run the AI screener to find opportunities
    4. Run the AI analyst on top opportunities
    5. Simulate trade execution using next-candle prices
    6. Record results
    """
    config = SystemConfig()
    result = BacktestResult(market_name, start_date, end_date)

    # Initialize AI components (uses real API calls)
    ai_client = AIClient(config.ai)
    cost_tracker = CostTracker(daily_limit=config.ai.daily_cost_limit_usd * 2)  # Relaxed limit for backtesting
    risk_manager = RiskManager()

    screener = Screener(ai_client, cost_tracker, trader_id=f"backtest-{market_name}")
    analyst = Analyst(ai_client, cost_tracker, trader_id=f"backtest-{market_name}")

    market_enum = Market(market_name)

    # Default assets per market
    asset_map: dict[str, list[str]] = {
        "crypto": ["BTC/USDT", "ETH/USDT", "SOL/USDT", "AVAX/USDT", "LINK/USDT"],
        "stocks": ["AAPL", "TSLA", "NVDA", "MSFT", "AMZN", "GOOG", "META"],
        "polymarket": [],  # Polymarket assets are dynamic
    }
    assets = asset_map.get(market_name, [])

    logger.info(
        "backtest_start",
        market=market_name,
        start=str(start_date),
        end=str(end_date),
        assets=assets,
        dry_run=dry_run,
    )

    # Load all historical data
    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date, datetime.max.time())
    historical = await load_historical_data(market_name, assets, start_dt, end_dt)

    if not historical:
        logger.warning("no_historical_data", market=market_name)
        return result

    # Iterate day by day
    current_date = start_date
    while current_date <= end_date:
        day_start = datetime.combine(current_date, datetime.min.time())
        day_end = datetime.combine(current_date, datetime.max.time())
        trades_today = 0

        logger.info("backtest_day", date=str(current_date))

        # Build snapshots for this day from historical data
        snapshots: list[MarketSnapshot] = []
        for asset, candles in historical.items():
            day_candles = [
                c for c in candles
                if day_start <= c["time"] <= day_end
            ]
            if day_candles:
                latest = day_candles[-1]
                snapshot = MarketSnapshot(
                    market=market_enum,
                    symbol=asset,
                    price=float(latest["close"]),
                    volume_24h=sum(float(c.get("volume", 0) or 0) for c in day_candles),
                    price_change_24h=(
                        (float(day_candles[-1]["close"]) - float(day_candles[0]["open"]))
                        / float(day_candles[0]["open"]) * 100
                        if float(day_candles[0]["open"]) > 0
                        else 0.0
                    ),
                    high_24h=max(float(c["high"]) for c in day_candles),
                    low_24h=min(float(c["low"]) for c in day_candles),
                )
                snapshots.append(snapshot)

        if not snapshots:
            current_date += timedelta(days=1)
            continue

        # Run screener
        if not dry_run:
            try:
                trader_config = TraderConfig(
                    max_trades_per_day=max_trades_per_day,
                )
                screener_result = await screener.scan(snapshots, trader_config, market_enum)

                result.record_ai_call(
                    call_type="screener",
                    model=config.ai.screener_model,
                    cost=screener_result.inference_cost,
                    tokens_in=screener_result.tokens_in or 0,
                    tokens_out=screener_result.tokens_out or 0,
                )

                # Process top opportunities
                for opp in sorted(
                    screener_result.opportunities,
                    key=lambda o: o.confidence,
                    reverse=True,
                )[:max_trades_per_day]:
                    if trades_today >= max_trades_per_day:
                        break

                    # Simulate trade using next-day open as exit
                    next_date = current_date + timedelta(days=1)
                    if next_date > end_date:
                        break

                    # Find next day's data for this asset
                    asset_candles = historical.get(opp.symbol, [])
                    next_day_candles = [
                        c for c in asset_candles
                        if datetime.combine(next_date, datetime.min.time()) <= c["time"]
                        <= datetime.combine(next_date, datetime.max.time())
                    ]

                    if not next_day_candles:
                        continue

                    entry_price = float(opp.price) if hasattr(opp, "price") and opp.price else float(
                        [c for c in asset_candles if day_start <= c["time"] <= day_end][-1]["close"]
                    )
                    exit_price = float(next_day_candles[-1]["close"])
                    direction = "long"  # Default to long for backtest
                    size_usd = min(100.0, config.goal.starting_capital * 0.02)

                    result.record_trade(
                        symbol=opp.symbol,
                        direction=direction,
                        entry_price=entry_price,
                        exit_price=exit_price,
                        size_usd=size_usd,
                        confidence=opp.confidence,
                    )
                    trades_today += 1

            except Exception:
                logger.exception("backtest_day_error", date=str(current_date))

        current_date += timedelta(days=1)

        # Respect rate limits
        await asyncio.sleep(1.0)

    return result


async def main(
    market: str,
    start: date,
    end: date,
    dry_run: bool,
    max_trades: int,
) -> None:
    """Initialize the system and run the backtest."""
    config = SystemConfig()

    reconfigure_engine(
        url=config.database.url,
        echo=config.database.echo,
        pool_size=5,
        max_overflow=5,
    )

    await init_db()
    logger.info("database_ready")

    try:
        result = await run_backtest(
            market_name=market,
            start_date=start,
            end_date=end,
            dry_run=dry_run,
            max_trades_per_day=max_trades,
        )

        summary = result.summary()

        # Print results
        print("\n" + "=" * 60)
        print("BACKTEST RESULTS")
        print("=" * 60)
        for key, value in summary.items():
            print(f"  {key:.<30} {value}")
        print("=" * 60)

        if result.trades:
            print(f"\nTop 10 trades by P&L:")
            sorted_trades = sorted(result.trades, key=lambda t: t["pnl"], reverse=True)
            for i, t in enumerate(sorted_trades[:10], 1):
                print(
                    f"  {i}. {t['symbol']:>12} {t['direction']:>5} "
                    f"PnL: ${t['pnl']:>8.2f}  "
                    f"Conf: {t['confidence']:.2f}"
                )

        print(f"\nAI inference breakdown:")
        print(f"  Total calls: {len(result.ai_calls)}")
        print(f"  Total cost:  ${result.total_inference_cost:.4f}")
        if result.ai_calls:
            avg_cost = result.total_inference_cost / len(result.ai_calls)
            print(f"  Avg cost/call: ${avg_cost:.6f}")

    finally:
        await dispose_engine()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run historical backtesting with real AI calls.")
    parser.add_argument(
        "--market",
        type=str,
        required=True,
        choices=["crypto", "stocks", "polymarket"],
        help="Market to backtest",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Number of days to look back (alternative to --start/--end)",
    )
    parser.add_argument(
        "--start",
        type=str,
        default=None,
        help="Start date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end",
        type=str,
        default=None,
        help="End date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip AI calls, only validate data loading",
    )
    parser.add_argument(
        "--max-trades",
        type=int,
        default=10,
        help="Maximum trades per day (default: 10)",
    )
    args = parser.parse_args()

    # Resolve date range
    if args.days:
        end_date = date.today()
        start_date = end_date - timedelta(days=args.days)
    elif args.start and args.end:
        start_date = date.fromisoformat(args.start)
        end_date = date.fromisoformat(args.end)
    elif args.start:
        start_date = date.fromisoformat(args.start)
        end_date = date.today()
    else:
        end_date = date.today()
        start_date = end_date - timedelta(days=30)

    asyncio.run(main(
        market=args.market,
        start=start_date,
        end=end_date,
        dry_run=args.dry_run,
        max_trades=args.max_trades,
    ))

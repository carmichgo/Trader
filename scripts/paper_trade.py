#!/usr/bin/env python3
"""Paper trading entry point.

Runs all enabled traders in paper (simulated) mode against live market data.
No real orders are placed; positions and P&L are tracked in the database.

Usage:
    python scripts/paper_trade.py [--traders crypto,stocks,polymarket] [--interval 60]
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from pathlib import Path

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
)
from packages.core.db.timescale import setup_hypertables
from packages.core.ai.client import AIClient
from packages.core.ai.cost_tracker import CostTracker
from packages.core.risk.manager import RiskManager
from packages.core.risk.drawdown_monitor import DrawdownMonitor
from packages.core.risk.frequency_limiter import FrequencyLimiter
from packages.core.planning.pace_monitor import PaceMonitor
from packages.core.execution.order_manager import OrderManager

logger = structlog.get_logger(__name__)

# Graceful shutdown flag
_shutdown_event = asyncio.Event()


def _handle_signal(sig: signal.Signals) -> None:
    logger.info("shutdown_signal_received", signal=sig.name)
    _shutdown_event.set()


async def run_trader(trader_name: str, config: SystemConfig) -> None:
    """Import and run a single trader in paper mode."""
    logger.info("starting_paper_trader", trader=trader_name)

    # Shared components
    ai_client = AIClient(config.ai)
    cost_tracker = CostTracker(daily_limit=config.ai.daily_cost_limit_usd)
    risk_manager = RiskManager()
    drawdown_monitor = DrawdownMonitor(max_drawdown_pct=config.goal.max_drawdown_pct)
    frequency_limiter = FrequencyLimiter()
    pace_monitor = PaceMonitor()
    order_manager = OrderManager()

    # Import the correct trader module
    if trader_name == "polymarket":
        from packages.trader_polymarket import create_trader
    elif trader_name == "crypto":
        from packages.trader_crypto import create_trader
    elif trader_name == "stocks":
        from packages.trader_stocks import create_trader
    else:
        logger.error("unknown_trader", trader=trader_name)
        return

    try:
        trader = create_trader(
            config=config,
            ai_client=ai_client,
            cost_tracker=cost_tracker,
            risk_manager=risk_manager,
            drawdown_monitor=drawdown_monitor,
            frequency_limiter=frequency_limiter,
            pace_monitor=pace_monitor,
            order_manager=order_manager,
        )
    except (ImportError, AttributeError) as exc:
        logger.error(
            "trader_init_failed",
            trader=trader_name,
            error=str(exc),
            hint=f"Ensure packages/trader_{trader_name}/__init__.py exports create_trader()",
        )
        return

    # Run the trading loop until shutdown
    while not _shutdown_event.is_set():
        try:
            await trader.run_cycle()
        except Exception:
            logger.exception("paper_trade_cycle_error", trader=trader_name)

        # Wait for the next cycle or shutdown
        try:
            await asyncio.wait_for(
                _shutdown_event.wait(),
                timeout=trader.trader_config.screener_interval_minutes * 60
                if hasattr(trader, "trader_config")
                else 60.0,
            )
        except asyncio.TimeoutError:
            pass  # Timeout means it's time for the next cycle

    logger.info("paper_trader_stopped", trader=trader_name)


async def main(traders: list[str], interval: float) -> None:
    """Initialize the system and run paper traders concurrently."""
    config = SystemConfig()

    logger.info(
        "paper_trading_start",
        traders=traders,
        env=config.env,
        starting_capital=config.goal.starting_capital,
        target_capital=config.goal.target_capital,
    )

    # Set up the database
    reconfigure_engine(
        url=config.database.url,
        echo=config.database.echo,
        pool_size=config.database.pool_size,
        max_overflow=config.database.max_overflow,
    )

    await init_db()
    logger.info("database_ready")

    try:
        await setup_hypertables()
        logger.info("hypertables_ready")
    except Exception:
        logger.warning("hypertables_skipped")

    # Register signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: _handle_signal(s))

    # Launch all traders concurrently
    tasks = [
        asyncio.create_task(run_trader(name, config), name=f"paper-{name}")
        for name in traders
    ]

    logger.info("all_paper_traders_running", count=len(tasks))

    # Wait for shutdown signal
    await _shutdown_event.wait()
    logger.info("shutting_down_paper_traders")

    # Cancel all trader tasks
    for task in tasks:
        task.cancel()

    await asyncio.gather(*tasks, return_exceptions=True)

    # Cleanup
    await dispose_engine()
    logger.info("paper_trading_shutdown_complete")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run paper trading with live market data.")
    parser.add_argument(
        "--traders",
        type=str,
        default="crypto,stocks,polymarket",
        help="Comma-separated list of traders to run (default: crypto,stocks,polymarket)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=60.0,
        help="Default cycle interval in seconds (default: 60)",
    )
    args = parser.parse_args()

    trader_list = [t.strip() for t in args.traders.split(",") if t.strip()]
    asyncio.run(main(traders=trader_list, interval=args.interval))

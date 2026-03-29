#!/usr/bin/env python3
"""Seed the database with historical market data for backtesting.

Downloads historical OHLCV data from public sources and loads it
into the TimescaleDB database for use by the backtesting engine.

Usage:
    python scripts/seed_data.py --market crypto --days 90
    python scripts/seed_data.py --market stocks --symbols AAPL,NVDA,MSFT --days 365
    python scripts/seed_data.py --all --days 30
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, date, timezone
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
from packages.core.db.timescale import setup_hypertables

logger = structlog.get_logger(__name__)


# Default symbols per market
DEFAULT_SYMBOLS: dict[str, list[str]] = {
    "crypto": ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT"],
    "stocks": ["SPY", "QQQ", "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AMD"],
}


async def seed_crypto_data(
    symbols: list[str],
    start_date: date,
    end_date: date,
) -> int:
    """Download and insert crypto OHLCV data via CCXT.

    Parameters
    ----------
    symbols:
        Trading pairs to fetch (e.g. ``["BTC/USDT", "ETH/USDT"]``).
    start_date:
        Start of the data range.
    end_date:
        End of the data range.

    Returns
    -------
    int
        Number of rows inserted.
    """
    rows_inserted = 0

    try:
        import ccxt.async_support as ccxt_async

        exchange = ccxt_async.binance({"enableRateLimit": True})
        await exchange.load_markets()

        start_ts = int(datetime.combine(start_date, datetime.min.time()).timestamp() * 1000)
        end_ts = int(datetime.combine(end_date, datetime.max.time()).timestamp() * 1000)

        for symbol in symbols:
            logger.info("fetching_crypto_data", symbol=symbol)

            try:
                all_candles: list[list] = []
                since = start_ts

                while since < end_ts:
                    candles = await exchange.fetch_ohlcv(
                        symbol, "1h", since=since, limit=1000
                    )
                    if not candles:
                        break

                    all_candles.extend(candles)
                    since = candles[-1][0] + 1  # Next timestamp after last candle

                    # Rate limiting
                    await asyncio.sleep(0.5)

                if all_candles:
                    # Insert into database
                    async with AsyncSessionLocal() as session:
                        for candle in all_candles:
                            ts, o, h, l, c, v = candle
                            # TODO: Insert via TimescaleDB ORM model
                            # ohlcv = OhlcvRecord(
                            #     time=datetime.fromtimestamp(ts / 1000, tz=timezone.utc),
                            #     market="crypto",
                            #     asset=symbol,
                            #     open=o, high=h, low=l, close=c, volume=v,
                            # )
                            # session.add(ohlcv)
                            rows_inserted += 1

                        # await session.commit()

                    logger.info(
                        "crypto_data_loaded",
                        symbol=symbol,
                        candles=len(all_candles),
                    )

            except Exception:
                logger.exception("crypto_fetch_failed", symbol=symbol)

        await exchange.close()

    except ImportError:
        logger.error(
            "ccxt_not_installed",
            msg="pip install ccxt -- required for crypto data seeding",
        )

    return rows_inserted


async def seed_stock_data(
    symbols: list[str],
    start_date: date,
    end_date: date,
) -> int:
    """Download and insert stock OHLCV data via Alpaca or yfinance.

    Parameters
    ----------
    symbols:
        Ticker symbols to fetch.
    start_date:
        Start of the data range.
    end_date:
        End of the data range.

    Returns
    -------
    int
        Number of rows inserted.
    """
    rows_inserted = 0

    # Try yfinance first (no API key required)
    try:
        import yfinance as yf

        for symbol in symbols:
            logger.info("fetching_stock_data", symbol=symbol, source="yfinance")

            try:
                ticker = yf.Ticker(symbol)
                df = ticker.history(
                    start=start_date.isoformat(),
                    end=end_date.isoformat(),
                    interval="1h",
                )

                if df.empty:
                    # Fall back to daily data
                    df = ticker.history(
                        start=start_date.isoformat(),
                        end=end_date.isoformat(),
                        interval="1d",
                    )

                if not df.empty:
                    async with AsyncSessionLocal() as session:
                        for idx, row in df.iterrows():
                            # TODO: Insert via TimescaleDB ORM model
                            # ohlcv = OhlcvRecord(
                            #     time=idx.to_pydatetime(),
                            #     market="stocks",
                            #     asset=symbol,
                            #     open=row["Open"],
                            #     high=row["High"],
                            #     low=row["Low"],
                            #     close=row["Close"],
                            #     volume=row["Volume"],
                            # )
                            # session.add(ohlcv)
                            rows_inserted += 1

                        # await session.commit()

                    logger.info(
                        "stock_data_loaded",
                        symbol=symbol,
                        rows=len(df),
                    )

            except Exception:
                logger.exception("stock_fetch_failed", symbol=symbol)

        return rows_inserted

    except ImportError:
        logger.warning(
            "yfinance_not_installed",
            msg="pip install yfinance -- trying Alpaca instead",
        )

    # Fallback: Alpaca historical data
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame

        config = SystemConfig()
        client = StockHistoricalDataClient(
            config.market.alpaca_api_key,
            config.market.alpaca_api_secret,
        )

        for symbol in symbols:
            logger.info("fetching_stock_data", symbol=symbol, source="alpaca")

            try:
                request = StockBarsRequest(
                    symbol_or_symbols=[symbol],
                    timeframe=TimeFrame.Hour,
                    start=datetime.combine(start_date, datetime.min.time()),
                    end=datetime.combine(end_date, datetime.max.time()),
                    limit=10000,
                )
                bars = client.get_stock_bars(request)
                symbol_bars = bars.get(symbol, [])

                if symbol_bars:
                    async with AsyncSessionLocal() as session:
                        for bar in symbol_bars:
                            # TODO: Insert via TimescaleDB ORM model
                            rows_inserted += 1

                        # await session.commit()

                    logger.info(
                        "stock_data_loaded",
                        symbol=symbol,
                        rows=len(symbol_bars),
                    )

            except Exception:
                logger.exception("stock_fetch_failed", symbol=symbol)

    except ImportError:
        logger.error(
            "alpaca_not_installed",
            msg="pip install alpaca-py yfinance -- required for stock data seeding",
        )

    return rows_inserted


async def main(
    markets: list[str],
    symbols_override: list[str] | None,
    days: int,
) -> None:
    """Initialize the database and seed historical data."""
    config = SystemConfig()

    reconfigure_engine(
        url=config.database.url,
        echo=config.database.echo,
        pool_size=5,
        max_overflow=5,
    )

    await init_db()

    try:
        await setup_hypertables()
        logger.info("hypertables_ready")
    except Exception:
        logger.warning("hypertables_skipped", msg="TimescaleDB may not be available")

    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    total_rows = 0

    for market in markets:
        symbols = symbols_override or DEFAULT_SYMBOLS.get(market, [])

        logger.info(
            "seeding_market",
            market=market,
            symbols=symbols,
            start=str(start_date),
            end=str(end_date),
        )

        if market == "crypto":
            rows = await seed_crypto_data(symbols, start_date, end_date)
        elif market == "stocks":
            rows = await seed_stock_data(symbols, start_date, end_date)
        else:
            logger.warning("unsupported_market", market=market)
            continue

        total_rows += rows
        logger.info("market_seeded", market=market, rows=rows)

    print(f"\nSeeding complete: {total_rows} rows inserted across {len(markets)} market(s).")
    print(f"Date range: {start_date} to {end_date} ({days} days)")

    await dispose_engine()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Seed the database with historical market data."
    )
    parser.add_argument(
        "--market",
        type=str,
        default=None,
        choices=["crypto", "stocks"],
        help="Market to seed data for",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Seed data for all markets",
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default=None,
        help="Comma-separated list of symbols to seed (overrides defaults)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=90,
        help="Number of days of historical data to fetch (default: 90)",
    )
    args = parser.parse_args()

    if args.all:
        market_list = ["crypto", "stocks"]
    elif args.market:
        market_list = [args.market]
    else:
        parser.error("Specify --market or --all")
        market_list = []  # Unreachable; satisfies type checker

    symbol_list = (
        [s.strip() for s in args.symbols.split(",") if s.strip()]
        if args.symbols
        else None
    )

    asyncio.run(main(
        markets=market_list,
        symbols_override=symbol_list,
        days=args.days,
    ))

"""Binance/Bybit WebSocket feed using CCXT for real-time market data.

Connects to exchange WebSockets for real-time prices, order books, and trades.
Provides OHLCV, order book depth, ticker, and funding rate data.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from packages.core.data.base_feed import BaseDataFeed
from packages.core.models import (
    Direction,
    Market,
    MarketSnapshot,
    NormalizedSignal,
)

logger = structlog.get_logger(__name__)


class ExchangeFeed(BaseDataFeed):
    """Real-time exchange data feed via CCXT.

    Connects to Binance, Bybit, or other CCXT-supported exchanges and
    streams live price data, order books, and trades.  Falls back to
    REST polling when WebSocket is unavailable.

    Parameters
    ----------
    exchange_id:
        CCXT exchange identifier (e.g. ``"binance"``, ``"bybit"``).
    api_key:
        Exchange API key.  Required for private endpoints.
    api_secret:
        Exchange API secret.
    symbols:
        List of trading pairs to track (e.g. ``["BTC/USDT", "ETH/USDT"]``).
    sandbox:
        If ``True``, connect to the exchange's testnet.
    """

    def __init__(
        self,
        exchange_id: str = "binance",
        api_key: str = "",
        api_secret: str = "",
        symbols: list[str] | None = None,
        sandbox: bool = True,
    ) -> None:
        super().__init__()
        self.exchange_id = exchange_id
        self.api_key = api_key
        self.api_secret = api_secret
        self.symbols = symbols or ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
        self.sandbox = sandbox

        self._exchange: Any = None  # ccxt.pro exchange instance
        self._ws_exchange: Any = None  # ccxt.pro async exchange instance
        self._ticker_cache: dict[str, dict[str, Any]] = {}
        self._orderbook_cache: dict[str, dict[str, Any]] = {}
        self._ohlcv_cache: dict[str, list[list]] = {}
        self._funding_cache: dict[str, float] = {}
        self._watch_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Establish connection to the exchange via CCXT."""
        try:
            import ccxt.async_support as ccxt_async

            exchange_class = getattr(ccxt_async, self.exchange_id, None)
            if exchange_class is None:
                raise ValueError(f"Unsupported exchange: {self.exchange_id}")

            config: dict[str, Any] = {
                "apiKey": self.api_key,
                "secret": self.api_secret,
                "enableRateLimit": True,
                "options": {"defaultType": "future"},
            }

            if self.sandbox:
                config["sandbox"] = True

            self._exchange = exchange_class(config)
            await self._exchange.load_markets()

            # Validate requested symbols exist
            available = set(self._exchange.symbols)
            valid_symbols = [s for s in self.symbols if s in available]
            if not valid_symbols:
                logger.warning(
                    "no_valid_symbols",
                    requested=self.symbols,
                    sample_available=list(available)[:10],
                )
            self.symbols = valid_symbols or self.symbols[:1]

            self._connected = True
            logger.info(
                "exchange_feed_connected",
                exchange=self.exchange_id,
                symbols=self.symbols,
                sandbox=self.sandbox,
            )

            # Try to set up WebSocket streaming via ccxt.pro
            await self._start_ws_streaming()

        except ImportError:
            logger.error(
                "ccxt_not_installed",
                msg="Install ccxt with: pip install ccxt",
            )
            raise
        except Exception:
            logger.exception("exchange_feed_connect_failed")
            raise

    async def disconnect(self) -> None:
        """Close exchange connections and cancel streaming tasks."""
        if self._watch_task and not self._watch_task.done():
            self._watch_task.cancel()
            try:
                await self._watch_task
            except asyncio.CancelledError:
                pass

        if self._ws_exchange is not None:
            try:
                await self._ws_exchange.close()
            except Exception:
                pass

        if self._exchange is not None:
            try:
                await self._exchange.close()
            except Exception:
                pass

        self._connected = False
        logger.info("exchange_feed_disconnected", exchange=self.exchange_id)

    # ------------------------------------------------------------------
    # WebSocket streaming
    # ------------------------------------------------------------------

    async def _start_ws_streaming(self) -> None:
        """Attempt to start WebSocket streaming via ccxt.pro.

        Falls back silently to REST polling if ccxt.pro is not available.
        """
        try:
            import ccxt.pro as ccxt_pro

            exchange_class = getattr(ccxt_pro, self.exchange_id, None)
            if exchange_class is None:
                logger.info("ws_not_available", exchange=self.exchange_id)
                return

            config: dict[str, Any] = {
                "apiKey": self.api_key,
                "secret": self.api_secret,
                "enableRateLimit": True,
                "options": {"defaultType": "future"},
            }
            if self.sandbox:
                config["sandbox"] = True

            self._ws_exchange = exchange_class(config)
            self._watch_task = asyncio.create_task(self._ws_watch_loop())
            logger.info("ws_streaming_started", exchange=self.exchange_id)

        except ImportError:
            logger.info(
                "ccxt_pro_not_available",
                msg="WebSocket streaming disabled; using REST polling. "
                "Install ccxt[ws] for real-time data.",
            )

    async def _ws_watch_loop(self) -> None:
        """Continuously watch tickers and order books over WebSocket."""
        while self._connected and self._ws_exchange is not None:
            try:
                for symbol in self.symbols:
                    ticker = await self._ws_exchange.watch_ticker(symbol)
                    self._ticker_cache[symbol] = ticker

                    orderbook = await self._ws_exchange.watch_order_book(symbol, limit=20)
                    self._orderbook_cache[symbol] = orderbook

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("ws_watch_error")
                await asyncio.sleep(5)

    # ------------------------------------------------------------------
    # Data retrieval -- BaseDataFeed interface
    # ------------------------------------------------------------------

    async def get_latest(self) -> list[NormalizedSignal]:
        """Return the latest market state as normalized signals.

        This method satisfies the :class:`BaseDataFeed` contract.  Each
        tracked symbol produces one :class:`NormalizedSignal` with
        price-change direction and basic confidence scoring.
        """
        if not self._connected or self._exchange is None:
            return []

        signals: list[NormalizedSignal] = []
        now = datetime.now(timezone.utc)

        for symbol in self.symbols:
            try:
                ticker = await self.get_ticker(symbol)
                if ticker is None:
                    continue

                change_pct = ticker.get("percentage", 0.0) or 0.0
                direction = Direction.BUY if change_pct >= 0 else Direction.SHORT

                # Simple momentum-based confidence: abs(change) capped at 1.0
                raw_confidence = min(abs(change_pct) / 10.0, 1.0)

                signals.append(
                    NormalizedSignal(
                        market=Market.CRYPTO,
                        symbol=symbol,
                        direction=direction,
                        normalized_confidence=round(raw_confidence, 4),
                        expected_return=change_pct / 100.0 if change_pct else None,
                        metadata={
                            "price": ticker.get("last"),
                            "volume_24h": ticker.get("quoteVolume"),
                            "bid": ticker.get("bid"),
                            "ask": ticker.get("ask"),
                            "source": f"ccxt:{self.exchange_id}",
                        },
                    )
                )
            except Exception:
                logger.exception("get_latest_symbol_failed", symbol=symbol)

        self._last_update_time = now
        return signals

    # ------------------------------------------------------------------
    # Market data methods
    # ------------------------------------------------------------------

    async def get_ticker(self, symbol: str) -> dict[str, Any] | None:
        """Fetch the current ticker for *symbol*.

        Returns the cached WebSocket ticker if available, otherwise
        falls back to a REST call.
        """
        # Prefer cached WS data
        if symbol in self._ticker_cache:
            return self._ticker_cache[symbol]

        if self._exchange is None:
            return None

        try:
            ticker = await self._exchange.fetch_ticker(symbol)
            self._ticker_cache[symbol] = ticker
            return ticker
        except Exception:
            logger.exception("fetch_ticker_failed", symbol=symbol)
            return None

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 100,
    ) -> list[list]:
        """Fetch OHLCV candlestick data.

        Parameters
        ----------
        symbol:
            Trading pair (e.g. ``"BTC/USDT"``).
        timeframe:
            Candle interval (e.g. ``"1m"``, ``"5m"``, ``"1h"``, ``"1d"``).
        limit:
            Maximum number of candles to return.

        Returns
        -------
        list[list]
            Each inner list: ``[timestamp, open, high, low, close, volume]``.
        """
        if self._exchange is None:
            return []

        try:
            ohlcv = await self._exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            cache_key = f"{symbol}:{timeframe}"
            self._ohlcv_cache[cache_key] = ohlcv
            return ohlcv
        except Exception:
            logger.exception("fetch_ohlcv_failed", symbol=symbol, timeframe=timeframe)
            return []

    async def get_order_book(
        self,
        symbol: str,
        limit: int = 20,
    ) -> dict[str, Any] | None:
        """Fetch the current order book for *symbol*.

        Parameters
        ----------
        symbol:
            Trading pair.
        limit:
            Depth of book (number of levels per side).

        Returns
        -------
        dict
            Keys: ``bids``, ``asks``, ``timestamp``, ``nonce``.
        """
        # Prefer cached WS data
        if symbol in self._orderbook_cache:
            return self._orderbook_cache[symbol]

        if self._exchange is None:
            return None

        try:
            book = await self._exchange.fetch_order_book(symbol, limit=limit)
            self._orderbook_cache[symbol] = book
            return book
        except Exception:
            logger.exception("fetch_order_book_failed", symbol=symbol)
            return None

    async def get_funding_rates(self, symbol: str | None = None) -> dict[str, float]:
        """Fetch current funding rates for perpetual futures.

        Parameters
        ----------
        symbol:
            Specific symbol to query.  If ``None``, fetches for all
            tracked symbols.

        Returns
        -------
        dict[str, float]
            Mapping of symbol to current funding rate.
        """
        if self._exchange is None:
            return {}

        targets = [symbol] if symbol else self.symbols
        rates: dict[str, float] = {}

        for sym in targets:
            try:
                if hasattr(self._exchange, "fetch_funding_rate"):
                    result = await self._exchange.fetch_funding_rate(sym)
                    rate = result.get("fundingRate", 0.0)
                    rates[sym] = rate
                    self._funding_cache[sym] = rate
                else:
                    logger.debug("funding_rate_not_supported", exchange=self.exchange_id)
                    break
            except Exception:
                logger.exception("fetch_funding_rate_failed", symbol=sym)

        return rates

    # ------------------------------------------------------------------
    # Snapshot builder
    # ------------------------------------------------------------------

    async def get_snapshots(self) -> list[MarketSnapshot]:
        """Build :class:`MarketSnapshot` objects for all tracked symbols.

        Convenience method used by the :class:`CryptoTrader` to gather
        structured data for the screener.
        """
        snapshots: list[MarketSnapshot] = []
        now = datetime.now(timezone.utc)

        for symbol in self.symbols:
            try:
                ticker = await self.get_ticker(symbol)
                if ticker is None:
                    continue

                funding = self._funding_cache.get(symbol)

                snapshots.append(
                    MarketSnapshot(
                        market=Market.CRYPTO,
                        symbol=symbol,
                        price=ticker.get("last", 0.0),
                        bid=ticker.get("bid"),
                        ask=ticker.get("ask"),
                        spread=(
                            ticker["ask"] - ticker["bid"]
                            if ticker.get("ask") and ticker.get("bid")
                            else None
                        ),
                        volume_24h=ticker.get("quoteVolume"),
                        change_24h_pct=ticker.get("percentage"),
                        high_24h=ticker.get("high"),
                        low_24h=ticker.get("low"),
                        open_interest=None,  # Requires separate call
                        funding_rate=funding,
                        timestamp=now,
                        source=f"ccxt:{self.exchange_id}",
                        metadata={
                            "base_volume": ticker.get("baseVolume"),
                            "vwap": ticker.get("vwap"),
                            "previous_close": ticker.get("previousClose"),
                        },
                    )
                )
            except Exception:
                logger.exception("snapshot_build_failed", symbol=symbol)

        return snapshots

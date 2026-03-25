"""Stock market data feed via Alpaca and Polygon APIs.

Streams real-time and historical stock market data including prices,
quotes, bars, and trade data for equities and ETFs.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from packages.core.data.base_feed import BaseDataFeed
from packages.core.models import Direction, Market, MarketSnapshot, NormalizedSignal

logger = structlog.get_logger(__name__)


# TODO: Configure API keys in .env:
#   MARKET_ALPACA_API_KEY=...
#   MARKET_ALPACA_API_SECRET=...
#   POLYGON_API_KEY=...
#
# Alpaca docs: https://docs.alpaca.markets/
# Polygon docs: https://polygon.io/docs/


class MarketFeed(BaseDataFeed):
    """Stock market data feed via Alpaca / Polygon.

    Provides real-time and historical stock data including quotes,
    bars (OHLCV), and snapshot data for a universe of equities.

    Parameters
    ----------
    alpaca_api_key:
        Alpaca API key.
    alpaca_api_secret:
        Alpaca API secret.
    alpaca_base_url:
        Alpaca base URL (paper or live).
    polygon_api_key:
        Polygon.io API key for supplementary data.
    symbols:
        List of ticker symbols to track.
    use_websocket:
        If ``True``, stream data via WebSocket; otherwise poll.
    poll_interval_seconds:
        Polling interval when not using WebSocket.
    """

    def __init__(
        self,
        alpaca_api_key: str = "",
        alpaca_api_secret: str = "",
        alpaca_base_url: str = "https://paper-api.alpaca.markets",
        polygon_api_key: str = "",
        symbols: list[str] | None = None,
        use_websocket: bool = False,
        poll_interval_seconds: int = 60,
    ) -> None:
        super().__init__()
        self.alpaca_api_key = alpaca_api_key
        self.alpaca_api_secret = alpaca_api_secret
        self.alpaca_base_url = alpaca_base_url
        self.polygon_api_key = polygon_api_key
        self.symbols = symbols or [
            "SPY", "QQQ", "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA",
            "META", "TSLA", "AMD",
        ]
        self.use_websocket = use_websocket
        self.poll_interval_seconds = poll_interval_seconds

        self._alpaca_client: Any = None
        self._data_client: Any = None
        self._snapshot_cache: dict[str, dict[str, Any]] = {}
        self._bars_cache: dict[str, list[dict[str, Any]]] = {}
        self._quotes_cache: dict[str, dict[str, Any]] = {}
        self._poll_task: Optional[asyncio.Task] = None
        self._ws_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Initialize Alpaca client and start data streaming."""
        try:
            from alpaca.trading.client import TradingClient
            from alpaca.data.live import StockDataStream
            from alpaca.data.historical import StockHistoricalDataClient

            self._alpaca_client = TradingClient(
                self.alpaca_api_key,
                self.alpaca_api_secret,
                paper=("paper" in self.alpaca_base_url),
            )

            self._data_client = StockHistoricalDataClient(
                self.alpaca_api_key,
                self.alpaca_api_secret,
            )

            self._connected = True

            if self.use_websocket:
                self._ws_task = asyncio.create_task(self._start_websocket())
            else:
                self._poll_task = asyncio.create_task(self._poll_loop())

            logger.info(
                "market_feed_connected",
                symbols=self.symbols,
                mode="websocket" if self.use_websocket else "polling",
            )

        except ImportError:
            logger.warning(
                "alpaca_not_installed",
                msg="Install with: pip install alpaca-py. "
                "Feed will start in degraded mode.",
            )
            self._connected = True
            self._poll_task = asyncio.create_task(self._poll_loop())

        except Exception:
            logger.exception("market_feed_connect_failed")
            self._connected = True

    async def disconnect(self) -> None:
        """Stop streaming and clean up."""
        for task in (self._poll_task, self._ws_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self._connected = False
        logger.info("market_feed_disconnected")

    # ------------------------------------------------------------------
    # Streaming / Polling
    # ------------------------------------------------------------------

    async def _start_websocket(self) -> None:
        """Start Alpaca WebSocket streaming for real-time quotes."""
        try:
            from alpaca.data.live import StockDataStream

            stream = StockDataStream(
                self.alpaca_api_key,
                self.alpaca_api_secret,
            )

            async def on_quote(data: Any) -> None:
                symbol = data.symbol
                self._quotes_cache[symbol] = {
                    "bid": data.bid_price,
                    "ask": data.ask_price,
                    "bid_size": data.bid_size,
                    "ask_size": data.ask_size,
                    "timestamp": data.timestamp.isoformat(),
                }

            async def on_bar(data: Any) -> None:
                symbol = data.symbol
                bar = {
                    "open": data.open,
                    "high": data.high,
                    "low": data.low,
                    "close": data.close,
                    "volume": data.volume,
                    "timestamp": data.timestamp.isoformat(),
                }
                if symbol not in self._bars_cache:
                    self._bars_cache[symbol] = []
                self._bars_cache[symbol].append(bar)
                # Keep last 100 bars
                self._bars_cache[symbol] = self._bars_cache[symbol][-100:]

            stream.subscribe_quotes(on_quote, *self.symbols)
            stream.subscribe_bars(on_bar, *self.symbols)
            await stream._run_forever()  # noqa: SLF001

        except Exception:
            logger.exception("websocket_stream_error")

    async def _poll_loop(self) -> None:
        """Periodically fetch stock snapshots via REST."""
        while self._connected:
            try:
                await self._fetch_snapshots()
                await self._fetch_bars()
                self._last_update_time = datetime.now(timezone.utc)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("market_poll_error")

            await asyncio.sleep(self.poll_interval_seconds)

    async def _fetch_snapshots(self) -> None:
        """Fetch latest snapshots for all tracked symbols."""
        if self._data_client is None:
            return

        try:
            from alpaca.data.requests import StockSnapshotRequest

            request = StockSnapshotRequest(symbol_or_symbols=self.symbols)
            snapshots = self._data_client.get_stock_snapshot(request)

            for symbol, snap in snapshots.items():
                self._snapshot_cache[symbol] = {
                    "latest_trade_price": snap.latest_trade.price if snap.latest_trade else None,
                    "latest_trade_size": snap.latest_trade.size if snap.latest_trade else None,
                    "latest_quote_bid": snap.latest_quote.bid_price if snap.latest_quote else None,
                    "latest_quote_ask": snap.latest_quote.ask_price if snap.latest_quote else None,
                    "daily_bar_open": snap.daily_bar.open if snap.daily_bar else None,
                    "daily_bar_high": snap.daily_bar.high if snap.daily_bar else None,
                    "daily_bar_low": snap.daily_bar.low if snap.daily_bar else None,
                    "daily_bar_close": snap.daily_bar.close if snap.daily_bar else None,
                    "daily_bar_volume": snap.daily_bar.volume if snap.daily_bar else None,
                    "prev_daily_close": (
                        snap.previous_daily_bar.close if snap.previous_daily_bar else None
                    ),
                }

        except Exception:
            logger.exception("fetch_snapshots_failed")

    async def _fetch_bars(self) -> None:
        """Fetch historical bars for technical analysis."""
        if self._data_client is None:
            return

        try:
            from alpaca.data.requests import StockBarsRequest
            from alpaca.data.timeframe import TimeFrame

            request = StockBarsRequest(
                symbol_or_symbols=self.symbols,
                timeframe=TimeFrame.Hour,
                limit=100,
            )
            bars = self._data_client.get_stock_bars(request)

            for symbol in self.symbols:
                symbol_bars = bars.get(symbol, [])
                self._bars_cache[symbol] = [
                    {
                        "timestamp": b.timestamp.isoformat(),
                        "open": b.open,
                        "high": b.high,
                        "low": b.low,
                        "close": b.close,
                        "volume": b.volume,
                    }
                    for b in symbol_bars
                ]

        except Exception:
            logger.exception("fetch_bars_failed")

    # ------------------------------------------------------------------
    # Data retrieval -- BaseDataFeed interface
    # ------------------------------------------------------------------

    async def get_latest(self) -> list[NormalizedSignal]:
        """Return normalized signals based on current stock data."""
        signals: list[NormalizedSignal] = []

        for symbol, snap in self._snapshot_cache.items():
            price = snap.get("latest_trade_price")
            prev_close = snap.get("prev_daily_close")

            if price is None or prev_close is None or prev_close == 0:
                continue

            change_pct = (price - prev_close) / prev_close * 100
            direction = Direction.BUY if change_pct >= 0 else Direction.SHORT
            confidence = min(abs(change_pct) / 5.0, 1.0)

            signals.append(
                NormalizedSignal(
                    market=Market.STOCKS,
                    symbol=symbol,
                    direction=direction,
                    normalized_confidence=round(confidence, 4),
                    expected_return=change_pct / 100.0,
                    metadata={
                        "source": "alpaca",
                        "price": price,
                        "prev_close": prev_close,
                        "change_pct": round(change_pct, 2),
                        "bid": snap.get("latest_quote_bid"),
                        "ask": snap.get("latest_quote_ask"),
                        "volume": snap.get("daily_bar_volume"),
                    },
                )
            )

        return signals

    # ------------------------------------------------------------------
    # Snapshot builder
    # ------------------------------------------------------------------

    async def get_snapshots(self) -> list[MarketSnapshot]:
        """Build :class:`MarketSnapshot` objects for all tracked stocks."""
        snapshots: list[MarketSnapshot] = []
        now = datetime.now(timezone.utc)

        for symbol, snap in self._snapshot_cache.items():
            price = snap.get("latest_trade_price")
            if price is None:
                continue

            prev_close = snap.get("prev_daily_close", price)
            change_pct = (
                (price - prev_close) / prev_close * 100
                if prev_close and prev_close > 0
                else 0.0
            )

            bid = snap.get("latest_quote_bid")
            ask = snap.get("latest_quote_ask")

            snapshots.append(
                MarketSnapshot(
                    market=Market.STOCKS,
                    symbol=symbol,
                    price=price,
                    bid=bid,
                    ask=ask,
                    spread=(ask - bid) if (bid and ask) else None,
                    volume_24h=snap.get("daily_bar_volume"),
                    change_24h_pct=change_pct,
                    high_24h=snap.get("daily_bar_high"),
                    low_24h=snap.get("daily_bar_low"),
                    timestamp=now,
                    source="alpaca",
                    metadata={
                        "open": snap.get("daily_bar_open"),
                        "prev_close": prev_close,
                    },
                )
            )

        return snapshots

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    def get_bars(self, symbol: str) -> list[dict[str, Any]]:
        """Return cached OHLCV bars for *symbol*."""
        return self._bars_cache.get(symbol, [])

    def get_quote(self, symbol: str) -> dict[str, Any]:
        """Return latest quote data for *symbol*."""
        return self._quotes_cache.get(symbol, {})

"""Perpetual futures funding rate feed.

Tracks funding rates across exchanges for perpetual futures contracts.
Persistent positive/negative funding can signal overcrowded positioning
and provide mean-reversion opportunities.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from packages.core.data.base_feed import BaseDataFeed
from packages.core.models import Direction, Market, NormalizedSignal

logger = structlog.get_logger(__name__)


# TODO: Configure exchange API access for funding rate data:
#   - CCXT provides funding rates for most exchanges
#   - Binance: https://binance-docs.github.io/apidocs/futures/en/
#   - Bybit: https://bybit-exchange.github.io/docs/v5/market/history-fund-rate
#
# Store exchange API keys in .env:
#   MARKET_CRYPTO_API_KEY=...
#   MARKET_CRYPTO_API_SECRET=...


class FundingFeed(BaseDataFeed):
    """Perpetual futures funding rate tracker.

    Monitors funding rates across exchanges to detect:
    - High positive funding: market is overcrowded long (bearish signal)
    - High negative funding: market is overcrowded short (bullish signal)
    - Funding rate divergences between exchanges (arb opportunity)

    Parameters
    ----------
    exchange_id:
        CCXT exchange identifier (e.g. ``"binance"``, ``"bybit"``).
    api_key:
        Exchange API key.
    api_secret:
        Exchange API secret.
    symbols:
        Perpetual futures symbols to track.
    sandbox:
        If ``True``, use the exchange's testnet.
    poll_interval_seconds:
        How often to fetch funding rates.
    funding_threshold:
        Annualized funding rate threshold for generating signals.
    """

    def __init__(
        self,
        exchange_id: str = "binance",
        api_key: str = "",
        api_secret: str = "",
        symbols: list[str] | None = None,
        sandbox: bool = True,
        poll_interval_seconds: int = 300,
        funding_threshold: float = 0.0005,
    ) -> None:
        super().__init__()
        self.exchange_id = exchange_id
        self.api_key = api_key
        self.api_secret = api_secret
        self.symbols = symbols or [
            "BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT",
            "BNB/USDT:USDT", "XRP/USDT:USDT",
        ]
        self.sandbox = sandbox
        self.poll_interval_seconds = poll_interval_seconds
        self.funding_threshold = funding_threshold

        self._exchange: Any = None
        self._current_rates: dict[str, float] = {}
        self._predicted_rates: dict[str, float] = {}
        self._historical_rates: dict[str, list[dict[str, Any]]] = {}
        self._poll_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Initialize exchange connection and start polling funding rates."""
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

            self._connected = True
            self._poll_task = asyncio.create_task(self._poll_loop())

            logger.info(
                "funding_feed_connected",
                exchange=self.exchange_id,
                symbols=self.symbols,
                poll_interval=self.poll_interval_seconds,
            )

        except ImportError:
            logger.warning(
                "ccxt_not_installed",
                msg="Install with: pip install ccxt. Feed will start in degraded mode.",
            )
            self._connected = True
            self._poll_task = asyncio.create_task(self._poll_loop())

        except Exception:
            logger.exception("funding_feed_connect_failed")
            self._connected = True

    async def disconnect(self) -> None:
        """Stop polling and close exchange connection."""
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

        if self._exchange is not None:
            try:
                await self._exchange.close()
            except Exception:
                pass

        self._connected = False
        logger.info("funding_feed_disconnected")

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        """Periodically fetch funding rates from the exchange."""
        while self._connected:
            try:
                await self._fetch_funding_rates()
                await self._fetch_predicted_rates()
                self._last_update_time = datetime.now(timezone.utc)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("funding_poll_error")

            await asyncio.sleep(self.poll_interval_seconds)

    # ------------------------------------------------------------------
    # Data fetchers
    # ------------------------------------------------------------------

    async def _fetch_funding_rates(self) -> None:
        """Fetch current funding rates for all tracked symbols."""
        if self._exchange is None:
            return

        # TODO: Implement CCXT funding rate fetching
        # for symbol in self.symbols:
        #     try:
        #         if hasattr(self._exchange, "fetch_funding_rate"):
        #             result = await self._exchange.fetch_funding_rate(symbol)
        #             rate = result.get("fundingRate", 0.0)
        #             self._current_rates[symbol] = rate
        #
        #             # Store in history
        #             if symbol not in self._historical_rates:
        #                 self._historical_rates[symbol] = []
        #             self._historical_rates[symbol].append({
        #                 "rate": rate,
        #                 "timestamp": result.get("fundingTimestamp"),
        #                 "datetime": result.get("fundingDatetime"),
        #             })
        #             # Keep last 100 entries
        #             self._historical_rates[symbol] = self._historical_rates[symbol][-100:]
        #     except Exception:
        #         logger.exception("fetch_funding_rate_failed", symbol=symbol)

        logger.debug("funding_rates_fetch_skipped", reason="API not yet integrated")

    async def _fetch_predicted_rates(self) -> None:
        """Fetch predicted next-period funding rates.

        Some exchanges provide estimated next funding rates,
        which can be useful for anticipating rate changes.
        """
        if self._exchange is None:
            return

        # TODO: Implement predicted rate fetching
        # Binance provides markPrice endpoint with predicted funding rate
        # for symbol in self.symbols:
        #     try:
        #         if hasattr(self._exchange, "fetch_funding_rate"):
        #             result = await self._exchange.fetch_funding_rate(symbol)
        #             predicted = result.get("nextFundingRate")
        #             if predicted is not None:
        #                 self._predicted_rates[symbol] = predicted
        #     except Exception:
        #         logger.exception("fetch_predicted_rate_failed", symbol=symbol)

        logger.debug("predicted_rates_fetch_skipped", reason="API not yet integrated")

    # ------------------------------------------------------------------
    # Data retrieval -- BaseDataFeed interface
    # ------------------------------------------------------------------

    async def get_latest(self) -> list[NormalizedSignal]:
        """Convert funding rate data into normalized signals.

        Strategy:
        - High positive funding (longs pay shorts): bearish signal
        - High negative funding (shorts pay longs): bullish signal
        - Extreme rates suggest overcrowded positioning
        """
        signals: list[NormalizedSignal] = []

        for symbol, rate in self._current_rates.items():
            if abs(rate) < self.funding_threshold:
                continue  # Skip low-conviction signals

            # Contrarian: high positive funding -> short, high negative -> long
            if rate > self.funding_threshold:
                direction = Direction.SHORT
                # Higher rate = stronger signal, cap at 0.7
                confidence = min(rate / (self.funding_threshold * 10), 0.7)
            else:
                direction = Direction.BUY
                confidence = min(abs(rate) / (self.funding_threshold * 10), 0.7)

            # Annualized rate for context (8h periods)
            annualized = rate * 3 * 365  # 3 periods per day * 365 days

            predicted = self._predicted_rates.get(symbol)
            history = self._historical_rates.get(symbol, [])
            avg_rate = (
                sum(h["rate"] for h in history[-24:]) / len(history[-24:])
                if history
                else rate
            )

            signals.append(
                NormalizedSignal(
                    market=Market.CRYPTO,
                    symbol=symbol.replace(":USDT", ""),
                    direction=direction,
                    normalized_confidence=round(confidence, 4),
                    metadata={
                        "source": "funding_feed",
                        "current_rate": rate,
                        "predicted_rate": predicted,
                        "annualized_rate": round(annualized, 4),
                        "avg_rate_24h": round(avg_rate, 6),
                        "exchange": self.exchange_id,
                    },
                )
            )

        return signals

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    def get_funding_rate(self, symbol: str) -> float | None:
        """Return the current funding rate for *symbol*."""
        return self._current_rates.get(symbol)

    def get_all_rates(self) -> dict[str, float]:
        """Return current funding rates for all tracked symbols."""
        return dict(self._current_rates)

    def get_predicted_rate(self, symbol: str) -> float | None:
        """Return the predicted next funding rate for *symbol*."""
        return self._predicted_rates.get(symbol)

    def get_rate_history(self, symbol: str) -> list[dict[str, Any]]:
        """Return historical funding rates for *symbol*."""
        return self._historical_rates.get(symbol, [])

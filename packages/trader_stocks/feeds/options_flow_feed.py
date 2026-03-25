"""Options flow data feed: unusual activity from Unusual Whales.

Tracks unusual options activity including large block trades,
smart money flow, and options sentiment to provide leading
indicators for equity price movements.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from packages.core.data.base_feed import BaseDataFeed
from packages.core.models import Direction, Market, NormalizedSignal

logger = structlog.get_logger(__name__)


# TODO: Configure Unusual Whales API key in .env:
#   UNUSUAL_WHALES_API_KEY=...
#
# Unusual Whales API: https://docs.unusualwhales.com/
# Alternative: CBOE options data, TDAmeritrade options chain


class OptionsFlowFeed(BaseDataFeed):
    """Unusual options activity data feed.

    Monitors unusual options flow including:
    - Large block trades (institutional activity)
    - Put/call ratio extremes
    - Options volume spikes relative to open interest
    - Smart money sentiment from dark pool prints

    Parameters
    ----------
    api_key:
        API key for Unusual Whales.
    symbols:
        Equity symbols to track options flow for.
    poll_interval_seconds:
        Polling frequency for options data.
    min_premium_usd:
        Minimum premium threshold for tracking a trade.
    """

    def __init__(
        self,
        api_key: str = "",
        symbols: list[str] | None = None,
        poll_interval_seconds: int = 120,
        min_premium_usd: float = 50_000.0,
    ) -> None:
        super().__init__()
        self.api_key = api_key
        self.symbols = symbols or [
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
            "AMD", "SPY", "QQQ",
        ]
        self.poll_interval_seconds = poll_interval_seconds
        self.min_premium_usd = min_premium_usd

        self._unusual_activity: dict[str, list[dict[str, Any]]] = {}
        self._put_call_ratios: dict[str, float] = {}
        self._flow_sentiment: dict[str, dict[str, Any]] = {}
        self._dark_pool_prints: list[dict[str, Any]] = []
        self._poll_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Start the options flow polling loop."""
        if not self.api_key:
            logger.warning(
                "options_flow_no_api_key",
                msg="No Unusual Whales API key configured. "
                "Set UNUSUAL_WHALES_API_KEY in .env.",
            )

        self._connected = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info(
            "options_flow_feed_connected",
            symbols=self.symbols,
            poll_interval=self.poll_interval_seconds,
            min_premium=self.min_premium_usd,
        )

    async def disconnect(self) -> None:
        """Stop polling."""
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        self._connected = False
        logger.info("options_flow_feed_disconnected")

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        """Periodically refresh options flow data."""
        while self._connected:
            try:
                await asyncio.gather(
                    self._fetch_unusual_activity(),
                    self._fetch_put_call_ratios(),
                    self._fetch_flow_sentiment(),
                    self._fetch_dark_pool_prints(),
                    return_exceptions=True,
                )
                self._last_update_time = datetime.now(timezone.utc)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("options_flow_poll_error")

            await asyncio.sleep(self.poll_interval_seconds)

    # ------------------------------------------------------------------
    # Data fetchers
    # ------------------------------------------------------------------

    async def _fetch_unusual_activity(self) -> None:
        """Fetch unusual options trades from Unusual Whales.

        Unusual activity includes trades with:
        - Volume significantly exceeding open interest
        - Large block premiums (institutional-sized)
        - Aggressive fills (above ask or below bid)
        """
        if not self.api_key:
            return

        # TODO: Implement Unusual Whales API integration
        # import aiohttp
        # url = "https://api.unusualwhales.com/api/option-trades/flow"
        # headers = {"Authorization": f"Bearer {self.api_key}"}
        # params = {"limit": 100}
        #
        # async with aiohttp.ClientSession() as session:
        #     async with session.get(url, headers=headers, params=params) as resp:
        #         if resp.status == 200:
        #             data = await resp.json()
        #             for trade in data.get("data", []):
        #                 symbol = trade.get("ticker", "")
        #                 if symbol not in self.symbols:
        #                     continue
        #                 premium = float(trade.get("premium", 0))
        #                 if premium < self.min_premium_usd:
        #                     continue
        #
        #                 if symbol not in self._unusual_activity:
        #                     self._unusual_activity[symbol] = []
        #                 self._unusual_activity[symbol].append({
        #                     "type": trade.get("put_call", ""),
        #                     "strike": trade.get("strike_price"),
        #                     "expiry": trade.get("expiry"),
        #                     "premium": premium,
        #                     "volume": trade.get("volume"),
        #                     "open_interest": trade.get("open_interest"),
        #                     "side": trade.get("side"),  # buy/sell
        #                     "sentiment": trade.get("sentiment"),
        #                     "timestamp": trade.get("executed_at"),
        #                 })
        #                 # Keep last 50 per symbol
        #                 self._unusual_activity[symbol] = \
        #                     self._unusual_activity[symbol][-50:]

        logger.debug("unusual_activity_fetch_skipped", reason="API not yet integrated")

    async def _fetch_put_call_ratios(self) -> None:
        """Fetch put/call ratios for tracked symbols.

        Extreme P/C ratios can signal sentiment shifts:
        - Very high P/C (>1.5): excessive fear, contrarian bullish
        - Very low P/C (<0.5): excessive greed, contrarian bearish
        """
        if not self.api_key:
            return

        # TODO: Implement put/call ratio endpoint
        # for symbol in self.symbols:
        #     url = f"https://api.unusualwhales.com/api/stock/{symbol}/options-volume"
        #     headers = {"Authorization": f"Bearer {self.api_key}"}
        #     async with aiohttp.ClientSession() as session:
        #         async with session.get(url, headers=headers) as resp:
        #             if resp.status == 200:
        #                 data = await resp.json()
        #                 call_vol = data.get("call_volume", 0)
        #                 put_vol = data.get("put_volume", 0)
        #                 if call_vol > 0:
        #                     self._put_call_ratios[symbol] = put_vol / call_vol

        logger.debug("put_call_ratios_fetch_skipped", reason="API not yet integrated")

    async def _fetch_flow_sentiment(self) -> None:
        """Compute net options flow sentiment per symbol.

        Aggregates bullish vs bearish premium to determine
        the institutional flow direction.
        """
        # TODO: Compute from unusual activity data
        # for symbol, trades in self._unusual_activity.items():
        #     bullish_premium = sum(
        #         t["premium"] for t in trades
        #         if t.get("sentiment") == "bullish"
        #     )
        #     bearish_premium = sum(
        #         t["premium"] for t in trades
        #         if t.get("sentiment") == "bearish"
        #     )
        #     total = bullish_premium + bearish_premium
        #     if total > 0:
        #         self._flow_sentiment[symbol] = {
        #             "bullish_premium": bullish_premium,
        #             "bearish_premium": bearish_premium,
        #             "net_sentiment": (bullish_premium - bearish_premium) / total,
        #             "total_premium": total,
        #         }

        logger.debug("flow_sentiment_compute_skipped", reason="Not yet implemented")

    async def _fetch_dark_pool_prints(self) -> None:
        """Fetch dark pool trade prints.

        Large dark pool trades can signal institutional accumulation
        or distribution before public price moves.
        """
        if not self.api_key:
            return

        # TODO: Implement dark pool data endpoint
        # url = "https://api.unusualwhales.com/api/darkpool/recent"
        # headers = {"Authorization": f"Bearer {self.api_key}"}
        # async with aiohttp.ClientSession() as session:
        #     async with session.get(url, headers=headers) as resp:
        #         if resp.status == 200:
        #             data = await resp.json()
        #             self._dark_pool_prints = [
        #                 {
        #                     "symbol": t.get("ticker"),
        #                     "price": t.get("price"),
        #                     "size": t.get("size"),
        #                     "notional": t.get("notional_value"),
        #                     "timestamp": t.get("executed_at"),
        #                 }
        #                 for t in data.get("data", [])
        #                 if t.get("ticker") in self.symbols
        #             ]

        logger.debug("dark_pool_fetch_skipped", reason="API not yet integrated")

    # ------------------------------------------------------------------
    # Data retrieval -- BaseDataFeed interface
    # ------------------------------------------------------------------

    async def get_latest(self) -> list[NormalizedSignal]:
        """Convert options flow data into normalized signals.

        Generates signals from:
        1. Net options flow sentiment (institutional direction)
        2. Extreme put/call ratios (contrarian)
        3. Unusual activity volume (conviction)
        """
        signals: list[NormalizedSignal] = []

        for symbol in self.symbols:
            # Flow sentiment signal
            sentiment = self._flow_sentiment.get(symbol, {})
            net_sent = sentiment.get("net_sentiment")
            if net_sent is not None and abs(net_sent) > 0.2:
                direction = Direction.BUY if net_sent > 0 else Direction.SHORT
                confidence = min(abs(net_sent) * 0.5, 0.6)

                signals.append(
                    NormalizedSignal(
                        market=Market.STOCKS,
                        symbol=symbol,
                        direction=direction,
                        normalized_confidence=round(confidence, 4),
                        metadata={
                            "source": "options_flow",
                            "signal_type": "flow_sentiment",
                            "net_sentiment": round(net_sent, 4),
                            "bullish_premium": sentiment.get("bullish_premium"),
                            "bearish_premium": sentiment.get("bearish_premium"),
                        },
                    )
                )

            # Put/call ratio contrarian signal
            pc_ratio = self._put_call_ratios.get(symbol)
            if pc_ratio is not None:
                if pc_ratio > 1.5:
                    # Extreme fear -> contrarian bullish
                    signals.append(
                        NormalizedSignal(
                            market=Market.STOCKS,
                            symbol=symbol,
                            direction=Direction.BUY,
                            normalized_confidence=min((pc_ratio - 1.5) / 2.0, 0.5),
                            metadata={
                                "source": "options_flow",
                                "signal_type": "high_put_call",
                                "put_call_ratio": round(pc_ratio, 3),
                            },
                        )
                    )
                elif pc_ratio < 0.5:
                    # Extreme greed -> contrarian bearish
                    signals.append(
                        NormalizedSignal(
                            market=Market.STOCKS,
                            symbol=symbol,
                            direction=Direction.SHORT,
                            normalized_confidence=min((0.5 - pc_ratio) / 0.5, 0.4),
                            metadata={
                                "source": "options_flow",
                                "signal_type": "low_put_call",
                                "put_call_ratio": round(pc_ratio, 3),
                            },
                        )
                    )

        return signals

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    def get_unusual_activity(self, symbol: str) -> list[dict[str, Any]]:
        """Return unusual options trades for *symbol*."""
        return self._unusual_activity.get(symbol, [])

    def get_put_call_ratio(self, symbol: str) -> float | None:
        """Return the current put/call ratio for *symbol*."""
        return self._put_call_ratios.get(symbol)

    def get_flow_sentiment(self, symbol: str) -> dict[str, Any]:
        """Return net options flow sentiment for *symbol*."""
        return self._flow_sentiment.get(symbol, {})

    def get_dark_pool_prints(self, symbol: str | None = None) -> list[dict[str, Any]]:
        """Return recent dark pool prints, optionally filtered by *symbol*."""
        if symbol is None:
            return list(self._dark_pool_prints)
        return [p for p in self._dark_pool_prints if p.get("symbol") == symbol]

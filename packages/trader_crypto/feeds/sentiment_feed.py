"""Crypto sentiment data feed: Fear & Greed index, social sentiment, news tone.

Aggregates sentiment signals from multiple sources to provide a market
mood indicator that complements technical and on-chain data.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from packages.core.data.base_feed import BaseDataFeed
from packages.core.models import Direction, Market, NormalizedSignal

logger = structlog.get_logger(__name__)


# TODO: Configure API keys for sentiment providers:
#   - Alternative.me Fear & Greed (free): https://alternative.me/crypto/fear-and-greed-index/
#   - LunarCrush (social): https://lunarcrush.com/developers/docs
#   - Santiment: https://api.santiment.net/
#
# Store keys in .env:
#   LUNARCRUSH_API_KEY=...
#   SANTIMENT_API_KEY=...


class SentimentFeed(BaseDataFeed):
    """Aggregated crypto sentiment data feed.

    Combines multiple sentiment sources into a unified view:
    - Fear & Greed Index (market-wide)
    - Social media sentiment (per-asset via LunarCrush)
    - On-chain sentiment (via Santiment)

    Parameters
    ----------
    lunarcrush_api_key:
        API key for LunarCrush social metrics.
    santiment_api_key:
        API key for Santiment on-chain social data.
    symbols:
        Assets to track sentiment for.
    poll_interval_seconds:
        Polling frequency (sentiment data is typically slow-moving).
    """

    def __init__(
        self,
        lunarcrush_api_key: str = "",
        santiment_api_key: str = "",
        symbols: list[str] | None = None,
        poll_interval_seconds: int = 600,
    ) -> None:
        super().__init__()
        self.lunarcrush_api_key = lunarcrush_api_key
        self.santiment_api_key = santiment_api_key
        self.symbols = symbols or ["BTC", "ETH", "SOL"]
        self.poll_interval_seconds = poll_interval_seconds

        self._fear_greed_index: Optional[int] = None
        self._fear_greed_label: Optional[str] = None
        self._social_sentiment: dict[str, dict[str, Any]] = {}
        self._news_sentiment: dict[str, float] = {}
        self._poll_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Start the sentiment polling loop."""
        self._connected = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info(
            "sentiment_feed_connected",
            symbols=self.symbols,
            poll_interval=self.poll_interval_seconds,
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
        logger.info("sentiment_feed_disconnected")

    # ------------------------------------------------------------------
    # Polling loop
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        """Periodically refresh sentiment data from all sources."""
        while self._connected:
            try:
                await asyncio.gather(
                    self._fetch_fear_greed_index(),
                    self._fetch_social_sentiment(),
                    self._fetch_news_sentiment(),
                    return_exceptions=True,
                )
                self._last_update_time = datetime.now(timezone.utc)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("sentiment_poll_error")

            await asyncio.sleep(self.poll_interval_seconds)

    # ------------------------------------------------------------------
    # Data fetchers
    # ------------------------------------------------------------------

    async def _fetch_fear_greed_index(self) -> None:
        """Fetch the Crypto Fear & Greed Index from Alternative.me.

        This is a free API that provides a 0-100 index:
        - 0-24: Extreme Fear
        - 25-49: Fear
        - 50-74: Greed
        - 75-100: Extreme Greed
        """
        try:
            import aiohttp

            url = "https://api.alternative.me/fng/?limit=1&format=json"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("data"):
                            entry = data["data"][0]
                            self._fear_greed_index = int(entry["value"])
                            self._fear_greed_label = entry["value_classification"]
                            logger.debug(
                                "fear_greed_updated",
                                value=self._fear_greed_index,
                                label=self._fear_greed_label,
                            )
                    else:
                        logger.warning("fear_greed_http_error", status=resp.status)
        except ImportError:
            logger.debug("aiohttp_not_installed", msg="pip install aiohttp for sentiment feed")
        except Exception:
            logger.exception("fear_greed_fetch_failed")

    async def _fetch_social_sentiment(self) -> None:
        """Fetch social sentiment metrics from LunarCrush.

        Tracks social volume, bullish/bearish ratio, and galaxy score
        for each monitored asset.
        """
        if not self.lunarcrush_api_key:
            return

        # TODO: Implement LunarCrush API integration
        # Endpoint: https://lunarcrush.com/api4/public/coins/{symbol}/v1
        # Headers: {"Authorization": f"Bearer {self.lunarcrush_api_key}"}
        #
        # Parse into:
        # self._social_sentiment[symbol] = {
        #     "galaxy_score": 72.5,        # 0-100 overall score
        #     "alt_rank": 5,               # rank among alts
        #     "social_volume_24h": 15000,   # social mentions
        #     "social_score": 85,           # social engagement
        #     "bullish_pct": 0.65,          # % bullish posts
        #     "bearish_pct": 0.20,          # % bearish posts
        #     "neutral_pct": 0.15,          # % neutral posts
        #     "sentiment_score": 3.8,       # -5 to 5
        # }

        logger.debug("social_sentiment_fetch_skipped", reason="API not yet integrated")

    async def _fetch_news_sentiment(self) -> None:
        """Fetch aggregated news sentiment scores.

        Analyzes recent crypto news headlines for overall tone.
        """
        # TODO: Integrate news sentiment API (e.g. CryptoPanic, Santiment)
        # CryptoPanic: https://cryptopanic.com/developers/api/
        # Santiment: https://api.santiment.net/graphiql
        #
        # Aggregate headline sentiment into a -1.0 to 1.0 score per asset.

        logger.debug("news_sentiment_fetch_skipped", reason="API not yet integrated")

    # ------------------------------------------------------------------
    # Data retrieval -- BaseDataFeed interface
    # ------------------------------------------------------------------

    async def get_latest(self) -> list[NormalizedSignal]:
        """Convert sentiment data into normalized directional signals.

        Uses a contrarian approach: extreme fear is mildly bullish,
        extreme greed is mildly bearish (mean-reversion tendency).
        """
        signals: list[NormalizedSignal] = []

        if self._fear_greed_index is None:
            return signals

        # Market-wide signal based on Fear & Greed Index
        fgi = self._fear_greed_index

        # Contrarian signal: extreme fear -> buy, extreme greed -> sell
        if fgi <= 20:
            direction = Direction.BUY
            confidence = 0.6 + (20 - fgi) / 100.0  # 0.60-0.80
        elif fgi <= 35:
            direction = Direction.BUY
            confidence = 0.4 + (35 - fgi) / 75.0  # 0.40-0.60
        elif fgi >= 80:
            direction = Direction.SHORT
            confidence = 0.5 + (fgi - 80) / 40.0  # 0.50-1.00, capped
            confidence = min(confidence, 0.80)
        elif fgi >= 65:
            direction = Direction.SHORT
            confidence = 0.3 + (fgi - 65) / 50.0  # 0.30-0.60
        else:
            # Neutral zone (35-65): very low confidence signal
            direction = Direction.BUY
            confidence = 0.15

        for symbol in self.symbols:
            social = self._social_sentiment.get(symbol, {})

            # Adjust confidence with social sentiment if available
            adjusted_confidence = confidence
            if social.get("sentiment_score") is not None:
                social_score = social["sentiment_score"]
                # Blend: 70% fear/greed, 30% social
                social_conf = min(max(abs(social_score) / 5.0, 0.0), 1.0)
                adjusted_confidence = confidence * 0.7 + social_conf * 0.3

            signals.append(
                NormalizedSignal(
                    market=Market.CRYPTO,
                    symbol=f"{symbol}/USDT",
                    direction=direction,
                    normalized_confidence=round(min(adjusted_confidence, 1.0), 4),
                    metadata={
                        "source": "sentiment",
                        "fear_greed_index": fgi,
                        "fear_greed_label": self._fear_greed_label,
                        "social_sentiment": social,
                        "news_sentiment": self._news_sentiment.get(symbol),
                    },
                )
            )

        return signals

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    @property
    def fear_greed_index(self) -> Optional[int]:
        """Current Fear & Greed Index value (0-100)."""
        return self._fear_greed_index

    @property
    def fear_greed_label(self) -> Optional[str]:
        """Human-readable label for the current Fear & Greed value."""
        return self._fear_greed_label

    def get_social_sentiment(self, symbol: str) -> dict[str, Any]:
        """Return cached social sentiment data for *symbol*."""
        return self._social_sentiment.get(symbol, {})

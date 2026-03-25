"""Analyst ratings and consensus data feed.

Tracks Wall Street analyst ratings, price targets, and consensus
estimates to provide fundamental sentiment signals for equities.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from packages.core.data.base_feed import BaseDataFeed
from packages.core.models import Direction, Market, NormalizedSignal

logger = structlog.get_logger(__name__)


# TODO: Configure API keys for analyst data in .env:
#   FINANCIAL_MODELING_KEY=...    # https://financialmodelingprep.com/
#   ALPHA_VANTAGE_API_KEY=...    # https://www.alphavantage.co/
#
# Analyst data can also be sourced from:
#   - Polygon.io: https://polygon.io/docs/stocks/get_v3_reference_tickers__stocksticker__financials
#   - TipRanks API (unofficial)


class AnalystFeed(BaseDataFeed):
    """Wall Street analyst ratings and consensus feed.

    Tracks analyst consensus including:
    - Buy/Hold/Sell ratings distribution
    - Average and median price targets
    - Recent rating changes (upgrades/downgrades)
    - EPS estimate revisions

    Parameters
    ----------
    fmp_key:
        API key for Financial Modeling Prep.
    alpha_vantage_key:
        API key for Alpha Vantage.
    symbols:
        Equity symbols to track analyst coverage for.
    poll_interval_seconds:
        Polling frequency (analyst data changes infrequently).
    """

    def __init__(
        self,
        fmp_key: str = "",
        alpha_vantage_key: str = "",
        symbols: list[str] | None = None,
        poll_interval_seconds: int = 3600,
    ) -> None:
        super().__init__()
        self.fmp_key = fmp_key
        self.alpha_vantage_key = alpha_vantage_key
        self.symbols = symbols or [
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
            "AMD", "CRM", "NFLX",
        ]
        self.poll_interval_seconds = poll_interval_seconds

        self._consensus_cache: dict[str, dict[str, Any]] = {}
        self._price_targets: dict[str, dict[str, Any]] = {}
        self._recent_changes: list[dict[str, Any]] = []
        self._eps_revisions: dict[str, dict[str, Any]] = {}
        self._poll_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Start the analyst data polling loop."""
        if not self.fmp_key and not self.alpha_vantage_key:
            logger.warning(
                "analyst_feed_no_api_keys",
                msg="No analyst data API keys configured. "
                "Set FINANCIAL_MODELING_KEY or ALPHA_VANTAGE_API_KEY in .env.",
            )

        self._connected = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info(
            "analyst_feed_connected",
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
        logger.info("analyst_feed_disconnected")

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        """Periodically refresh analyst data."""
        while self._connected:
            try:
                await asyncio.gather(
                    self._fetch_consensus_ratings(),
                    self._fetch_price_targets(),
                    self._fetch_rating_changes(),
                    self._fetch_eps_revisions(),
                    return_exceptions=True,
                )
                self._last_update_time = datetime.now(timezone.utc)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("analyst_poll_error")

            await asyncio.sleep(self.poll_interval_seconds)

    # ------------------------------------------------------------------
    # Data fetchers
    # ------------------------------------------------------------------

    async def _fetch_consensus_ratings(self) -> None:
        """Fetch analyst consensus ratings (Buy/Hold/Sell distribution).

        The consensus distribution helps gauge institutional sentiment
        and identifies potential crowded positions.
        """
        if not self.fmp_key:
            return

        # TODO: Implement Financial Modeling Prep analyst endpoint
        # import aiohttp
        # for symbol in self.symbols:
        #     url = f"https://financialmodelingprep.com/api/v3/analyst-stock-recommendations/{symbol}"
        #     params = {"apikey": self.fmp_key}
        #     async with aiohttp.ClientSession() as session:
        #         async with session.get(url, params=params) as resp:
        #             if resp.status == 200:
        #                 data = await resp.json()
        #                 if data:
        #                     latest = data[0]
        #                     strong_buy = latest.get("analystRatingsStrongBuy", 0)
        #                     buy = latest.get("analystRatingsbuy", 0)
        #                     hold = latest.get("analystRatingsHold", 0)
        #                     sell = latest.get("analystRatingsSell", 0)
        #                     strong_sell = latest.get("analystRatingsStrongSell", 0)
        #                     total = strong_buy + buy + hold + sell + strong_sell
        #
        #                     self._consensus_cache[symbol] = {
        #                         "strong_buy": strong_buy,
        #                         "buy": buy,
        #                         "hold": hold,
        #                         "sell": sell,
        #                         "strong_sell": strong_sell,
        #                         "total_analysts": total,
        #                         "bullish_pct": (strong_buy + buy) / total if total else 0,
        #                         "bearish_pct": (sell + strong_sell) / total if total else 0,
        #                         "date": latest.get("date"),
        #                     }

        logger.debug("consensus_ratings_fetch_skipped", reason="API not yet integrated")

    async def _fetch_price_targets(self) -> None:
        """Fetch analyst consensus price targets.

        Price targets provide an upside/downside reference point.
        A stock trading well below consensus target may be undervalued.
        """
        if not self.fmp_key:
            return

        # TODO: Implement price target endpoint
        # import aiohttp
        # for symbol in self.symbols:
        #     url = f"https://financialmodelingprep.com/api/v4/price-target-consensus"
        #     params = {"symbol": symbol, "apikey": self.fmp_key}
        #     async with aiohttp.ClientSession() as session:
        #         async with session.get(url, params=params) as resp:
        #             if resp.status == 200:
        #                 data = await resp.json()
        #                 if data:
        #                     target = data[0]
        #                     self._price_targets[symbol] = {
        #                         "target_high": target.get("targetHigh"),
        #                         "target_low": target.get("targetLow"),
        #                         "target_consensus": target.get("targetConsensus"),
        #                         "target_median": target.get("targetMedian"),
        #                     }

        logger.debug("price_targets_fetch_skipped", reason="API not yet integrated")

    async def _fetch_rating_changes(self) -> None:
        """Fetch recent analyst rating changes (upgrades/downgrades).

        Recent changes are more impactful than stale ratings, as
        they reflect new information or revised outlook.
        """
        if not self.fmp_key:
            return

        # TODO: Implement rating changes endpoint
        # import aiohttp
        # url = "https://financialmodelingprep.com/api/v3/upgrades-downgrades-consensus"
        # params = {"apikey": self.fmp_key}
        # async with aiohttp.ClientSession() as session:
        #     async with session.get(url, params=params) as resp:
        #         if resp.status == 200:
        #             data = await resp.json()
        #             self._recent_changes = [
        #                 {
        #                     "symbol": c.get("symbol"),
        #                     "published_date": c.get("publishedDate"),
        #                     "firm": c.get("gradingCompany"),
        #                     "action": c.get("action"),  # upgrade/downgrade/init
        #                     "new_grade": c.get("newGrade"),
        #                     "previous_grade": c.get("previousGrade"),
        #                 }
        #                 for c in data
        #                 if c.get("symbol") in self.symbols
        #             ][:50]

        logger.debug("rating_changes_fetch_skipped", reason="API not yet integrated")

    async def _fetch_eps_revisions(self) -> None:
        """Fetch EPS estimate revisions.

        Upward EPS revisions are bullish; downward revisions
        are bearish. The trend of revisions matters more than
        absolute estimates.
        """
        if not self.fmp_key:
            return

        # TODO: Implement EPS estimate endpoint
        # import aiohttp
        # for symbol in self.symbols:
        #     url = f"https://financialmodelingprep.com/api/v3/analyst-estimates/{symbol}"
        #     params = {"period": "quarter", "limit": 4, "apikey": self.fmp_key}
        #     async with aiohttp.ClientSession() as session:
        #         async with session.get(url, params=params) as resp:
        #             if resp.status == 200:
        #                 data = await resp.json()
        #                 if data:
        #                     latest = data[0]
        #                     self._eps_revisions[symbol] = {
        #                         "estimated_eps": latest.get("estimatedEpsAvg"),
        #                         "eps_high": latest.get("estimatedEpsHigh"),
        #                         "eps_low": latest.get("estimatedEpsLow"),
        #                         "estimated_revenue": latest.get("estimatedRevenueAvg"),
        #                         "num_analysts": latest.get("numberAnalystEstimatedEps"),
        #                         "date": latest.get("date"),
        #                     }

        logger.debug("eps_revisions_fetch_skipped", reason="API not yet integrated")

    # ------------------------------------------------------------------
    # Data retrieval -- BaseDataFeed interface
    # ------------------------------------------------------------------

    async def get_latest(self) -> list[NormalizedSignal]:
        """Convert analyst data into normalized signals.

        Generates signals from:
        1. Strong consensus bias (>70% bullish or bearish)
        2. Price target upside/downside
        3. Recent upgrades/downgrades
        """
        signals: list[NormalizedSignal] = []

        for symbol in self.symbols:
            consensus = self._consensus_cache.get(symbol, {})
            price_target = self._price_targets.get(symbol, {})

            # Consensus signal: strong bullish or bearish skew
            bullish_pct = consensus.get("bullish_pct", 0)
            bearish_pct = consensus.get("bearish_pct", 0)

            if bullish_pct > 0.7:
                signals.append(
                    NormalizedSignal(
                        market=Market.STOCKS,
                        symbol=symbol,
                        direction=Direction.BUY,
                        normalized_confidence=round(min(bullish_pct * 0.5, 0.5), 4),
                        metadata={
                            "source": "analyst_feed",
                            "signal_type": "consensus_bullish",
                            "bullish_pct": round(bullish_pct, 3),
                            "total_analysts": consensus.get("total_analysts"),
                        },
                    )
                )
            elif bearish_pct > 0.4:
                signals.append(
                    NormalizedSignal(
                        market=Market.STOCKS,
                        symbol=symbol,
                        direction=Direction.SHORT,
                        normalized_confidence=round(min(bearish_pct * 0.4, 0.4), 4),
                        metadata={
                            "source": "analyst_feed",
                            "signal_type": "consensus_bearish",
                            "bearish_pct": round(bearish_pct, 3),
                            "total_analysts": consensus.get("total_analysts"),
                        },
                    )
                )

            # Price target signal: significant upside or downside
            target_consensus = price_target.get("target_consensus")
            if target_consensus and target_consensus > 0:
                # Note: actual current price needed for upside calc
                # This will be enriched when combined with market feed data
                signals.append(
                    NormalizedSignal(
                        market=Market.STOCKS,
                        symbol=symbol,
                        direction=Direction.BUY,
                        normalized_confidence=0.2,  # Low base confidence
                        metadata={
                            "source": "analyst_feed",
                            "signal_type": "price_target",
                            "target_consensus": target_consensus,
                            "target_high": price_target.get("target_high"),
                            "target_low": price_target.get("target_low"),
                        },
                    )
                )

        # Recent rating changes generate higher-priority signals
        for change in self._recent_changes[:10]:
            symbol = change.get("symbol", "")
            action = change.get("action", "")

            if action == "upgrade":
                direction = Direction.BUY
                confidence = 0.35
            elif action == "downgrade":
                direction = Direction.SHORT
                confidence = 0.30
            else:
                continue

            signals.append(
                NormalizedSignal(
                    market=Market.STOCKS,
                    symbol=symbol,
                    direction=direction,
                    normalized_confidence=confidence,
                    metadata={
                        "source": "analyst_feed",
                        "signal_type": "rating_change",
                        "action": action,
                        "firm": change.get("firm"),
                        "new_grade": change.get("new_grade"),
                        "previous_grade": change.get("previous_grade"),
                    },
                )
            )

        return signals

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    def get_consensus(self, symbol: str) -> dict[str, Any]:
        """Return cached consensus ratings for *symbol*."""
        return self._consensus_cache.get(symbol, {})

    def get_price_target(self, symbol: str) -> dict[str, Any]:
        """Return cached price target data for *symbol*."""
        return self._price_targets.get(symbol, {})

    def get_recent_changes(self, symbol: str | None = None) -> list[dict[str, Any]]:
        """Return recent rating changes, optionally filtered by *symbol*."""
        if symbol is None:
            return list(self._recent_changes)
        return [c for c in self._recent_changes if c.get("symbol") == symbol]

    def get_eps_estimates(self, symbol: str) -> dict[str, Any]:
        """Return cached EPS estimate data for *symbol*."""
        return self._eps_revisions.get(symbol, {})

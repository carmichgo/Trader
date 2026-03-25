"""Cross-reference feed for prediction market comparison.

Compares prices across Polymarket, PredictIt, Metaculus, and other
prediction market platforms to identify arbitrage opportunities and
consensus divergences.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from packages.core.data.base_feed import BaseDataFeed
from packages.core.models import Direction, Market, NormalizedSignal

logger = structlog.get_logger(__name__)


# TODO: Configure API access for prediction market platforms:
#   - PredictIt: https://www.predictit.org/api/marketdata/all/
#   - Metaculus: https://www.metaculus.com/api/
#   - Manifold: https://docs.manifold.markets/api
#
# PredictIt is free; Metaculus and Manifold have public APIs.
# No API keys required for read-only public data.


class CrossReferenceFeed(BaseDataFeed):
    """Cross-platform prediction market comparison feed.

    Compares event probabilities across multiple prediction
    platforms to identify:
    - Price discrepancies (potential arbitrage)
    - Consensus divergences (one platform disagrees)
    - Information advantages (one platform moves first)

    Parameters
    ----------
    enable_predictit:
        Whether to fetch PredictIt data.
    enable_metaculus:
        Whether to fetch Metaculus community predictions.
    enable_manifold:
        Whether to fetch Manifold Markets data.
    poll_interval_seconds:
        Polling frequency for cross-platform data.
    min_divergence_pct:
        Minimum price divergence (in percentage points) to
        generate a signal.
    """

    def __init__(
        self,
        enable_predictit: bool = True,
        enable_metaculus: bool = True,
        enable_manifold: bool = True,
        poll_interval_seconds: int = 300,
        min_divergence_pct: float = 5.0,
    ) -> None:
        super().__init__()
        self.enable_predictit = enable_predictit
        self.enable_metaculus = enable_metaculus
        self.enable_manifold = enable_manifold
        self.poll_interval_seconds = poll_interval_seconds
        self.min_divergence_pct = min_divergence_pct

        self._predictit_markets: dict[str, dict[str, Any]] = {}
        self._metaculus_questions: dict[str, dict[str, Any]] = {}
        self._manifold_markets: dict[str, dict[str, Any]] = {}
        self._divergences: list[dict[str, Any]] = []
        self._poll_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Start the cross-reference polling loop."""
        self._connected = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info(
            "cross_reference_feed_connected",
            predictit=self.enable_predictit,
            metaculus=self.enable_metaculus,
            manifold=self.enable_manifold,
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
        logger.info("cross_reference_feed_disconnected")

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        """Periodically refresh cross-platform data."""
        while self._connected:
            try:
                tasks = []
                if self.enable_predictit:
                    tasks.append(self._fetch_predictit())
                if self.enable_metaculus:
                    tasks.append(self._fetch_metaculus())
                if self.enable_manifold:
                    tasks.append(self._fetch_manifold())

                await asyncio.gather(*tasks, return_exceptions=True)
                self._compute_divergences()
                self._last_update_time = datetime.now(timezone.utc)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("cross_reference_poll_error")

            await asyncio.sleep(self.poll_interval_seconds)

    # ------------------------------------------------------------------
    # Data fetchers
    # ------------------------------------------------------------------

    async def _fetch_predictit(self) -> None:
        """Fetch market data from PredictIt.

        PredictIt provides a public API with all active markets
        and current Yes/No prices.
        """
        # TODO: Implement PredictIt API integration
        # import aiohttp
        # url = "https://www.predictit.org/api/marketdata/all/"
        # async with aiohttp.ClientSession() as session:
        #     async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
        #         if resp.status == 200:
        #             data = await resp.json()
        #             for market in data.get("markets", []):
        #                 market_id = str(market.get("id", ""))
        #                 for contract in market.get("contracts", []):
        #                     key = f"pi_{market_id}_{contract.get('id')}"
        #                     self._predictit_markets[key] = {
        #                         "platform": "predictit",
        #                         "market_name": market.get("name", ""),
        #                         "contract_name": contract.get("name", ""),
        #                         "yes_price": contract.get("lastTradePrice"),
        #                         "best_buy_yes": contract.get("bestBuyYesCost"),
        #                         "best_buy_no": contract.get("bestBuyNoCost"),
        #                         "volume": contract.get("totalSharesTraded"),
        #                         "status": market.get("status"),
        #                     }

        logger.debug("predictit_fetch_skipped", reason="API not yet integrated")

    async def _fetch_metaculus(self) -> None:
        """Fetch community predictions from Metaculus.

        Metaculus provides calibrated probability forecasts from
        their forecaster community, useful as a reference point.
        """
        # TODO: Implement Metaculus API integration
        # import aiohttp
        # url = "https://www.metaculus.com/api/questions/"
        # params = {
        #     "status": "open",
        #     "type": "binary",
        #     "order_by": "-activity",
        #     "limit": 50,
        # }
        # async with aiohttp.ClientSession() as session:
        #     async with session.get(url, params=params) as resp:
        #         if resp.status == 200:
        #             data = await resp.json()
        #             for q in data.get("results", []):
        #                 q_id = str(q.get("id", ""))
        #                 community_prediction = q.get("community_prediction", {})
        #                 self._metaculus_questions[q_id] = {
        #                     "platform": "metaculus",
        #                     "title": q.get("title", ""),
        #                     "community_median": community_prediction.get("full", {}).get("q2"),
        #                     "num_predictions": q.get("number_of_predictions", 0),
        #                     "resolution_date": q.get("resolve_time"),
        #                     "url": q.get("url"),
        #                 }

        logger.debug("metaculus_fetch_skipped", reason="API not yet integrated")

    async def _fetch_manifold(self) -> None:
        """Fetch market data from Manifold Markets.

        Manifold provides a free API with active prediction markets
        and current probabilities.
        """
        # TODO: Implement Manifold Markets API integration
        # import aiohttp
        # url = "https://api.manifold.markets/v0/markets"
        # params = {"limit": 50, "sort": "liquidity"}
        # async with aiohttp.ClientSession() as session:
        #     async with session.get(url, params=params) as resp:
        #         if resp.status == 200:
        #             markets = await resp.json()
        #             for m in markets:
        #                 m_id = m.get("id", "")
        #                 self._manifold_markets[m_id] = {
        #                     "platform": "manifold",
        #                     "question": m.get("question", ""),
        #                     "probability": m.get("probability"),
        #                     "volume": m.get("volume"),
        #                     "liquidity": m.get("totalLiquidity"),
        #                     "close_time": m.get("closeTime"),
        #                     "url": m.get("url"),
        #                 }

        logger.debug("manifold_fetch_skipped", reason="API not yet integrated")

    def _compute_divergences(self) -> None:
        """Identify price divergences across platforms.

        Matches similar markets across platforms using keyword
        matching and computes price differences.
        """
        self._divergences = []

        # TODO: Implement cross-platform market matching
        # This requires NLP-based matching of market questions across
        # platforms since they use different naming conventions.
        #
        # Algorithm:
        # 1. Extract key phrases from each market question
        # 2. Compute similarity scores between cross-platform pairs
        # 3. For matched pairs, compute price divergence
        # 4. Flag divergences above min_divergence_pct
        #
        # Example divergence:
        # {
        #     "polymarket_id": "0xabc...",
        #     "polymarket_price": 0.65,
        #     "predictit_id": "pi_1234_5678",
        #     "predictit_price": 0.72,
        #     "divergence_pct": 7.0,
        #     "question": "Will X happen by Y?",
        #     "direction": "polymarket_underpriced",
        # }

        logger.debug("divergence_computation_skipped", reason="Matching not yet implemented")

    # ------------------------------------------------------------------
    # Data retrieval -- BaseDataFeed interface
    # ------------------------------------------------------------------

    async def get_latest(self) -> list[NormalizedSignal]:
        """Convert cross-platform divergences into trading signals.

        When Polymarket disagrees with other platforms by more than
        the threshold, generate a signal to trade toward consensus.
        """
        signals: list[NormalizedSignal] = []

        for divergence in self._divergences:
            div_pct = divergence.get("divergence_pct", 0)
            if abs(div_pct) < self.min_divergence_pct:
                continue

            polymarket_id = divergence.get("polymarket_id", "")
            direction_hint = divergence.get("direction", "")

            # If Polymarket is underpriced vs consensus -> BUY YES
            # If Polymarket is overpriced vs consensus -> SELL YES (BUY NO)
            if "underpriced" in direction_hint:
                direction = Direction.BUY
            else:
                direction = Direction.SELL

            # Higher divergence = higher confidence, cap at 0.7
            confidence = min(abs(div_pct) / 30.0, 0.7)

            signals.append(
                NormalizedSignal(
                    market=Market.POLYMARKET,
                    symbol=polymarket_id,
                    direction=direction,
                    normalized_confidence=round(confidence, 4),
                    metadata={
                        "source": "cross_reference",
                        "divergence_pct": div_pct,
                        "polymarket_price": divergence.get("polymarket_price"),
                        "reference_price": divergence.get("predictit_price")
                        or divergence.get("metaculus_price")
                        or divergence.get("manifold_price"),
                        "reference_platform": divergence.get("reference_platform"),
                        "question": divergence.get("question", "")[:200],
                    },
                )
            )

        return signals

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    def get_divergences(self) -> list[dict[str, Any]]:
        """Return all detected cross-platform divergences."""
        return list(self._divergences)

    def get_predictit_markets(self) -> dict[str, dict[str, Any]]:
        """Return cached PredictIt market data."""
        return dict(self._predictit_markets)

    def get_metaculus_questions(self) -> dict[str, dict[str, Any]]:
        """Return cached Metaculus community predictions."""
        return dict(self._metaculus_questions)

    def get_manifold_markets(self) -> dict[str, dict[str, Any]]:
        """Return cached Manifold Markets data."""
        return dict(self._manifold_markets)

"""Polymarket CLOB (Central Limit Order Book) data feed.

Streams real-time market data from the Polymarket CLOB API including
order books, trades, and market metadata for prediction markets.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from packages.core.data.base_feed import BaseDataFeed
from packages.core.models import Direction, Market, MarketSnapshot, NormalizedSignal

logger = structlog.get_logger(__name__)


# TODO: Configure Polymarket API credentials in .env:
#   POLYMARKET_API_KEY=...
#   POLYMARKET_API_SECRET=...
#   POLYMARKET_FUNDER_ADDRESS=...
#
# Polymarket CLOB API docs: https://docs.polymarket.com/


class ClobFeed(BaseDataFeed):
    """Polymarket CLOB real-time data feed.

    Connects to the Polymarket CLOB API to stream prediction market
    data including prices, order books, volume, and market metadata.

    Parameters
    ----------
    api_key:
        Polymarket API key.
    api_secret:
        Polymarket API secret (for signing).
    funder_address:
        Ethereum address used for funding trades.
    base_url:
        CLOB API base URL.
    poll_interval_seconds:
        Polling frequency for market data.
    """

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        funder_address: str = "",
        base_url: str = "https://clob.polymarket.com",
        poll_interval_seconds: int = 30,
    ) -> None:
        super().__init__()
        self.api_key = api_key
        self.api_secret = api_secret
        self.funder_address = funder_address
        self.base_url = base_url
        self.poll_interval_seconds = poll_interval_seconds

        self._clob_client: Any = None
        self._markets_cache: dict[str, dict[str, Any]] = {}
        self._orderbook_cache: dict[str, dict[str, Any]] = {}
        self._price_cache: dict[str, float] = {}
        self._tracked_condition_ids: list[str] = []
        self._poll_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Initialize the Polymarket CLOB client and start polling."""
        try:
            from py_clob_client.client import ClobClient

            self._clob_client = ClobClient(
                self.base_url,
                key=self.api_key,
                chain_id=137,  # Polygon mainnet
                funder=self.funder_address,
            )

            # Fetch active markets
            await self._refresh_active_markets()

            self._connected = True
            self._poll_task = asyncio.create_task(self._poll_loop())

            logger.info(
                "clob_feed_connected",
                markets_tracked=len(self._markets_cache),
                poll_interval=self.poll_interval_seconds,
            )

        except ImportError:
            logger.warning(
                "py_clob_client_not_installed",
                msg="Install with: pip install py-clob-client. "
                "Feed will start in degraded mode.",
            )
            self._connected = True
            self._poll_task = asyncio.create_task(self._poll_loop())

        except Exception:
            logger.exception("clob_feed_connect_failed")
            self._connected = True  # Allow degraded operation

    async def disconnect(self) -> None:
        """Stop polling and clean up."""
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

        self._connected = False
        logger.info("clob_feed_disconnected")

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        """Periodically refresh market data from the CLOB."""
        while self._connected:
            try:
                await self._refresh_prices()
                await self._refresh_order_books()
                self._last_update_time = datetime.now(timezone.utc)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("clob_poll_error")

            await asyncio.sleep(self.poll_interval_seconds)

    async def _refresh_active_markets(self) -> None:
        """Fetch and cache currently active prediction markets.

        Filters for markets with sufficient liquidity and volume.
        """
        if self._clob_client is None:
            return

        try:
            # Fetch markets using the CLOB client
            # The client runs synchronous code; wrap in executor
            loop = asyncio.get_event_loop()
            markets = await loop.run_in_executor(
                None, self._clob_client.get_markets
            )

            for market_data in markets:
                condition_id = market_data.get("condition_id", "")
                if not condition_id:
                    continue

                self._markets_cache[condition_id] = {
                    "condition_id": condition_id,
                    "question": market_data.get("question", ""),
                    "description": market_data.get("description", ""),
                    "outcomes": market_data.get("outcomes", ["Yes", "No"]),
                    "tokens": market_data.get("tokens", []),
                    "end_date_iso": market_data.get("end_date_iso"),
                    "active": market_data.get("active", True),
                    "closed": market_data.get("closed", False),
                    "volume": float(market_data.get("volume", 0)),
                    "liquidity": float(market_data.get("liquidity", 0)),
                }

            self._tracked_condition_ids = [
                cid for cid, m in self._markets_cache.items()
                if m["active"] and not m["closed"] and m["liquidity"] > 100
            ]

            logger.info(
                "active_markets_refreshed",
                total=len(self._markets_cache),
                tracked=len(self._tracked_condition_ids),
            )

        except Exception:
            logger.exception("refresh_active_markets_failed")

    async def _refresh_prices(self) -> None:
        """Update price cache for all tracked markets."""
        if self._clob_client is None:
            return

        loop = asyncio.get_event_loop()
        for condition_id in self._tracked_condition_ids:
            try:
                market = self._markets_cache.get(condition_id)
                if not market or not market.get("tokens"):
                    continue

                # Get midpoint price for the YES token
                token_id = market["tokens"][0].get("token_id", "") if market["tokens"] else ""
                if not token_id:
                    continue

                price_data = await loop.run_in_executor(
                    None, lambda tid=token_id: self._clob_client.get_midpoint(tid)
                )
                if price_data is not None:
                    self._price_cache[condition_id] = float(price_data)

            except Exception:
                logger.exception(
                    "refresh_price_failed", condition_id=condition_id
                )

    async def _refresh_order_books(self) -> None:
        """Update order book cache for tracked markets."""
        if self._clob_client is None:
            return

        loop = asyncio.get_event_loop()
        for condition_id in self._tracked_condition_ids[:20]:  # Limit to top 20
            try:
                market = self._markets_cache.get(condition_id)
                if not market or not market.get("tokens"):
                    continue

                token_id = market["tokens"][0].get("token_id", "") if market["tokens"] else ""
                if not token_id:
                    continue

                book = await loop.run_in_executor(
                    None, lambda tid=token_id: self._clob_client.get_order_book(tid)
                )
                if book:
                    self._orderbook_cache[condition_id] = book

            except Exception:
                logger.exception(
                    "refresh_orderbook_failed", condition_id=condition_id
                )

    # ------------------------------------------------------------------
    # Data retrieval -- BaseDataFeed interface
    # ------------------------------------------------------------------

    async def get_latest(self) -> list[NormalizedSignal]:
        """Return normalized signals based on current market prices.

        Markets with YES prices deviating significantly from 0.50 may
        present opportunities for mean-reversion or momentum trades.
        """
        signals: list[NormalizedSignal] = []

        for condition_id, price in self._price_cache.items():
            market_data = self._markets_cache.get(condition_id, {})
            question = market_data.get("question", condition_id)

            # Simple signal: extreme prices suggest high conviction
            if price > 0.85:
                direction = Direction.SELL  # Overpriced YES
                confidence = min((price - 0.85) / 0.15 * 0.5, 0.5)
            elif price < 0.15:
                direction = Direction.BUY  # Underpriced YES
                confidence = min((0.15 - price) / 0.15 * 0.5, 0.5)
            else:
                continue  # Skip mid-range markets for simple signal

            signals.append(
                NormalizedSignal(
                    market=Market.POLYMARKET,
                    symbol=condition_id,
                    direction=direction,
                    normalized_confidence=round(confidence, 4),
                    metadata={
                        "source": "polymarket_clob",
                        "question": question[:200],
                        "yes_price": price,
                        "no_price": 1.0 - price,
                        "volume": market_data.get("volume", 0),
                        "liquidity": market_data.get("liquidity", 0),
                    },
                )
            )

        return signals

    # ------------------------------------------------------------------
    # Snapshot builder
    # ------------------------------------------------------------------

    async def get_snapshots(self) -> list[MarketSnapshot]:
        """Build :class:`MarketSnapshot` objects for tracked prediction markets."""
        snapshots: list[MarketSnapshot] = []
        now = datetime.now(timezone.utc)

        for condition_id in self._tracked_condition_ids:
            market_data = self._markets_cache.get(condition_id, {})
            price = self._price_cache.get(condition_id)
            if price is None:
                continue

            book = self._orderbook_cache.get(condition_id, {})
            bids = book.get("bids", [])
            asks = book.get("asks", [])

            best_bid = float(bids[0]["price"]) if bids else None
            best_ask = float(asks[0]["price"]) if asks else None

            snapshots.append(
                MarketSnapshot(
                    market=Market.POLYMARKET,
                    symbol=condition_id,
                    price=price,
                    bid=best_bid,
                    ask=best_ask,
                    spread=(best_ask - best_bid) if (best_bid and best_ask) else None,
                    volume_24h=market_data.get("volume"),
                    timestamp=now,
                    source="polymarket_clob",
                    metadata={
                        "question": market_data.get("question", "")[:200],
                        "description": market_data.get("description", "")[:500],
                        "outcomes": market_data.get("outcomes", []),
                        "end_date": market_data.get("end_date_iso"),
                        "liquidity": market_data.get("liquidity", 0),
                        "no_price": 1.0 - price,
                    },
                )
            )

        return snapshots

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    def get_market_info(self, condition_id: str) -> dict[str, Any]:
        """Return cached market metadata for a given condition ID."""
        return self._markets_cache.get(condition_id, {})

    def get_order_book(self, condition_id: str) -> dict[str, Any]:
        """Return cached order book for a given condition ID."""
        return self._orderbook_cache.get(condition_id, {})

    @property
    def tracked_markets(self) -> list[str]:
        """List of currently tracked condition IDs."""
        return list(self._tracked_condition_ids)

"""On-chain data feed for whale alerts, exchange flows, and network metrics.

Integrates with on-chain analytics providers (Glassnode, CryptoQuant,
Nansen) to surface whale movements, exchange inflow/outflow signals,
and network health indicators.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from packages.core.data.base_feed import BaseDataFeed
from packages.core.models import Direction, Market, NormalizedSignal

logger = structlog.get_logger(__name__)


# TODO: Set up API keys for on-chain providers:
#   - Glassnode: https://studio.glassnode.com/settings/api
#   - CryptoQuant: https://cryptoquant.com/docs
#   - Nansen: https://docs.nansen.ai/
#
# Store keys in .env:
#   GLASSNODE_API_KEY=...
#   CRYPTOQUANT_API_KEY=...


class OnchainFeed(BaseDataFeed):
    """On-chain analytics data feed.

    Tracks whale wallet movements, exchange inflows/outflows, and
    network-level metrics that can provide leading signals for price
    action.

    Parameters
    ----------
    glassnode_api_key:
        API key for Glassnode Studio.
    cryptoquant_api_key:
        API key for CryptoQuant.
    symbols:
        On-chain assets to monitor (e.g. ``["BTC", "ETH"]``).
    poll_interval_seconds:
        How often to poll the APIs (on-chain data is slow-moving).
    """

    def __init__(
        self,
        glassnode_api_key: str = "",
        cryptoquant_api_key: str = "",
        symbols: list[str] | None = None,
        poll_interval_seconds: int = 300,
    ) -> None:
        super().__init__()
        self.glassnode_api_key = glassnode_api_key
        self.cryptoquant_api_key = cryptoquant_api_key
        self.symbols = symbols or ["BTC", "ETH"]
        self.poll_interval_seconds = poll_interval_seconds

        self._exchange_flow_cache: dict[str, dict[str, Any]] = {}
        self._whale_alerts: list[dict[str, Any]] = []
        self._network_metrics: dict[str, dict[str, Any]] = {}
        self._poll_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Start polling on-chain data providers."""
        # Validate that at least one API key is configured
        if not self.glassnode_api_key and not self.cryptoquant_api_key:
            logger.warning(
                "onchain_no_api_keys",
                msg="No on-chain API keys configured. Feed will return empty data. "
                "Set GLASSNODE_API_KEY or CRYPTOQUANT_API_KEY in .env.",
            )

        self._connected = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info(
            "onchain_feed_connected",
            symbols=self.symbols,
            poll_interval=self.poll_interval_seconds,
        )

    async def disconnect(self) -> None:
        """Stop the polling loop."""
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

        self._connected = False
        logger.info("onchain_feed_disconnected")

    # ------------------------------------------------------------------
    # Polling loop
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        """Periodically fetch on-chain data from configured providers."""
        while self._connected:
            try:
                await self._fetch_exchange_flows()
                await self._fetch_whale_alerts()
                await self._fetch_network_metrics()
                self._last_update_time = datetime.now(timezone.utc)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("onchain_poll_error")

            await asyncio.sleep(self.poll_interval_seconds)

    # ------------------------------------------------------------------
    # Data fetchers
    # ------------------------------------------------------------------

    async def _fetch_exchange_flows(self) -> None:
        """Fetch exchange inflow/outflow data.

        Large inflows to exchanges often precede selling pressure, while
        large outflows suggest accumulation.
        """
        if not self.glassnode_api_key:
            return

        # TODO: Implement Glassnode API call for exchange net flow
        # Endpoint: https://api.glassnode.com/v1/metrics/transactions/transfers_volume_exchanges_net
        # Headers: {"X-API-KEY": self.glassnode_api_key}
        #
        # Example response parsing:
        # for symbol in self.symbols:
        #     async with aiohttp.ClientSession() as session:
        #         params = {"a": symbol, "s": start_ts, "u": end_ts, "i": "1h"}
        #         async with session.get(url, params=params, headers=headers) as resp:
        #             data = await resp.json()
        #             self._exchange_flow_cache[symbol] = {
        #                 "net_flow": data[-1]["v"],
        #                 "inflow": ...,
        #                 "outflow": ...,
        #                 "timestamp": data[-1]["t"],
        #             }

        logger.debug("exchange_flows_fetch_skipped", reason="API not yet integrated")

    async def _fetch_whale_alerts(self) -> None:
        """Fetch recent whale transaction alerts.

        Monitors large on-chain transfers that may indicate institutional
        activity or exchange movements.
        """
        # TODO: Integrate Whale Alert API or CryptoQuant whale tracking
        # Endpoint: https://api.whale-alert.io/v1/transactions
        # Params: {"api_key": key, "min_value": 1000000, "cursor": ...}
        #
        # Parse into:
        # self._whale_alerts = [
        #     {
        #         "symbol": "BTC",
        #         "amount": 500.0,
        #         "amount_usd": 30_000_000,
        #         "from_type": "unknown",    # "exchange", "unknown"
        #         "to_type": "exchange",
        #         "timestamp": ...,
        #     },
        # ]

        logger.debug("whale_alerts_fetch_skipped", reason="API not yet integrated")

    async def _fetch_network_metrics(self) -> None:
        """Fetch network health metrics (hash rate, active addresses, etc.).

        These slow-moving fundamentals help the AI assess longer-term
        conviction.
        """
        if not self.glassnode_api_key:
            return

        # TODO: Fetch from Glassnode:
        # - Active addresses: /v1/metrics/addresses/active_count
        # - Hash rate: /v1/metrics/mining/hash_rate_mean
        # - NVT ratio: /v1/metrics/indicators/nvt
        # - MVRV ratio: /v1/metrics/market/mvrv
        #
        # for symbol in self.symbols:
        #     self._network_metrics[symbol] = {
        #         "active_addresses_24h": ...,
        #         "hash_rate": ...,
        #         "nvt_ratio": ...,
        #         "mvrv_ratio": ...,
        #     }

        logger.debug("network_metrics_fetch_skipped", reason="API not yet integrated")

    # ------------------------------------------------------------------
    # Data retrieval -- BaseDataFeed interface
    # ------------------------------------------------------------------

    async def get_latest(self) -> list[NormalizedSignal]:
        """Return on-chain signals as normalized signals.

        Converts exchange flow imbalances and whale activity into
        directional signals with confidence scores.
        """
        signals: list[NormalizedSignal] = []

        for symbol in self.symbols:
            flow_data = self._exchange_flow_cache.get(symbol)
            if flow_data is None:
                continue

            net_flow = flow_data.get("net_flow", 0.0)

            # Negative net flow (outflow > inflow) is bullish
            # Positive net flow (inflow > outflow) is bearish
            if net_flow < 0:
                direction = Direction.BUY
                confidence = min(abs(net_flow) / 10000.0, 0.8)  # Cap at 0.8
            elif net_flow > 0:
                direction = Direction.SHORT
                confidence = min(abs(net_flow) / 10000.0, 0.8)
            else:
                continue

            signals.append(
                NormalizedSignal(
                    market=Market.CRYPTO,
                    symbol=f"{symbol}/USDT",
                    direction=direction,
                    normalized_confidence=round(confidence, 4),
                    metadata={
                        "source": "onchain",
                        "net_flow": net_flow,
                        "whale_alert_count": len(
                            [w for w in self._whale_alerts if w.get("symbol") == symbol]
                        ),
                        "network_metrics": self._network_metrics.get(symbol, {}),
                    },
                )
            )

        return signals

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    def get_exchange_flows(self, symbol: str) -> dict[str, Any]:
        """Return cached exchange flow data for *symbol*."""
        return self._exchange_flow_cache.get(symbol, {})

    def get_whale_alerts(self, symbol: str | None = None) -> list[dict[str, Any]]:
        """Return recent whale alerts, optionally filtered by *symbol*."""
        if symbol is None:
            return list(self._whale_alerts)
        return [w for w in self._whale_alerts if w.get("symbol") == symbol]

    def get_network_metrics(self, symbol: str) -> dict[str, Any]:
        """Return cached network metrics for *symbol*."""
        return self._network_metrics.get(symbol, {})

"""DeFi data feed via DeFiLlama API.

Tracks Total Value Locked (TVL), protocol metrics, and yield data
from DeFiLlama to provide DeFi market intelligence that correlates
with crypto price action.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from packages.core.data.base_feed import BaseDataFeed
from packages.core.models import Direction, Market, NormalizedSignal

logger = structlog.get_logger(__name__)


# DeFiLlama API is free and requires no API key.
# Docs: https://defillama.com/docs/api
#
# Key endpoints:
#   - TVL: https://api.llama.fi/v2/historicalChainTvl
#   - Protocols: https://api.llama.fi/protocols
#   - Yields: https://yields.llama.fi/pools
#   - Stablecoins: https://stablecoins.llama.fi/stablecoins


class DeFiFeed(BaseDataFeed):
    """DeFi market data feed from DeFiLlama.

    Tracks TVL trends, protocol health, and yield movements to
    identify macro DeFi trends that influence crypto prices.

    Parameters
    ----------
    tracked_chains:
        Blockchain networks to track TVL for.
    tracked_protocols:
        Specific DeFi protocols to monitor.
    poll_interval_seconds:
        Polling frequency (DeFi data is relatively slow-moving).
    tvl_change_threshold_pct:
        Minimum TVL change percentage to generate a signal.
    """

    def __init__(
        self,
        tracked_chains: list[str] | None = None,
        tracked_protocols: list[str] | None = None,
        poll_interval_seconds: int = 600,
        tvl_change_threshold_pct: float = 5.0,
    ) -> None:
        super().__init__()
        self.tracked_chains = tracked_chains or [
            "Ethereum", "BSC", "Solana", "Arbitrum", "Polygon",
        ]
        self.tracked_protocols = tracked_protocols or [
            "lido", "aave", "makerdao", "uniswap", "curve-dex",
            "eigenlayer", "rocket-pool", "compound-finance",
        ]
        self.poll_interval_seconds = poll_interval_seconds
        self.tvl_change_threshold_pct = tvl_change_threshold_pct

        self._chain_tvl: dict[str, dict[str, Any]] = {}
        self._protocol_tvl: dict[str, dict[str, Any]] = {}
        self._total_tvl: Optional[float] = None
        self._total_tvl_previous: Optional[float] = None
        self._stablecoin_supply: dict[str, float] = {}
        self._yield_data: list[dict[str, Any]] = []
        self._poll_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Start the DeFi data polling loop."""
        self._connected = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info(
            "defi_feed_connected",
            chains=self.tracked_chains,
            protocols=self.tracked_protocols,
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
        logger.info("defi_feed_disconnected")

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        """Periodically refresh DeFi data from DeFiLlama."""
        while self._connected:
            try:
                await asyncio.gather(
                    self._fetch_chain_tvl(),
                    self._fetch_protocol_tvl(),
                    self._fetch_stablecoin_supply(),
                    self._fetch_yield_data(),
                    return_exceptions=True,
                )
                self._last_update_time = datetime.now(timezone.utc)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("defi_poll_error")

            await asyncio.sleep(self.poll_interval_seconds)

    # ------------------------------------------------------------------
    # Data fetchers
    # ------------------------------------------------------------------

    async def _fetch_chain_tvl(self) -> None:
        """Fetch TVL data for tracked blockchain networks.

        Rising TVL indicates capital inflows into DeFi, which is
        generally bullish for the underlying chain's native token.
        """
        # TODO: Implement DeFiLlama chain TVL endpoint
        # import aiohttp
        # async with aiohttp.ClientSession() as session:
        #     # Total TVL
        #     async with session.get("https://api.llama.fi/v2/historicalChainTvl") as resp:
        #         if resp.status == 200:
        #             data = await resp.json()
        #             if data:
        #                 self._total_tvl_previous = self._total_tvl
        #                 self._total_tvl = data[-1].get("tvl")
        #
        #     # Per-chain TVL
        #     for chain in self.tracked_chains:
        #         url = f"https://api.llama.fi/v2/historicalChainTvl/{chain}"
        #         async with session.get(url) as resp:
        #             if resp.status == 200:
        #                 data = await resp.json()
        #                 if data and len(data) >= 2:
        #                     current = data[-1].get("tvl", 0)
        #                     previous = data[-2].get("tvl", 0)
        #                     change_pct = ((current - previous) / previous * 100
        #                                   if previous > 0 else 0)
        #                     self._chain_tvl[chain] = {
        #                         "tvl": current,
        #                         "tvl_previous": previous,
        #                         "change_pct": change_pct,
        #                         "date": data[-1].get("date"),
        #                     }

        logger.debug("chain_tvl_fetch_skipped", reason="API not yet integrated")

    async def _fetch_protocol_tvl(self) -> None:
        """Fetch TVL data for specific DeFi protocols.

        Protocol-level TVL changes can indicate capital rotation
        between protocols and DeFi sub-sectors.
        """
        # TODO: Implement DeFiLlama protocol endpoint
        # import aiohttp
        # async with aiohttp.ClientSession() as session:
        #     async with session.get("https://api.llama.fi/protocols") as resp:
        #         if resp.status == 200:
        #             protocols = await resp.json()
        #             for proto in protocols:
        #                 slug = proto.get("slug", "")
        #                 if slug in self.tracked_protocols:
        #                     self._protocol_tvl[slug] = {
        #                         "name": proto.get("name"),
        #                         "tvl": proto.get("tvl", 0),
        #                         "change_1h": proto.get("change_1h"),
        #                         "change_1d": proto.get("change_1d"),
        #                         "change_7d": proto.get("change_7d"),
        #                         "chain": proto.get("chain"),
        #                         "category": proto.get("category"),
        #                     }

        logger.debug("protocol_tvl_fetch_skipped", reason="API not yet integrated")

    async def _fetch_stablecoin_supply(self) -> None:
        """Fetch stablecoin supply data.

        Increasing stablecoin supply (dry powder) is bullish for crypto
        markets, while decreasing supply suggests capital exit.
        """
        # TODO: Implement DeFiLlama stablecoins endpoint
        # import aiohttp
        # async with aiohttp.ClientSession() as session:
        #     url = "https://stablecoins.llama.fi/stablecoins?includePrices=true"
        #     async with session.get(url) as resp:
        #         if resp.status == 200:
        #             data = await resp.json()
        #             for stable in data.get("peggedAssets", []):
        #                 name = stable.get("symbol", "")
        #                 mcap = stable.get("circulating", {}).get("peggedUSD", 0)
        #                 self._stablecoin_supply[name] = mcap

        logger.debug("stablecoin_supply_fetch_skipped", reason="API not yet integrated")

    async def _fetch_yield_data(self) -> None:
        """Fetch DeFi yield data for top pools.

        Yield compression/expansion across DeFi signals risk appetite
        changes in the market.
        """
        # TODO: Implement DeFiLlama yields endpoint
        # import aiohttp
        # async with aiohttp.ClientSession() as session:
        #     url = "https://yields.llama.fi/pools"
        #     async with session.get(url) as resp:
        #         if resp.status == 200:
        #             data = await resp.json()
        #             pools = data.get("data", [])
        #             # Filter for top pools by TVL
        #             top_pools = sorted(
        #                 pools, key=lambda p: p.get("tvlUsd", 0), reverse=True
        #             )[:50]
        #             self._yield_data = [
        #                 {
        #                     "pool": p.get("pool"),
        #                     "project": p.get("project"),
        #                     "chain": p.get("chain"),
        #                     "symbol": p.get("symbol"),
        #                     "tvl_usd": p.get("tvlUsd"),
        #                     "apy": p.get("apy"),
        #                     "apy_base": p.get("apyBase"),
        #                     "apy_reward": p.get("apyReward"),
        #                 }
        #                 for p in top_pools
        #             ]

        logger.debug("yield_data_fetch_skipped", reason="API not yet integrated")

    # ------------------------------------------------------------------
    # Data retrieval -- BaseDataFeed interface
    # ------------------------------------------------------------------

    async def get_latest(self) -> list[NormalizedSignal]:
        """Convert DeFi data into normalized signals.

        TVL trends and stablecoin supply changes are converted
        into broad market directional signals.
        """
        signals: list[NormalizedSignal] = []

        # Chain-level TVL signals
        for chain, data in self._chain_tvl.items():
            change_pct = data.get("change_pct", 0)
            if abs(change_pct) < self.tvl_change_threshold_pct:
                continue

            # Rising TVL -> bullish for chain token
            if change_pct > 0:
                direction = Direction.BUY
                confidence = min(change_pct / 20.0, 0.6)
            else:
                direction = Direction.SHORT
                confidence = min(abs(change_pct) / 20.0, 0.6)

            # Map chain to trading symbol
            chain_to_symbol = {
                "Ethereum": "ETH/USDT",
                "BSC": "BNB/USDT",
                "Solana": "SOL/USDT",
                "Polygon": "MATIC/USDT",
                "Arbitrum": "ARB/USDT",
            }
            symbol = chain_to_symbol.get(chain)
            if not symbol:
                continue

            signals.append(
                NormalizedSignal(
                    market=Market.CRYPTO,
                    symbol=symbol,
                    direction=direction,
                    normalized_confidence=round(confidence, 4),
                    metadata={
                        "source": "defi_feed",
                        "signal_type": "tvl_change",
                        "chain": chain,
                        "tvl": data.get("tvl"),
                        "tvl_change_pct": round(change_pct, 2),
                    },
                )
            )

        # Total TVL change signal
        if self._total_tvl and self._total_tvl_previous:
            total_change = (
                (self._total_tvl - self._total_tvl_previous)
                / self._total_tvl_previous * 100
            )
            if abs(total_change) >= self.tvl_change_threshold_pct:
                direction = Direction.BUY if total_change > 0 else Direction.SHORT
                confidence = min(abs(total_change) / 15.0, 0.5)
                signals.append(
                    NormalizedSignal(
                        market=Market.CRYPTO,
                        symbol="BTC/USDT",
                        direction=direction,
                        normalized_confidence=round(confidence, 4),
                        metadata={
                            "source": "defi_feed",
                            "signal_type": "total_tvl_change",
                            "total_tvl": self._total_tvl,
                            "change_pct": round(total_change, 2),
                        },
                    )
                )

        return signals

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    def get_chain_tvl(self, chain: str) -> dict[str, Any]:
        """Return cached TVL data for a specific chain."""
        return self._chain_tvl.get(chain, {})

    def get_protocol_tvl(self, protocol: str) -> dict[str, Any]:
        """Return cached TVL data for a specific protocol."""
        return self._protocol_tvl.get(protocol, {})

    @property
    def total_tvl(self) -> float | None:
        """Total DeFi TVL across all chains."""
        return self._total_tvl

    def get_stablecoin_supply(self) -> dict[str, float]:
        """Return stablecoin supply data."""
        return dict(self._stablecoin_supply)

    def get_top_yields(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return top DeFi yield opportunities by TVL."""
        return self._yield_data[:limit]

    def get_defi_summary(self) -> dict[str, Any]:
        """Return a summary of the current DeFi landscape."""
        return {
            "total_tvl": self._total_tvl,
            "chain_tvl": {
                chain: data.get("tvl") for chain, data in self._chain_tvl.items()
            },
            "top_protocols": {
                name: data.get("tvl")
                for name, data in sorted(
                    self._protocol_tvl.items(),
                    key=lambda x: x[1].get("tvl", 0),
                    reverse=True,
                )[:10]
            },
            "stablecoin_supply": self._stablecoin_supply,
            "last_updated": (
                self._last_update_time.isoformat()
                if self._last_update_time
                else None
            ),
        }

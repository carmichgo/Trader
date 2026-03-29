"""Macroeconomic data feed via FRED API.

Provides macroeconomic indicators from the Federal Reserve Economic
Data (FRED) API including interest rates, inflation, employment,
and GDP data that influence equity markets.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from packages.core.data.base_feed import BaseDataFeed
from packages.core.models import Direction, Market, NormalizedSignal

logger = structlog.get_logger(__name__)


# TODO: Configure FRED API key in .env:
#   FRED_API_KEY=...
#
# FRED API docs: https://fred.stlouisfed.org/docs/api/fred/
# Free API key: https://fred.stlouisfed.org/docs/api/api_key.html


# Key FRED series IDs for macro indicators
FRED_SERIES = {
    "fed_funds_rate": "FEDFUNDS",           # Federal Funds Rate
    "cpi_yoy": "CPIAUCSL",                  # CPI (inflation)
    "unemployment": "UNRATE",                # Unemployment Rate
    "gdp_growth": "A191RL1Q225SBEA",        # Real GDP Growth
    "ten_year_yield": "DGS10",              # 10-Year Treasury Yield
    "two_year_yield": "DGS2",               # 2-Year Treasury Yield
    "vix": "VIXCLS",                        # VIX Volatility Index
    "consumer_sentiment": "UMCSENT",         # U of Michigan Consumer Sentiment
    "initial_claims": "ICSA",               # Initial Jobless Claims
    "pce_inflation": "PCEPI",               # PCE Price Index (Fed's preferred)
    "housing_starts": "HOUST",              # Housing Starts
    "retail_sales": "RSAFS",               # Retail Sales
    "ism_manufacturing": "MANEMP",           # Manufacturing Employment
    "m2_money_supply": "M2SL",             # M2 Money Supply
}


class MacroFeed(BaseDataFeed):
    """Macroeconomic data feed from FRED.

    Tracks key economic indicators that influence equity market
    direction, sector rotation, and risk appetite.

    Parameters
    ----------
    fred_api_key:
        FRED API key.
    tracked_series:
        Dict of name -> FRED series ID to track.  Defaults to
        a comprehensive set of macro indicators.
    poll_interval_seconds:
        Polling frequency.  Macro data updates infrequently
        (daily/weekly/monthly), so longer intervals are fine.
    """

    def __init__(
        self,
        fred_api_key: str = "",
        tracked_series: dict[str, str] | None = None,
        poll_interval_seconds: int = 3600,
    ) -> None:
        super().__init__()
        self.fred_api_key = fred_api_key
        self.tracked_series = tracked_series or FRED_SERIES
        self.poll_interval_seconds = poll_interval_seconds

        self._data_cache: dict[str, dict[str, Any]] = {}
        self._yield_curve_spread: Optional[float] = None
        self._macro_regime: str = "neutral"
        self._poll_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Start the macro data polling loop."""
        if not self.fred_api_key:
            logger.warning(
                "macro_feed_no_api_key",
                msg="No FRED API key configured. Set FRED_API_KEY in .env. "
                "Get a free key at https://fred.stlouisfed.org/docs/api/api_key.html",
            )

        self._connected = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info(
            "macro_feed_connected",
            series_count=len(self.tracked_series),
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
        logger.info("macro_feed_disconnected")

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        """Periodically refresh macro data from FRED."""
        while self._connected:
            try:
                await self._fetch_all_series()
                self._compute_derived_indicators()
                self._last_update_time = datetime.now(timezone.utc)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("macro_poll_error")

            await asyncio.sleep(self.poll_interval_seconds)

    # ------------------------------------------------------------------
    # Data fetchers
    # ------------------------------------------------------------------

    async def _fetch_all_series(self) -> None:
        """Fetch latest values for all tracked FRED series."""
        if not self.fred_api_key:
            return

        # TODO: Implement FRED API calls
        # import aiohttp
        # base_url = "https://api.stlouisfed.org/fred/series/observations"
        #
        # async with aiohttp.ClientSession() as session:
        #     for name, series_id in self.tracked_series.items():
        #         params = {
        #             "series_id": series_id,
        #             "api_key": self.fred_api_key,
        #             "file_type": "json",
        #             "sort_order": "desc",
        #             "limit": 5,  # Last 5 observations
        #         }
        #         async with session.get(base_url, params=params) as resp:
        #             if resp.status == 200:
        #                 data = await resp.json()
        #                 observations = data.get("observations", [])
        #                 if observations:
        #                     latest = observations[0]
        #                     value = latest.get("value", ".")
        #                     if value != ".":
        #                         self._data_cache[name] = {
        #                             "value": float(value),
        #                             "date": latest.get("date"),
        #                             "series_id": series_id,
        #                         }
        #                         # Store previous for change calculation
        #                         if len(observations) > 1:
        #                             prev = observations[1].get("value", ".")
        #                             if prev != ".":
        #                                 self._data_cache[name]["previous"] = float(prev)

        logger.debug("fred_fetch_skipped", reason="API not yet integrated")

    def _compute_derived_indicators(self) -> None:
        """Compute derived indicators from raw FRED data.

        Key derived indicators:
        - Yield curve spread (10Y - 2Y): inversion signals recession
        - Real interest rate: fed funds - inflation
        - Macro regime classification
        """
        # Yield curve spread
        ten_year = self._data_cache.get("ten_year_yield", {}).get("value")
        two_year = self._data_cache.get("two_year_yield", {}).get("value")

        if ten_year is not None and two_year is not None:
            self._yield_curve_spread = ten_year - two_year
        else:
            self._yield_curve_spread = None

        # Macro regime classification
        self._macro_regime = self._classify_regime()

    def _classify_regime(self) -> str:
        """Classify the current macro regime.

        Returns one of:
        - ``"risk_on"``: expansionary, low rates, positive sentiment
        - ``"risk_off"``: contractionary, rising rates, negative
        - ``"transition"``: mixed signals
        - ``"neutral"``: insufficient data
        """
        vix = self._data_cache.get("vix", {}).get("value")
        fed_rate = self._data_cache.get("fed_funds_rate", {}).get("value")
        unemployment = self._data_cache.get("unemployment", {}).get("value")
        consumer_sent = self._data_cache.get("consumer_sentiment", {}).get("value")

        if not any([vix, fed_rate, unemployment, consumer_sent]):
            return "neutral"

        risk_on_signals = 0
        risk_off_signals = 0

        if vix is not None:
            if vix < 15:
                risk_on_signals += 1
            elif vix > 25:
                risk_off_signals += 1

        if self._yield_curve_spread is not None:
            if self._yield_curve_spread > 0.5:
                risk_on_signals += 1
            elif self._yield_curve_spread < 0:
                risk_off_signals += 1  # Inverted yield curve

        if unemployment is not None:
            if unemployment < 4.0:
                risk_on_signals += 1
            elif unemployment > 6.0:
                risk_off_signals += 1

        if consumer_sent is not None:
            if consumer_sent > 80:
                risk_on_signals += 1
            elif consumer_sent < 60:
                risk_off_signals += 1

        if risk_on_signals > risk_off_signals + 1:
            return "risk_on"
        elif risk_off_signals > risk_on_signals + 1:
            return "risk_off"
        elif risk_on_signals > 0 or risk_off_signals > 0:
            return "transition"
        else:
            return "neutral"

    # ------------------------------------------------------------------
    # Data retrieval -- BaseDataFeed interface
    # ------------------------------------------------------------------

    async def get_latest(self) -> list[NormalizedSignal]:
        """Convert macro regime into a broad market signal.

        The macro regime influences overall equity positioning:
        - risk_on -> bullish bias for equities
        - risk_off -> bearish / defensive positioning
        """
        signals: list[NormalizedSignal] = []

        regime = self._macro_regime

        if regime == "risk_on":
            direction = Direction.BUY
            confidence = 0.4
        elif regime == "risk_off":
            direction = Direction.SHORT
            confidence = 0.4
        elif regime == "transition":
            direction = Direction.BUY
            confidence = 0.15
        else:
            return signals  # Neutral -- no signal

        # Emit one signal for the broad market (SPY)
        signals.append(
            NormalizedSignal(
                market=Market.STOCKS,
                symbol="SPY",
                direction=direction,
                normalized_confidence=round(confidence, 4),
                metadata={
                    "source": "macro_feed",
                    "regime": regime,
                    "yield_curve_spread": self._yield_curve_spread,
                    "vix": self._data_cache.get("vix", {}).get("value"),
                    "fed_funds_rate": self._data_cache.get("fed_funds_rate", {}).get("value"),
                    "unemployment": self._data_cache.get("unemployment", {}).get("value"),
                },
            )
        )

        return signals

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    @property
    def macro_regime(self) -> str:
        """Current macro regime classification."""
        return self._macro_regime

    @property
    def yield_curve_spread(self) -> Optional[float]:
        """Current 10Y-2Y yield curve spread."""
        return self._yield_curve_spread

    def get_indicator(self, name: str) -> dict[str, Any]:
        """Return cached data for a specific macro indicator."""
        return self._data_cache.get(name, {})

    def get_all_indicators(self) -> dict[str, dict[str, Any]]:
        """Return all cached macro indicators."""
        return dict(self._data_cache)

    def get_macro_summary(self) -> dict[str, Any]:
        """Return a summary of the current macro environment."""
        return {
            "regime": self._macro_regime,
            "yield_curve_spread": self._yield_curve_spread,
            "indicators": {
                name: data.get("value")
                for name, data in self._data_cache.items()
            },
            "last_updated": (
                self._last_update_time.isoformat()
                if self._last_update_time
                else None
            ),
        }

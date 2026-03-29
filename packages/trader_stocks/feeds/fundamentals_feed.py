"""Fundamentals data feed: SEC filings, earnings, and financial metrics.

Provides fundamental analysis data including earnings reports, SEC
filings, revenue growth, and valuation metrics for equities.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from packages.core.data.base_feed import BaseDataFeed
from packages.core.models import Direction, Market, NormalizedSignal

logger = structlog.get_logger(__name__)


# TODO: Configure API keys in .env for fundamental data:
#   ALPHA_VANTAGE_API_KEY=...     # https://www.alphavantage.co/
#   FINANCIAL_MODELING_KEY=...    # https://financialmodelingprep.com/
#   SEC_EDGAR_USER_AGENT=...     # your-email@domain.com (for SEC EDGAR)
#   POLYGON_API_KEY=...          # Polygon.io also provides fundamentals


class FundamentalsFeed(BaseDataFeed):
    """Fundamentals and earnings data feed.

    Tracks earnings reports, SEC filings, revenue metrics, and
    valuation ratios for equities in the trading universe.

    Parameters
    ----------
    alpha_vantage_key:
        API key for Alpha Vantage financial data.
    fmp_key:
        API key for Financial Modeling Prep.
    sec_user_agent:
        User agent string for SEC EDGAR API access.
    symbols:
        Ticker symbols to track fundamentals for.
    poll_interval_seconds:
        Polling frequency (fundamentals change infrequently).
    """

    def __init__(
        self,
        alpha_vantage_key: str = "",
        fmp_key: str = "",
        sec_user_agent: str = "",
        symbols: list[str] | None = None,
        poll_interval_seconds: int = 3600,
    ) -> None:
        super().__init__()
        self.alpha_vantage_key = alpha_vantage_key
        self.fmp_key = fmp_key
        self.sec_user_agent = sec_user_agent
        self.symbols = symbols or [
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
        ]
        self.poll_interval_seconds = poll_interval_seconds

        self._earnings_cache: dict[str, dict[str, Any]] = {}
        self._fundamentals_cache: dict[str, dict[str, Any]] = {}
        self._filings_cache: dict[str, list[dict[str, Any]]] = {}
        self._upcoming_earnings: list[dict[str, Any]] = []
        self._poll_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Start the fundamentals polling loop."""
        if not self.alpha_vantage_key and not self.fmp_key:
            logger.warning(
                "fundamentals_no_api_keys",
                msg="No fundamentals API keys configured. "
                "Set ALPHA_VANTAGE_API_KEY or FINANCIAL_MODELING_KEY in .env.",
            )

        self._connected = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info(
            "fundamentals_feed_connected",
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
        logger.info("fundamentals_feed_disconnected")

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        """Periodically refresh fundamental data."""
        while self._connected:
            try:
                await asyncio.gather(
                    self._fetch_earnings(),
                    self._fetch_fundamentals(),
                    self._fetch_sec_filings(),
                    self._fetch_upcoming_earnings(),
                    return_exceptions=True,
                )
                self._last_update_time = datetime.now(timezone.utc)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("fundamentals_poll_error")

            await asyncio.sleep(self.poll_interval_seconds)

    # ------------------------------------------------------------------
    # Data fetchers
    # ------------------------------------------------------------------

    async def _fetch_earnings(self) -> None:
        """Fetch recent earnings data for tracked symbols.

        Earnings surprises (beat/miss) are strong short-term signals.
        """
        if not self.fmp_key:
            return

        # TODO: Implement Financial Modeling Prep earnings endpoint
        # import aiohttp
        # for symbol in self.symbols:
        #     url = f"https://financialmodelingprep.com/api/v3/income-statement/{symbol}"
        #     params = {"period": "quarter", "limit": 4, "apikey": self.fmp_key}
        #     async with aiohttp.ClientSession() as session:
        #         async with session.get(url, params=params) as resp:
        #             data = await resp.json()
        #             if data:
        #                 latest = data[0]
        #                 self._earnings_cache[symbol] = {
        #                     "revenue": latest.get("revenue"),
        #                     "net_income": latest.get("netIncome"),
        #                     "eps": latest.get("eps"),
        #                     "revenue_growth": latest.get("revenueGrowth"),
        #                     "date": latest.get("date"),
        #                     "period": latest.get("period"),
        #                 }

        logger.debug("earnings_fetch_skipped", reason="API not yet integrated")

    async def _fetch_fundamentals(self) -> None:
        """Fetch key financial ratios and valuation metrics."""
        if not self.fmp_key and not self.alpha_vantage_key:
            return

        # TODO: Implement key ratios endpoint
        # Metrics to fetch:
        # - P/E ratio (trailing and forward)
        # - P/S ratio
        # - P/B ratio
        # - EV/EBITDA
        # - Debt/Equity
        # - ROE
        # - Free cash flow yield
        # - Dividend yield
        #
        # for symbol in self.symbols:
        #     url = f"https://financialmodelingprep.com/api/v3/ratios-ttm/{symbol}"
        #     params = {"apikey": self.fmp_key}
        #     async with aiohttp.ClientSession() as session:
        #         async with session.get(url, params=params) as resp:
        #             data = await resp.json()
        #             if data:
        #                 ratios = data[0]
        #                 self._fundamentals_cache[symbol] = {
        #                     "pe_ratio": ratios.get("peRatioTTM"),
        #                     "ps_ratio": ratios.get("priceToSalesRatioTTM"),
        #                     "pb_ratio": ratios.get("priceToBookRatioTTM"),
        #                     "ev_ebitda": ratios.get("enterpriseValueMultipleTTM"),
        #                     "debt_equity": ratios.get("debtEquityRatioTTM"),
        #                     "roe": ratios.get("returnOnEquityTTM"),
        #                     "fcf_yield": ratios.get("freeCashFlowPerShareTTM"),
        #                     "dividend_yield": ratios.get("dividendYielTTM"),
        #                 }

        logger.debug("fundamentals_fetch_skipped", reason="API not yet integrated")

    async def _fetch_sec_filings(self) -> None:
        """Fetch recent SEC filings from EDGAR.

        Monitors 8-K (material events), 10-Q (quarterly), and 10-K
        (annual) filings for insider activity and material disclosures.
        """
        if not self.sec_user_agent:
            return

        # TODO: Implement SEC EDGAR API
        # Base URL: https://efts.sec.gov/LATEST/search-index
        # Headers: {"User-Agent": self.sec_user_agent}
        #
        # For each symbol, search for recent filings:
        # url = f"https://efts.sec.gov/LATEST/search-index?q={symbol}&dateRange=custom&startdt=..."
        # Focus on:
        # - 8-K filings (material events: CEO changes, M&A, etc.)
        # - 13-F filings (institutional holdings)
        # - Form 4 (insider transactions)

        logger.debug("sec_filings_fetch_skipped", reason="API not yet integrated")

    async def _fetch_upcoming_earnings(self) -> None:
        """Fetch earnings calendar for upcoming reports.

        Earnings dates create predictable volatility events that
        the AI can prepare for.
        """
        # TODO: Implement earnings calendar
        # url = "https://financialmodelingprep.com/api/v3/earning_calendar"
        # params = {"apikey": self.fmp_key}
        # Filter for tracked symbols

        logger.debug("upcoming_earnings_fetch_skipped", reason="API not yet integrated")

    # ------------------------------------------------------------------
    # Data retrieval -- BaseDataFeed interface
    # ------------------------------------------------------------------

    async def get_latest(self) -> list[NormalizedSignal]:
        """Convert fundamental signals into normalized signals.

        Earnings surprises and valuation extremes generate directional
        signals with appropriate confidence levels.
        """
        signals: list[NormalizedSignal] = []

        for symbol in self.symbols:
            earnings = self._earnings_cache.get(symbol, {})
            fundamentals = self._fundamentals_cache.get(symbol, {})

            if not earnings and not fundamentals:
                continue

            # Earnings surprise signal
            if earnings.get("eps_surprise_pct"):
                surprise = earnings["eps_surprise_pct"]
                if abs(surprise) > 5:  # >5% surprise
                    direction = Direction.BUY if surprise > 0 else Direction.SHORT
                    confidence = min(abs(surprise) / 20.0, 0.7)

                    signals.append(
                        NormalizedSignal(
                            market=Market.STOCKS,
                            symbol=symbol,
                            direction=direction,
                            normalized_confidence=round(confidence, 4),
                            metadata={
                                "source": "fundamentals",
                                "signal_type": "earnings_surprise",
                                "eps_surprise_pct": surprise,
                                "pe_ratio": fundamentals.get("pe_ratio"),
                            },
                        )
                    )

            # Valuation signal
            pe = fundamentals.get("pe_ratio")
            if pe is not None and pe > 0:
                if pe < 10:
                    signals.append(
                        NormalizedSignal(
                            market=Market.STOCKS,
                            symbol=symbol,
                            direction=Direction.BUY,
                            normalized_confidence=0.3,
                            metadata={
                                "source": "fundamentals",
                                "signal_type": "low_pe",
                                "pe_ratio": pe,
                            },
                        )
                    )
                elif pe > 50:
                    signals.append(
                        NormalizedSignal(
                            market=Market.STOCKS,
                            symbol=symbol,
                            direction=Direction.SHORT,
                            normalized_confidence=0.2,
                            metadata={
                                "source": "fundamentals",
                                "signal_type": "high_pe",
                                "pe_ratio": pe,
                            },
                        )
                    )

        return signals

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    def get_earnings(self, symbol: str) -> dict[str, Any]:
        """Return cached earnings data for *symbol*."""
        return self._earnings_cache.get(symbol, {})

    def get_fundamentals(self, symbol: str) -> dict[str, Any]:
        """Return cached fundamental ratios for *symbol*."""
        return self._fundamentals_cache.get(symbol, {})

    def get_filings(self, symbol: str) -> list[dict[str, Any]]:
        """Return cached SEC filings for *symbol*."""
        return self._filings_cache.get(symbol, [])

    def get_upcoming_earnings(self) -> list[dict[str, Any]]:
        """Return the upcoming earnings calendar."""
        return list(self._upcoming_earnings)

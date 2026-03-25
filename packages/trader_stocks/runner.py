"""Stock trader runner: main event loop and dependency wiring.

Implements the :class:`StockTrader` (a :class:`BaseTrader` subclass)
and provides the ``run_stock_trader()`` entry point.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from packages.core.ai.client import AIClient
from packages.core.ai.cost_tracker import CostTracker
from packages.core.base_trader import BaseTrader
from packages.core.config import SystemConfig
from packages.core.execution.order_manager import OrderManager
from packages.core.models import (
    Market,
    MarketSnapshot,
    Opportunity,
    TraderConfig,
    TraderPortfolio,
)
from packages.core.planning.pace_monitor import PaceMonitor
from packages.core.risk.drawdown_monitor import DrawdownMonitor
from packages.core.risk.frequency_limiter import FrequencyLimiter
from packages.core.risk.manager import RiskManager
from packages.trader_stocks.executor import StockExecutor
from packages.trader_stocks.feeds.market_feed import MarketFeed
from packages.trader_stocks.feeds.fundamentals_feed import FundamentalsFeed
from packages.trader_stocks.feeds.macro_feed import MacroFeed
from packages.trader_stocks.strategy import StockStrategy

logger = structlog.get_logger(__name__)


class StockTrader(BaseTrader):
    """Stock-specific trader implementation.

    Wires together market feeds, fundamentals, macro data, and the
    stock strategy preprocessor to implement the abstract methods
    required by :class:`BaseTrader`.

    Parameters
    ----------
    market_feed:
        Real-time stock market data feed (prices, quotes, bars).
    fundamentals_feed:
        Fundamentals data feed (earnings, SEC filings, ratios).
    macro_feed:
        Macroeconomic data feed (FRED API indicators).
    strategy:
        Stock strategy preprocessor for building AI contexts.
    **kwargs:
        Passed through to :class:`BaseTrader`.
    """

    def __init__(
        self,
        market_feed: MarketFeed,
        fundamentals_feed: FundamentalsFeed,
        macro_feed: MacroFeed,
        strategy: StockStrategy,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.market_feed = market_feed
        self.fundamentals_feed = fundamentals_feed
        self.macro_feed = macro_feed
        self.strategy = strategy

        # Caches for the current cycle
        self._current_snapshots: list[MarketSnapshot] = []
        self._current_bars: dict[str, list[dict[str, Any]]] = {}
        self._current_fundamentals: dict[str, dict[str, Any]] = {}
        self._current_macro: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # BaseTrader abstract method implementations
    # ------------------------------------------------------------------

    async def collect_market_data(self) -> list[MarketSnapshot]:
        """Gather stock market data from all configured feeds.

        Collects data in parallel from market, fundamentals, and macro
        feeds, then builds enriched :class:`MarketSnapshot` objects
        via the :class:`StockStrategy`.
        """
        log = logger.bind(trader=self.trader_name)

        # Parallel data collection
        await asyncio.gather(
            self._collect_market_data(),
            self._collect_fundamentals_data(),
            self._collect_macro_data(),
            return_exceptions=True,
        )

        log.info(
            "stock_data_collected",
            snapshots=len(self._current_snapshots),
            bars_symbols=len(self._current_bars),
            fundamentals_symbols=len(self._current_fundamentals),
            has_macro=bool(self._current_macro),
        )

        return self._current_snapshots

    def build_full_context(self, opportunity: Opportunity) -> dict[str, Any]:
        """Assemble the full context for Opus analyst evaluation.

        Delegates to :class:`StockStrategy` which combines all
        available data sources into a structured context dict.
        """
        recent_trades = [
            {
                "symbol": t.symbol,
                "direction": t.direction.value,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "net_pnl": t.net_pnl,
                "close_reason": t.close_reason.value if t.close_reason else None,
            }
            for t in self.portfolio.trade_history[-10:]
        ]

        return self.strategy.build_analysis_context(
            opportunity=opportunity,
            snapshots=self._current_snapshots,
            portfolio_state=self.portfolio.current_state,
            recent_trades=recent_trades,
            bars_data=self._current_bars,
            fundamentals_data=self._current_fundamentals,
            macro_summary=self._current_macro,
        )

    # ------------------------------------------------------------------
    # Data collection helpers
    # ------------------------------------------------------------------

    async def _collect_market_data(self) -> None:
        """Fetch snapshots and bars from the market feed."""
        try:
            self._current_snapshots = await self.market_feed.get_snapshots()

            # Fetch bars for each symbol
            for symbol in self.market_feed.symbols:
                bars = self.market_feed.get_bars(symbol)
                if bars:
                    self._current_bars[symbol] = bars

        except Exception:
            logger.exception("stock_market_data_collection_failed")
            self._current_snapshots = []

    async def _collect_fundamentals_data(self) -> None:
        """Fetch fundamentals for all tracked symbols."""
        try:
            for symbol in self.market_feed.symbols:
                fundamentals = self.fundamentals_feed.get_fundamentals(symbol)
                earnings = self.fundamentals_feed.get_earnings(symbol)
                if fundamentals or earnings:
                    self._current_fundamentals[symbol] = {
                        **fundamentals,
                        "earnings": earnings,
                    }
        except Exception:
            logger.exception("fundamentals_data_collection_failed")

    async def _collect_macro_data(self) -> None:
        """Fetch macro environment summary."""
        try:
            self._current_macro = self.macro_feed.get_macro_summary()
        except Exception:
            logger.exception("macro_data_collection_failed")

    # ------------------------------------------------------------------
    # Lifecycle overrides
    # ------------------------------------------------------------------

    async def start(self, interval_seconds: float | None = None) -> None:
        """Start the stock trader: connect feeds, then run the loop."""
        log = logger.bind(trader=self.trader_name)

        # Connect all feeds
        log.info("connecting_stock_feeds")
        await asyncio.gather(
            self.market_feed.connect(),
            self.fundamentals_feed.connect(),
            self.macro_feed.connect(),
            return_exceptions=True,
        )

        # Initialize executor
        if isinstance(self.executor, StockExecutor):
            await self.executor.initialize()

        log.info("stock_feeds_connected")

        # Run the trading loop
        await super().start(interval_seconds)

    async def stop(self) -> None:
        """Stop the stock trader and disconnect all feeds."""
        await super().stop()

        await asyncio.gather(
            self.market_feed.disconnect(),
            self.fundamentals_feed.disconnect(),
            self.macro_feed.disconnect(),
            return_exceptions=True,
        )

        if isinstance(self.executor, StockExecutor):
            await self.executor.close()

        logger.info("stock_trader_stopped", trader=self.trader_name)


# ======================================================================
# Entry point
# ======================================================================


async def run_stock_trader(
    config: SystemConfig | None = None,
    trader_config: TraderConfig | None = None,
) -> None:
    """Entry point: wire up all dependencies and run the stock trader.

    Parameters
    ----------
    config:
        System configuration.  Loaded from config.yaml / .env if not
        provided.
    trader_config:
        Trader-specific configuration.  Uses sensible stock defaults
        if not provided.
    """
    config = config or SystemConfig()
    trader_config = trader_config or TraderConfig(
        name="stock-trader",
        mode="paper",
        markets=[Market.STOCKS],
        initial_balance=config.goal.starting_capital,
        target_balance=config.goal.target_capital,
        screener_interval_minutes=15,
        default_leverage=1.0,
        default_stop_loss_pct=0.05,
        default_take_profit_pct=0.10,
    )

    # --- Feeds ---
    market_feed = MarketFeed(
        alpaca_api_key=config.market.alpaca_api_key,
        alpaca_api_secret=config.market.alpaca_api_secret,
        alpaca_base_url=config.market.alpaca_base_url,
        symbols=[
            "SPY", "QQQ", "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA",
            "META", "TSLA", "AMD",
        ],
        poll_interval_seconds=60,
    )

    fundamentals_feed = FundamentalsFeed(
        symbols=[
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
        ],
        poll_interval_seconds=3600,
    )

    macro_feed = MacroFeed(
        poll_interval_seconds=3600,
    )

    # --- Strategy ---
    strategy = StockStrategy(config=trader_config)

    # --- Executor ---
    executor = StockExecutor(
        api_key=config.market.alpaca_api_key,
        api_secret=config.market.alpaca_api_secret,
        base_url=config.market.alpaca_base_url,
        default_order_type="market",
    )

    # --- AI ---
    ai_client = AIClient(config.ai)
    cost_tracker = CostTracker(daily_limit_usd=config.ai.daily_cost_limit_usd)

    # --- Risk ---
    risk_manager = RiskManager()
    drawdown_monitor = DrawdownMonitor(
        initial_balance=trader_config.initial_balance,
        max_daily_drawdown_pct=trader_config.safety_rails.max_daily_drawdown_pct,
        kill_switch_pct=trader_config.safety_rails.kill_switch_drawdown_pct,
    )
    frequency_limiter = FrequencyLimiter(
        max_losing_streak=trader_config.safety_rails.max_losing_streak_before_pause,
        cool_down_hours=trader_config.safety_rails.cool_down_after_pause_hours,
    )

    # --- Planning ---
    pace_monitor = PaceMonitor(
        target_balance=trader_config.target_balance or trader_config.initial_balance * 10,
        time_horizon_days=config.goal.time_horizon_days,
        initial_balance=trader_config.initial_balance,
    )

    # --- Order management ---
    order_manager = OrderManager()

    # --- Portfolio ---
    portfolio = TraderPortfolio(
        name="stock-trader",
        initial_balance=trader_config.initial_balance,
        is_paper_trading=(trader_config.mode == "paper"),
    )

    # --- Assemble trader ---
    trader = StockTrader(
        market_feed=market_feed,
        fundamentals_feed=fundamentals_feed,
        macro_feed=macro_feed,
        strategy=strategy,
        trader_name="stock-trader",
        market=Market.STOCKS,
        config=config,
        trader_config=trader_config,
        ai_client=ai_client,
        risk_manager=risk_manager,
        executor=executor,
        cost_tracker=cost_tracker,
        order_manager=order_manager,
        drawdown_monitor=drawdown_monitor,
        frequency_limiter=frequency_limiter,
        pace_monitor=pace_monitor,
        portfolio=portfolio,
    )

    logger.info(
        "stock_trader_starting",
        initial_balance=trader_config.initial_balance,
        mode=trader_config.mode,
    )

    try:
        await trader.start()
    except KeyboardInterrupt:
        logger.info("stock_trader_interrupted")
    finally:
        await trader.stop()

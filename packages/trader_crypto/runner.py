"""Crypto trader runner: main event loop and dependency wiring.

Implements the :class:`CryptoTrader` (a :class:`BaseTrader` subclass)
and provides the ``run_crypto_trader()`` entry point.
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
from packages.trader_crypto.executor import CryptoExecutor
from packages.trader_crypto.feeds.exchange_feed import ExchangeFeed
from packages.trader_crypto.feeds.onchain_feed import OnchainFeed
from packages.trader_crypto.feeds.sentiment_feed import SentimentFeed
from packages.trader_crypto.strategy import CryptoStrategy

logger = structlog.get_logger(__name__)


class CryptoTrader(BaseTrader):
    """Crypto-specific trader implementation.

    Wires together exchange feeds, on-chain data, sentiment data,
    and the crypto strategy preprocessor to implement the abstract
    :meth:`collect_market_data` and :meth:`build_full_context` methods
    required by :class:`BaseTrader`.

    Parameters
    ----------
    exchange_feed:
        Real-time exchange data feed (prices, order books, trades).
    onchain_feed:
        On-chain analytics feed (whale alerts, exchange flows).
    sentiment_feed:
        Sentiment data feed (Fear & Greed, social sentiment).
    strategy:
        Crypto strategy preprocessor for building AI contexts.
    **kwargs:
        Passed through to :class:`BaseTrader`.
    """

    def __init__(
        self,
        exchange_feed: ExchangeFeed,
        onchain_feed: OnchainFeed,
        sentiment_feed: SentimentFeed,
        strategy: CryptoStrategy,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.exchange_feed = exchange_feed
        self.onchain_feed = onchain_feed
        self.sentiment_feed = sentiment_feed
        self.strategy = strategy

        # Caches for the current cycle
        self._current_snapshots: list[MarketSnapshot] = []
        self._current_ohlcv: dict[str, list[list]] = {}
        self._current_orderbooks: dict[str, dict[str, Any]] = {}
        self._current_onchain: dict[str, dict[str, Any]] = {}
        self._current_sentiment: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # BaseTrader abstract method implementations
    # ------------------------------------------------------------------

    async def collect_market_data(self) -> list[MarketSnapshot]:
        """Gather crypto market data from all configured feeds.

        Collects data in parallel from exchange, on-chain, and sentiment
        feeds, then builds enriched :class:`MarketSnapshot` objects
        via the :class:`CryptoStrategy`.
        """
        log = logger.bind(trader=self.trader_name)

        # Parallel data collection
        exchange_task = self._collect_exchange_data()
        onchain_task = self._collect_onchain_data()
        sentiment_task = self._collect_sentiment_data()

        await asyncio.gather(
            exchange_task, onchain_task, sentiment_task,
            return_exceptions=True,
        )

        log.info(
            "market_data_collected",
            snapshots=len(self._current_snapshots),
            ohlcv_symbols=len(self._current_ohlcv),
            onchain_symbols=len(self._current_onchain),
            has_sentiment=bool(self._current_sentiment),
        )

        return self._current_snapshots

    def build_full_context(self, opportunity: Opportunity) -> dict[str, Any]:
        """Assemble the full context for Opus analyst evaluation.

        Delegates to :class:`CryptoStrategy` which combines all
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
            ohlcv_data=self._current_ohlcv,
            orderbook_data=self._current_orderbooks,
            onchain_data=self._current_onchain,
            sentiment_data=self._current_sentiment,
        )

    # ------------------------------------------------------------------
    # Data collection helpers
    # ------------------------------------------------------------------

    async def _collect_exchange_data(self) -> None:
        """Fetch snapshots, OHLCV, order books, and funding rates."""
        try:
            self._current_snapshots = await self.exchange_feed.get_snapshots()

            # Fetch OHLCV and order books for each symbol
            for symbol in self.exchange_feed.symbols:
                try:
                    ohlcv = await self.exchange_feed.get_ohlcv(symbol, "1h", limit=100)
                    if ohlcv:
                        self._current_ohlcv[symbol] = ohlcv
                except Exception:
                    logger.exception("ohlcv_fetch_failed", symbol=symbol)

                try:
                    book = await self.exchange_feed.get_order_book(symbol, limit=20)
                    if book:
                        self._current_orderbooks[symbol] = book
                except Exception:
                    logger.exception("orderbook_fetch_failed", symbol=symbol)

            # Fetch funding rates
            try:
                funding_rates = await self.exchange_feed.get_funding_rates()
                for sym, rate in funding_rates.items():
                    for snapshot in self._current_snapshots:
                        if snapshot.symbol == sym:
                            snapshot.funding_rate = rate
            except Exception:
                logger.exception("funding_rates_fetch_failed")

        except Exception:
            logger.exception("exchange_data_collection_failed")
            self._current_snapshots = []

    async def _collect_onchain_data(self) -> None:
        """Fetch on-chain metrics for all tracked symbols."""
        try:
            for symbol in self.onchain_feed.symbols:
                self._current_onchain[symbol] = {
                    "exchange_flows": self.onchain_feed.get_exchange_flows(symbol),
                    "whale_alerts": self.onchain_feed.get_whale_alerts(symbol),
                    "network_metrics": self.onchain_feed.get_network_metrics(symbol),
                }
        except Exception:
            logger.exception("onchain_data_collection_failed")

    async def _collect_sentiment_data(self) -> None:
        """Fetch sentiment indicators."""
        try:
            self._current_sentiment = {
                "fear_greed_index": self.sentiment_feed.fear_greed_index,
                "fear_greed_label": self.sentiment_feed.fear_greed_label,
            }
            for symbol in self.sentiment_feed.symbols:
                social = self.sentiment_feed.get_social_sentiment(symbol)
                if social:
                    self._current_sentiment[f"social_{symbol}"] = social
        except Exception:
            logger.exception("sentiment_data_collection_failed")

    # ------------------------------------------------------------------
    # Lifecycle overrides
    # ------------------------------------------------------------------

    async def start(self, interval_seconds: float | None = None) -> None:
        """Start the crypto trader: connect feeds, then run the loop."""
        log = logger.bind(trader=self.trader_name)

        # Connect all feeds
        log.info("connecting_feeds")
        await asyncio.gather(
            self.exchange_feed.connect(),
            self.onchain_feed.connect(),
            self.sentiment_feed.connect(),
            return_exceptions=True,
        )

        # Initialize executor
        if isinstance(self.executor, CryptoExecutor):
            await self.executor.initialize()

        log.info("feeds_connected")

        # Run the trading loop
        await super().start(interval_seconds)

    async def stop(self) -> None:
        """Stop the crypto trader and disconnect all feeds."""
        await super().stop()

        await asyncio.gather(
            self.exchange_feed.disconnect(),
            self.onchain_feed.disconnect(),
            self.sentiment_feed.disconnect(),
            return_exceptions=True,
        )

        if isinstance(self.executor, CryptoExecutor):
            await self.executor.close()

        logger.info("crypto_trader_stopped", trader=self.trader_name)


# ======================================================================
# Entry point
# ======================================================================


async def run_crypto_trader(
    config: SystemConfig | None = None,
    trader_config: TraderConfig | None = None,
) -> None:
    """Entry point: wire up all dependencies and run the crypto trader.

    Parameters
    ----------
    config:
        System configuration.  Loaded from config.yaml / .env if not
        provided.
    trader_config:
        Trader-specific configuration.  Uses sensible crypto defaults
        if not provided.
    """
    config = config or SystemConfig()
    trader_config = trader_config or TraderConfig(
        name="crypto-trader",
        mode="paper",
        markets=[Market.CRYPTO],
        initial_balance=config.goal.starting_capital,
        target_balance=config.goal.target_capital,
        screener_interval_minutes=15,
        default_leverage=1.0,
        default_stop_loss_pct=0.05,
        default_take_profit_pct=0.10,
    )

    # --- Feeds ---
    exchange_feed = ExchangeFeed(
        exchange_id=config.market.crypto_exchange,
        api_key=config.market.crypto_api_key,
        api_secret=config.market.crypto_api_secret,
        symbols=["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT"],
        sandbox=config.market.crypto_sandbox,
    )

    onchain_feed = OnchainFeed(
        symbols=["BTC", "ETH"],
        poll_interval_seconds=300,
    )

    sentiment_feed = SentimentFeed(
        symbols=["BTC", "ETH", "SOL"],
        poll_interval_seconds=600,
    )

    # --- Strategy ---
    strategy = CryptoStrategy(config=trader_config)

    # --- Executor ---
    executor = CryptoExecutor(
        exchange_id=config.market.crypto_exchange,
        api_key=config.market.crypto_api_key,
        api_secret=config.market.crypto_api_secret,
        sandbox=config.market.crypto_sandbox,
        default_order_type="limit",
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
        name="crypto-trader",
        initial_balance=trader_config.initial_balance,
        is_paper_trading=(trader_config.mode == "paper"),
    )

    # --- Assemble trader ---
    trader = CryptoTrader(
        exchange_feed=exchange_feed,
        onchain_feed=onchain_feed,
        sentiment_feed=sentiment_feed,
        strategy=strategy,
        trader_name="crypto-trader",
        market=Market.CRYPTO,
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
        "crypto_trader_starting",
        exchange=config.market.crypto_exchange,
        sandbox=config.market.crypto_sandbox,
        initial_balance=trader_config.initial_balance,
        mode=trader_config.mode,
    )

    try:
        await trader.start()
    except KeyboardInterrupt:
        logger.info("crypto_trader_interrupted")
    finally:
        await trader.stop()

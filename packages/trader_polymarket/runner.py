"""Polymarket trader runner: main event loop and dependency wiring.

Implements the :class:`PolymarketTrader` (a :class:`BaseTrader` subclass)
and provides the ``run_polymarket_trader()`` entry point.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from packages.core.ai.client import AIClient
from packages.core.ai.cost_tracker import CostTracker
from packages.core.base_trader import BaseTrader
from packages.core.db.supabase_client import SupabaseDB
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
from packages.trader_polymarket.executor import PolymarketExecutor
from packages.trader_polymarket.feeds.clob_feed import ClobFeed
from packages.trader_polymarket.feeds.news_feed import NewsFeed
from packages.trader_polymarket.feeds.resolution_tracker import ResolutionTracker
from packages.trader_polymarket.strategy import PolymarketStrategy

logger = structlog.get_logger(__name__)


class PolymarketTrader(BaseTrader):
    """Polymarket-specific trader implementation.

    Wires together the CLOB feed, news monitoring, resolution tracking,
    and the Polymarket strategy preprocessor to implement the abstract
    methods required by :class:`BaseTrader`.

    Parameters
    ----------
    clob_feed:
        Polymarket CLOB data feed for prices and order books.
    news_feed:
        News monitoring feed for event-relevant headlines.
    resolution_tracker:
        Tracks market resolution timelines and outcomes.
    strategy:
        Polymarket strategy preprocessor for building AI contexts.
    **kwargs:
        Passed through to :class:`BaseTrader`.
    """

    def __init__(
        self,
        clob_feed: ClobFeed,
        news_feed: NewsFeed,
        resolution_tracker: ResolutionTracker,
        strategy: PolymarketStrategy,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.clob_feed = clob_feed
        self.news_feed = news_feed
        self.resolution_tracker = resolution_tracker
        self.strategy = strategy

        # Caches for the current cycle
        self._current_snapshots: list[MarketSnapshot] = []
        self._current_news: list[dict[str, Any]] = []
        self._current_resolutions: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # BaseTrader abstract method implementations
    # ------------------------------------------------------------------

    async def collect_market_data(self) -> list[MarketSnapshot]:
        """Gather Polymarket data from all configured feeds.

        Collects CLOB data, news, and resolution statuses in parallel,
        then builds enriched market snapshots.
        """
        log = logger.bind(trader=self.trader_name)

        # Parallel data collection
        await asyncio.gather(
            self._collect_clob_data(),
            self._collect_news_data(),
            self._collect_resolution_data(),
            return_exceptions=True,
        )

        log.info(
            "polymarket_data_collected",
            snapshots=len(self._current_snapshots),
            news_items=len(self._current_news),
            resolution_markets=len(self._current_resolutions),
        )

        return self._current_snapshots

    def build_full_context(self, opportunity: Opportunity) -> dict[str, Any]:
        """Assemble the full context for Opus analyst evaluation.

        Includes market data, relevant news, resolution timeline,
        and portfolio state.
        """
        # Filter news relevant to this opportunity
        relevant_news = [
            h for h in self._current_news
            if any(
                keyword.lower() in (opportunity.title or "").lower()
                for keyword in h.get("title", "").split()[:3]
            )
        ]

        # Get resolution info
        resolution_info = self._current_resolutions.get(
            opportunity.symbol, {}
        )

        # Find related markets (same category)
        related = [
            {
                "symbol": s.symbol,
                "question": s.metadata.get("question", "")[:100],
                "price": s.price,
            }
            for s in self._current_snapshots
            if s.symbol != opportunity.symbol
            and s.metadata.get("question")
        ][:5]

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
            news_headlines=relevant_news,
            resolution_info=resolution_info,
            related_markets=related,
        )

    # ------------------------------------------------------------------
    # Data collection helpers
    # ------------------------------------------------------------------

    async def _collect_clob_data(self) -> None:
        """Fetch snapshots from the CLOB feed."""
        try:
            self._current_snapshots = await self.clob_feed.get_snapshots()
        except Exception:
            logger.exception("clob_data_collection_failed")
            self._current_snapshots = []

    async def _collect_news_data(self) -> None:
        """Fetch news headlines."""
        try:
            self._current_news = self.news_feed.get_headlines()
        except Exception:
            logger.exception("news_data_collection_failed")
            self._current_news = []

    async def _collect_resolution_data(self) -> None:
        """Fetch resolution statuses for tracked markets."""
        try:
            for condition_id in self.clob_feed.tracked_markets:
                status = self.resolution_tracker.get_status(condition_id)
                if status:
                    self._current_resolutions[condition_id] = status
        except Exception:
            logger.exception("resolution_data_collection_failed")

    # ------------------------------------------------------------------
    # Lifecycle overrides
    # ------------------------------------------------------------------

    async def start(self, interval_seconds: float | None = None) -> None:
        """Start the Polymarket trader: connect feeds, then run the loop."""
        log = logger.bind(trader=self.trader_name)

        log.info("connecting_polymarket_feeds")
        await asyncio.gather(
            self.clob_feed.connect(),
            self.news_feed.connect(),
            self.resolution_tracker.connect(),
            return_exceptions=True,
        )

        if isinstance(self.executor, PolymarketExecutor):
            await self.executor.initialize()

        log.info("polymarket_feeds_connected")
        await super().start(interval_seconds)

    async def stop(self) -> None:
        """Stop the Polymarket trader and disconnect feeds."""
        await super().stop()

        await asyncio.gather(
            self.clob_feed.disconnect(),
            self.news_feed.disconnect(),
            self.resolution_tracker.disconnect(),
            return_exceptions=True,
        )

        if isinstance(self.executor, PolymarketExecutor):
            await self.executor.close()

        logger.info("polymarket_trader_stopped", trader=self.trader_name)


# ======================================================================
# Entry point
# ======================================================================


async def run_polymarket_trader(
    config: SystemConfig | None = None,
    trader_config: TraderConfig | None = None,
) -> None:
    """Entry point: wire up dependencies and run the Polymarket trader.

    Parameters
    ----------
    config:
        System configuration. Loaded from config.yaml / .env if not provided.
    trader_config:
        Trader-specific configuration. Uses sensible Polymarket defaults
        if not provided.
    """
    config = config or SystemConfig()
    trader_config = trader_config or TraderConfig(
        name="polymarket-trader",
        mode="paper",
        markets=[Market.POLYMARKET],
        initial_balance=config.goal.starting_capital,
        target_balance=config.goal.target_capital,
        screener_interval_minutes=10,
        default_leverage=1.0,
        default_stop_loss_pct=0.15,
        default_take_profit_pct=0.25,
    )

    # --- Feeds ---
    clob_feed = ClobFeed(
        api_key=config.market.polymarket_api_key,
        api_secret=config.market.polymarket_api_secret,
        funder_address=config.market.polymarket_funder_address,
        poll_interval_seconds=30,
    )

    news_feed = NewsFeed(
        tracked_topics=[
            "election", "federal reserve", "supreme court",
            "regulation", "geopolitics", "AI policy",
        ],
        poll_interval_seconds=120,
    )

    resolution_tracker = ResolutionTracker(
        clob_feed=clob_feed,
        approaching_threshold_hours=48,
        poll_interval_seconds=60,
    )

    # --- Strategy ---
    strategy = PolymarketStrategy(config=trader_config)

    # --- Executor ---
    executor = PolymarketExecutor(
        api_key=config.market.polymarket_api_key,
        api_secret=config.market.polymarket_api_secret,
        funder_address=config.market.polymarket_funder_address,
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
        name="polymarket-trader",
        initial_balance=trader_config.initial_balance,
        is_paper_trading=(trader_config.mode == "paper"),
    )

    # --- Supabase persistence ---
    supabase_db = SupabaseDB()

    # --- Assemble trader ---
    trader = PolymarketTrader(
        clob_feed=clob_feed,
        news_feed=news_feed,
        resolution_tracker=resolution_tracker,
        strategy=strategy,
        trader_name="polymarket-trader",
        market=Market.POLYMARKET,
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
        supabase_db=supabase_db,
    )

    logger.info(
        "polymarket_trader_starting",
        initial_balance=trader_config.initial_balance,
        mode=trader_config.mode,
    )

    try:
        await trader.start()
    except KeyboardInterrupt:
        logger.info("polymarket_trader_interrupted")
    finally:
        await trader.stop()

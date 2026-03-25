"""Abstract base trader class for all market traders.

Provides the core trading loop: screen -> analyze -> risk-check -> execute -> monitor.
Concrete subclasses implement market-specific data collection and context building.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Any, Optional

import structlog

from packages.core.ai.analyst import Analyst
from packages.core.ai.client import AIClient
from packages.core.ai.cost_tracker import CostTracker
from packages.core.ai.screener import Screener
from packages.core.config import SystemConfig
from packages.core.execution.base_executor import BaseExecutor
from packages.core.execution.order_manager import OrderManager
from packages.core.models import (
    CloseReason,
    Direction,
    Market,
    MarketSnapshot,
    NetExpectedValue,
    Opportunity,
    PortfolioState,
    Position,
    ScreenerResult,
    Trade,
    TradeStatus,
    TraderConfig,
    TraderPortfolio,
)
from packages.core.planning.pace_monitor import PaceMonitor
from packages.core.risk.drawdown_monitor import DrawdownMonitor
from packages.core.risk.frequency_limiter import FrequencyLimiter
from packages.core.risk.manager import RiskCheckResult, RiskManager, TradePlan

logger = structlog.get_logger(__name__)


class BaseTrader(ABC):
    """Abstract base for all market traders.

    Orchestrates the full trading lifecycle:
    1. Collect market data from feeds
    2. Screen for opportunities (Sonnet)
    3. Deep-analyze high-value opportunities (Opus)
    4. Risk-check and size positions
    5. Execute orders
    6. Monitor open positions (stop-loss, take-profit, trailing stops, time expiry)

    Subclasses must implement:
    - :meth:`collect_market_data` -- gather market-specific snapshots
    - :meth:`build_full_context` -- assemble context dict for the analyst
    """

    def __init__(
        self,
        trader_name: str,
        market: Market,
        config: SystemConfig,
        trader_config: TraderConfig,
        ai_client: AIClient,
        risk_manager: RiskManager,
        executor: BaseExecutor,
        cost_tracker: CostTracker,
        order_manager: OrderManager,
        drawdown_monitor: DrawdownMonitor,
        frequency_limiter: FrequencyLimiter,
        pace_monitor: PaceMonitor,
        portfolio: TraderPortfolio | None = None,
    ) -> None:
        self.trader_name = trader_name
        self.market = market
        self.config = config
        self.trader_config = trader_config
        self.ai_client = ai_client
        self.risk_manager = risk_manager
        self.executor = executor
        self.cost_tracker = cost_tracker
        self.order_manager = order_manager
        self.drawdown_monitor = drawdown_monitor
        self.frequency_limiter = frequency_limiter
        self.pace_monitor = pace_monitor

        self.portfolio = portfolio or TraderPortfolio(
            name=trader_name,
            initial_balance=trader_config.initial_balance,
        )

        # AI sub-systems
        self.screener = Screener(ai_client, cost_tracker, trader_id=trader_name)
        self.analyst = Analyst(ai_client, cost_tracker, trader_id=trader_name)

        self._running = False

    # ------------------------------------------------------------------
    # Main trading cycle
    # ------------------------------------------------------------------

    async def run_cycle(self) -> None:
        """Execute a single trading cycle -- the main loop body.

        Steps:
        1. Check if trading is allowed (drawdown, frequency, budget)
        2. Collect market data from feeds
        3. Run screener (Sonnet)
        4. For each opportunity (highest confidence first):
           a. Pre-trade cost check (should_call_opus)
           b. Run analyst (Opus) or use screener output for small trades
           c. Risk check
           d. Execute order
           e. Log everything
           f. Update portfolio and pace
        5. Monitor existing positions
        """
        log = logger.bind(trader=self.trader_name, market=self.market.value)

        # ---- 1. Pre-flight checks ----------------------------------------
        if not self._preflight_checks(log):
            return

        # ---- 2. Collect market data --------------------------------------
        try:
            snapshots = await self.collect_market_data()
        except Exception:
            log.exception("market_data_collection_failed")
            return

        if not snapshots:
            log.info("no_market_data", msg="No snapshots returned, skipping cycle")
            return

        # ---- 3. Run screener (Sonnet) ------------------------------------
        try:
            screener_result = await self.screener.scan(
                snapshots, self.trader_config, self.market
            )
        except Exception:
            log.exception("screener_failed")
            return

        if not screener_result.opportunities:
            log.info(
                "no_opportunities",
                scanned=screener_result.total_scanned,
            )
            await self.monitor_positions()
            return

        # Sort by confidence descending
        opportunities = sorted(
            screener_result.opportunities,
            key=lambda o: o.confidence,
            reverse=True,
        )

        log.info(
            "screener_complete",
            opportunities=len(opportunities),
            scanned=screener_result.total_scanned,
            cost=screener_result.inference_cost,
        )

        # ---- 4. Process each opportunity ---------------------------------
        for opp in opportunities:
            # Re-check frequency/budget before each trade
            can_trade, reason = self.frequency_limiter.can_trade()
            if not can_trade:
                log.info("frequency_limit_hit", reason=reason)
                break

            budget_exhausted = await self.cost_tracker.is_budget_exhausted(
                self.trader_name
            )
            if budget_exhausted:
                log.warning("budget_exhausted_mid_cycle")
                break

            await self._process_opportunity(opp, log)

        # ---- 5. Monitor existing positions -------------------------------
        await self.monitor_positions()

    def _preflight_checks(self, log: Any) -> bool:
        """Return True if trading is allowed, False otherwise."""
        # Drawdown check
        if self.drawdown_monitor.is_paused():
            snapshot = self.drawdown_monitor.snapshot()
            log.warning(
                "trading_paused_drawdown",
                reason=snapshot.pause_reason,
                resume_at=snapshot.resume_at,
            )
            return False

        if self.drawdown_monitor.should_trigger_kill_switch():
            log.critical("kill_switch_active", msg="Trading halted by kill switch")
            return False

        # Frequency check
        can_trade, reason = self.frequency_limiter.can_trade()
        if not can_trade:
            log.info("frequency_limit", reason=reason)
            return False

        # Portfolio paused
        if self.portfolio.is_paused:
            log.info("portfolio_paused", reason=self.portfolio.pause_reason)
            return False

        return True

    async def _process_opportunity(self, opp: Opportunity, log: Any) -> None:
        """Evaluate and potentially execute a single opportunity."""
        log = log.bind(symbol=opp.symbol, confidence=opp.confidence)

        # 4a. Pre-trade cost check -- should we spend on Opus?
        should_use_opus = await self.analyst.should_call_opus(
            opp, self.trader_config
        )

        trade_plan = None

        if should_use_opus:
            # 4b. Deep analysis with Opus
            try:
                full_context = self.build_full_context(opp)
                trade_plan = await self.analyst.analyze(opp, full_context, self.market)
            except Exception:
                log.exception("analyst_failed")
                return

            if trade_plan is None:
                log.info("analyst_rejected", symbol=opp.symbol)
                return
        else:
            # Use screener output directly for small/low-cost trades
            log.info("skipping_opus", reason="below cost threshold")
            return  # Skip trades not worth Opus analysis

        # 4c. Risk check
        risk_plan = TradePlan(
            signal=self._opportunity_to_signal(opp),
            proposed_size_usd=trade_plan.position_size_usd,
            proposed_leverage=trade_plan.leverage,
            stop_loss_pct=(
                abs(trade_plan.entry_price - trade_plan.stop_loss_price)
                / trade_plan.entry_price
                if trade_plan.entry_price > 0
                else self.trader_config.default_stop_loss_pct
            ),
            take_profit_pct=(
                abs(trade_plan.take_profit_price - trade_plan.entry_price)
                / trade_plan.entry_price
                if trade_plan.entry_price > 0
                else self.trader_config.default_take_profit_pct
            ),
        )

        risk_result = self.risk_manager.check(
            risk_plan,
            self.portfolio.current_state,
            self.trader_config,
            self.trader_config.safety_rails,
        )

        if not risk_result.approved:
            log.info("risk_rejected", reason=risk_result.reason)
            return

        # Adjust size if risk manager clamped it
        if risk_result.adjusted_size is not None:
            trade_plan.position_size_usd = risk_result.adjusted_size
            log.info("size_adjusted", new_size=risk_result.adjusted_size)

        # 4d. Execute order
        try:
            order = await self.executor.place_order(risk_plan)
            self.order_manager.submit_order(order)
            log.info(
                "order_placed",
                order_id=order.id,
                exchange_id=order.exchange_order_id,
                direction=order.direction.value,
                quantity=order.quantity,
                price=order.price,
            )
        except Exception:
            log.exception("order_execution_failed")
            return

        # 4e. Create trade record
        trade = Trade(
            id=str(uuid.uuid4()),
            market=self.market,
            symbol=opp.symbol,
            direction=trade_plan.direction,
            strategy=self.trader_name,
            signal_id=opp.id,
            entry_price=trade_plan.entry_price,
            quantity=order.quantity,
            stop_loss_price=trade_plan.stop_loss_price,
            take_profit_price=trade_plan.take_profit_price,
            leverage=trade_plan.leverage,
            confidence=trade_plan.confidence,
            orders=[order],
        )
        self.portfolio.active_trades.append(trade)

        # 4f. Update portfolio and pace
        allocated = trade_plan.position_size_usd
        self.portfolio.current_state.allocated_balance += allocated
        self.portfolio.current_state.available_balance -= allocated
        self.portfolio.current_state.open_position_count += 1

        log.info(
            "trade_opened",
            trade_id=trade.id,
            size_usd=trade_plan.position_size_usd,
            entry=trade_plan.entry_price,
            stop=trade_plan.stop_loss_price,
            target=trade_plan.take_profit_price,
        )

    # ------------------------------------------------------------------
    # Position monitoring
    # ------------------------------------------------------------------

    async def monitor_positions(self) -> None:
        """Check all open positions for stop-loss, take-profit, trailing stops, and time expiry."""
        log = logger.bind(trader=self.trader_name)

        positions_to_close: list[tuple[Position, CloseReason]] = []

        for trade in list(self.portfolio.active_trades):
            if trade.status != TradeStatus.OPEN or trade.position is None:
                continue

            pos = trade.position
            now = datetime.utcnow()

            # Update current price from executor (best-effort)
            try:
                balance = await self.executor.get_account_balance()
            except Exception:
                pass

            # Stop-loss check
            if pos.stop_loss_price is not None and pos.current_price is not None:
                if pos.direction == Direction.BUY and pos.current_price <= pos.stop_loss_price:
                    positions_to_close.append((pos, CloseReason.STOP_LOSS))
                    continue
                if pos.direction == Direction.SHORT and pos.current_price >= pos.stop_loss_price:
                    positions_to_close.append((pos, CloseReason.STOP_LOSS))
                    continue

            # Take-profit check
            if pos.take_profit_price is not None and pos.current_price is not None:
                if pos.direction == Direction.BUY and pos.current_price >= pos.take_profit_price:
                    positions_to_close.append((pos, CloseReason.TAKE_PROFIT))
                    continue
                if pos.direction == Direction.SHORT and pos.current_price <= pos.take_profit_price:
                    positions_to_close.append((pos, CloseReason.TAKE_PROFIT))
                    continue

            # Time expiry check
            if trade.expiry_at is not None and now >= trade.expiry_at:
                positions_to_close.append((pos, CloseReason.TIME_EXPIRY))
                continue

        # Execute closures
        for pos, reason in positions_to_close:
            try:
                closing_order = await self.executor.close_position(pos, reason)
                self.order_manager.submit_order(closing_order)

                # Find and update the trade
                for trade in self.portfolio.active_trades:
                    if trade.position and trade.position.id == pos.id:
                        trade.status = TradeStatus.CLOSED
                        trade.close_reason = reason
                        trade.closed_at = datetime.utcnow()
                        trade.orders.append(closing_order)

                        # Calculate P&L
                        if pos.current_price is not None:
                            if pos.direction == Direction.BUY:
                                pnl = (pos.current_price - pos.entry_price) * pos.quantity
                            else:
                                pnl = (pos.entry_price - pos.current_price) * pos.quantity
                            pnl *= pos.leverage
                            trade.realized_pnl = pnl
                            trade.net_pnl = pnl - trade.fees_paid

                            # Update monitors
                            self.pace_monitor.record_trade(trade.net_pnl)
                            self.frequency_limiter.record_trade(won=trade.net_pnl > 0)
                            self.drawdown_monitor.update(
                                self.portfolio.current_state.total_balance + pnl
                            )

                        # Move to history
                        self.portfolio.active_trades.remove(trade)
                        self.portfolio.trade_history.append(trade)
                        self.portfolio.current_state.open_position_count -= 1
                        break

                log.info(
                    "position_closed",
                    position_id=pos.id,
                    reason=reason.value,
                    symbol=pos.symbol,
                )
            except Exception:
                log.exception("position_close_failed", position_id=pos.id)

    # ------------------------------------------------------------------
    # Helper: convert Opportunity to NormalizedSignal for risk manager
    # ------------------------------------------------------------------

    @staticmethod
    def _opportunity_to_signal(opp: Opportunity) -> Any:
        """Convert an Opportunity into a NormalizedSignal for risk checks."""
        from packages.core.models import NormalizedSignal

        return NormalizedSignal(
            market=opp.market,
            symbol=opp.symbol,
            direction=Direction.BUY,  # Default; analyst overrides
            normalized_confidence=opp.confidence,
            expected_return=opp.estimated_edge,
        )

    # ------------------------------------------------------------------
    # Abstract methods for subclasses
    # ------------------------------------------------------------------

    @abstractmethod
    async def collect_market_data(self) -> list[MarketSnapshot]:
        """Gather market data from all configured feeds.

        Returns a list of :class:`MarketSnapshot` objects representing
        the current state of all tracked instruments.
        """

    @abstractmethod
    def build_full_context(self, opportunity: Opportunity) -> dict[str, Any]:
        """Assemble the full context dictionary for deep analyst evaluation.

        The returned dict should include keys like:
        - ``portfolio_state``: current portfolio as dict
        - ``recent_trades``: list of recent trade result dicts
        - ``market_conditions``: current market regime info
        - ``risk_limits``: applicable safety rails as dict
        - ``available_balance``: float
        - ``max_position_pct``: float
        """

    # ------------------------------------------------------------------
    # Run loop
    # ------------------------------------------------------------------

    async def start(self, interval_seconds: float | None = None) -> None:
        """Start the continuous trading loop.

        Parameters
        ----------
        interval_seconds:
            Seconds between cycles.  Defaults to the screener interval
            from trader config (converted from minutes).
        """
        interval = interval_seconds or (self.trader_config.screener_interval_minutes * 60)
        self._running = True

        logger.info(
            "trader_starting",
            trader=self.trader_name,
            market=self.market.value,
            interval_seconds=interval,
        )

        while self._running:
            try:
                await self.run_cycle()
            except Exception:
                logger.exception("trading_cycle_error", trader=self.trader_name)

            await asyncio.sleep(interval)

    async def stop(self) -> None:
        """Signal the trading loop to stop after the current cycle."""
        self._running = False
        logger.info("trader_stopping", trader=self.trader_name)

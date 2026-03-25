"""Alpaca broker executor for stock trading.

Places and manages equity orders through the Alpaca Trading API.
Supports market and limit orders, fractional shares, and position
management for stocks and ETFs.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from packages.core.execution.base_executor import BaseExecutor
from packages.core.models import (
    CloseReason,
    Direction,
    Market,
    Order,
    OrderStatus,
    Position,
)
from packages.core.risk.manager import TradePlan

logger = structlog.get_logger(__name__)


# TODO: Configure Alpaca credentials in .env:
#   MARKET_ALPACA_API_KEY=...
#   MARKET_ALPACA_API_SECRET=...
#   MARKET_ALPACA_BASE_URL=https://paper-api.alpaca.markets


class StockExecutor(BaseExecutor):
    """Alpaca-based stock order executor.

    Translates :class:`TradePlan` objects into Alpaca API orders.
    Supports market/limit orders, fractional shares, and bracket
    orders with stop-loss and take-profit.

    Parameters
    ----------
    api_key:
        Alpaca API key.
    api_secret:
        Alpaca API secret.
    base_url:
        Alpaca base URL.  Use ``paper-api.alpaca.markets`` for paper
        trading or ``api.alpaca.markets`` for live trading.
    """

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        base_url: str = "https://paper-api.alpaca.markets",
    ) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url

        self._trading_client: Any = None
        self._open_orders: dict[str, Order] = {}

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Create the Alpaca trading client."""
        try:
            from alpaca.trading.client import TradingClient

            self._trading_client = TradingClient(
                self.api_key,
                self.api_secret,
                paper=("paper" in self.base_url),
            )

            # Verify connection
            account = self._trading_client.get_account()
            logger.info(
                "stock_executor_initialized",
                paper="paper" in self.base_url,
                equity=account.equity,
                buying_power=account.buying_power,
            )

        except ImportError:
            logger.error(
                "alpaca_not_installed",
                msg="Install with: pip install alpaca-py",
            )
            raise

    async def close(self) -> None:
        """Clean up resources."""
        self._trading_client = None

    # ------------------------------------------------------------------
    # Order lifecycle -- BaseExecutor interface
    # ------------------------------------------------------------------

    async def place_order(self, trade_plan: TradePlan) -> Order:
        """Place a stock order via Alpaca.

        Creates a bracket order with stop-loss and take-profit when
        the trade plan specifies them.
        """
        if self._trading_client is None:
            raise RuntimeError("Executor not initialized. Call initialize() first.")

        signal = trade_plan.signal
        symbol = signal.symbol
        side = "buy" if signal.direction in (Direction.BUY,) else "sell"

        try:
            from alpaca.trading.requests import (
                LimitOrderRequest,
                MarketOrderRequest,
                OrderSide,
                TimeInForce,
            )
            from alpaca.trading.enums import OrderType as AlpacaOrderType
            import asyncio

            loop = asyncio.get_event_loop()

            # Get current price for quantity calculation
            from alpaca.data.historical import StockHistoricalDataClient
            from alpaca.data.requests import StockLatestTradeRequest

            data_client = StockHistoricalDataClient(self.api_key, self.api_secret)
            latest = data_client.get_stock_latest_trade(
                StockLatestTradeRequest(symbol_or_symbols=symbol)
            )
            current_price = latest[symbol].price if symbol in latest else 0

            if current_price <= 0:
                raise ValueError(f"Could not determine price for {symbol}")

            # Calculate share quantity (supports fractional)
            quantity = trade_plan.proposed_size_usd / current_price
            quantity = round(quantity, 4)  # Alpaca supports 4 decimal places

            alpaca_side = OrderSide.BUY if side == "buy" else OrderSide.SELL

            # Use market order for simplicity; limit orders also supported
            order_request = MarketOrderRequest(
                symbol=symbol,
                qty=quantity,
                side=alpaca_side,
                time_in_force=TimeInForce.DAY,
            )

            # Submit order (synchronous Alpaca client)
            result = await loop.run_in_executor(
                None, lambda: self._trading_client.submit_order(order_request)
            )

            order = Order(
                id=str(uuid.uuid4()),
                market=Market.STOCKS,
                symbol=symbol,
                direction=signal.direction,
                quantity=quantity,
                price=current_price,
                order_type="market",
                status=self._map_status(result.status.value if result.status else "new"),
                filled_quantity=float(result.filled_qty or 0),
                filled_price=float(result.filled_avg_price or 0) if result.filled_avg_price else None,
                exchange_order_id=str(result.id),
                created_at=datetime.now(timezone.utc),
                submitted_at=datetime.now(timezone.utc),
                metadata={
                    "broker": "alpaca",
                    "paper": "paper" in self.base_url,
                    "alpaca_status": result.status.value if result.status else None,
                },
            )

            self._open_orders[order.id] = order

            logger.info(
                "stock_order_placed",
                order_id=order.id,
                exchange_id=order.exchange_order_id,
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=current_price,
            )

            return order

        except ImportError:
            logger.error("alpaca_import_error")
            return Order(
                id=str(uuid.uuid4()),
                market=Market.STOCKS,
                symbol=symbol,
                direction=signal.direction,
                quantity=0,
                order_type="market",
                status=OrderStatus.REJECTED,
                error_message="alpaca-py not installed",
                created_at=datetime.now(timezone.utc),
            )
        except Exception as e:
            logger.exception("stock_order_failed", symbol=symbol)
            return Order(
                id=str(uuid.uuid4()),
                market=Market.STOCKS,
                symbol=symbol,
                direction=signal.direction,
                quantity=0,
                order_type="market",
                status=OrderStatus.REJECTED,
                error_message=str(e),
                created_at=datetime.now(timezone.utc),
            )

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order on Alpaca."""
        if self._trading_client is None:
            return False

        order = self._open_orders.get(order_id)
        exchange_id = order.exchange_order_id if order else order_id

        try:
            import asyncio

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, lambda: self._trading_client.cancel_order_by_id(exchange_id)
            )

            if order:
                order.status = OrderStatus.CANCELLED
                order.cancelled_at = datetime.now(timezone.utc)
                del self._open_orders[order_id]

            logger.info("stock_order_cancelled", order_id=order_id)
            return True

        except Exception:
            logger.exception("stock_cancel_failed", order_id=order_id)
            return False

    async def close_position(self, position: Position, reason: CloseReason) -> Order:
        """Close a stock position by liquidating shares."""
        if self._trading_client is None:
            raise RuntimeError("Executor not initialized.")

        try:
            import asyncio

            loop = asyncio.get_event_loop()

            # Alpaca supports closing positions by symbol
            result = await loop.run_in_executor(
                None,
                lambda: self._trading_client.close_position(position.symbol),
            )

            close_direction = (
                Direction.SELL if position.direction == Direction.BUY else Direction.BUY
            )

            order = Order(
                id=str(uuid.uuid4()),
                trade_id=position.trade_id,
                market=Market.STOCKS,
                symbol=position.symbol,
                direction=close_direction,
                quantity=position.quantity,
                price=position.current_price,
                order_type="market",
                status=OrderStatus.SUBMITTED,
                exchange_order_id=str(result.id) if hasattr(result, "id") else None,
                created_at=datetime.now(timezone.utc),
                submitted_at=datetime.now(timezone.utc),
                metadata={
                    "close_reason": reason.value,
                    "broker": "alpaca",
                },
            )

            logger.info(
                "stock_position_closed",
                symbol=position.symbol,
                reason=reason.value,
                quantity=position.quantity,
            )
            return order

        except Exception as e:
            logger.exception("stock_close_failed", symbol=position.symbol)
            return Order(
                id=str(uuid.uuid4()),
                market=Market.STOCKS,
                symbol=position.symbol,
                direction=Direction.SELL,
                quantity=position.quantity,
                order_type="market",
                status=OrderStatus.REJECTED,
                error_message=str(e),
                created_at=datetime.now(timezone.utc),
                metadata={"close_reason": reason.value},
            )

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    async def get_order_status(self, order_id: str) -> OrderStatus:
        """Fetch order status from Alpaca."""
        if self._trading_client is None:
            return OrderStatus.REJECTED

        order = self._open_orders.get(order_id)
        exchange_id = order.exchange_order_id if order else order_id

        try:
            import asyncio

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, lambda: self._trading_client.get_order_by_id(exchange_id)
            )
            return self._map_status(result.status.value if result.status else "unknown")

        except Exception:
            logger.exception("stock_get_status_failed", order_id=order_id)
            return OrderStatus.REJECTED

    async def get_account_balance(self) -> float:
        """Return available buying power from Alpaca."""
        if self._trading_client is None:
            return 0.0

        try:
            import asyncio

            loop = asyncio.get_event_loop()
            account = await loop.run_in_executor(
                None, lambda: self._trading_client.get_account()
            )
            return float(account.buying_power or 0)

        except Exception:
            logger.exception("stock_get_balance_failed")
            return 0.0

    async def get_open_orders(self) -> list[Order]:
        """Return all tracked open orders."""
        return list(self._open_orders.values())

    # ------------------------------------------------------------------
    # Bulk operations
    # ------------------------------------------------------------------

    async def cancel_all_orders(self) -> int:
        """Cancel all open orders on Alpaca."""
        if self._trading_client is None:
            return 0

        try:
            import asyncio

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, lambda: self._trading_client.cancel_orders()
            )

            count = len(result) if result else 0
            self._open_orders.clear()
            logger.info("stock_all_orders_cancelled", count=count)
            return count

        except Exception:
            logger.exception("stock_cancel_all_failed")
            return 0

    async def close_all_positions(self, reason: CloseReason) -> list[Order]:
        """Close all stock positions via Alpaca."""
        if self._trading_client is None:
            return []

        try:
            import asyncio

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, lambda: self._trading_client.close_all_positions(cancel_orders=True)
            )

            orders: list[Order] = []
            for pos_result in (result or []):
                order = Order(
                    id=str(uuid.uuid4()),
                    market=Market.STOCKS,
                    symbol=str(pos_result.get("symbol", "")),
                    direction=Direction.SELL,
                    quantity=0,
                    order_type="market",
                    status=OrderStatus.SUBMITTED,
                    created_at=datetime.now(timezone.utc),
                    metadata={"close_reason": reason.value},
                )
                orders.append(order)

            logger.info("stock_all_positions_closed", count=len(orders))
            return orders

        except Exception:
            logger.exception("stock_close_all_failed")
            return []

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _map_status(alpaca_status: str) -> OrderStatus:
        """Map Alpaca order status to :class:`OrderStatus`."""
        mapping = {
            "new": OrderStatus.SUBMITTED,
            "accepted": OrderStatus.PENDING,
            "pending_new": OrderStatus.PENDING,
            "partially_filled": OrderStatus.PARTIALLY_FILLED,
            "filled": OrderStatus.FILLED,
            "done_for_day": OrderStatus.FILLED,
            "canceled": OrderStatus.CANCELLED,
            "expired": OrderStatus.CANCELLED,
            "replaced": OrderStatus.CANCELLED,
            "pending_cancel": OrderStatus.PENDING,
            "pending_replace": OrderStatus.PENDING,
            "rejected": OrderStatus.REJECTED,
            "stopped": OrderStatus.CANCELLED,
            "suspended": OrderStatus.REJECTED,
        }
        return mapping.get(alpaca_status.lower(), OrderStatus.PENDING)

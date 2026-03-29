"""Alpaca broker executor for stock trading.

Places and manages orders on the Alpaca brokerage API.
Supports market and limit orders for equities and ETFs.
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
    """Alpaca brokerage order executor for equities and ETFs.

    Translates :class:`TradePlan` objects into Alpaca orders,
    manages order lifecycle, and tracks positions.

    Parameters
    ----------
    api_key:
        Alpaca API key.
    api_secret:
        Alpaca API secret.
    base_url:
        Alpaca base URL (paper or live).
    default_order_type:
        Default order type: ``"market"`` or ``"limit"``.
    """

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        base_url: str = "https://paper-api.alpaca.markets",
        default_order_type: str = "market",
    ) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url
        self.default_order_type = default_order_type

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

            logger.info(
                "stock_executor_initialized",
                paper="paper" in self.base_url,
            )

        except ImportError:
            logger.error(
                "alpaca_not_installed",
                msg="pip install alpaca-py",
            )
            raise

    async def close(self) -> None:
        """Clean up resources."""
        self._trading_client = None

    # ------------------------------------------------------------------
    # Order lifecycle -- BaseExecutor interface
    # ------------------------------------------------------------------

    async def place_order(self, trade_plan: TradePlan) -> Order:
        """Place an order on Alpaca based on *trade_plan*.

        Translates the risk-approved plan into Alpaca order parameters
        and submits the order.
        """
        if self._trading_client is None:
            raise RuntimeError("Executor not initialized. Call initialize() first.")

        signal = trade_plan.signal
        symbol = signal.symbol
        side = "buy" if signal.direction == Direction.BUY else "sell"
        order_type = self.default_order_type

        try:
            from alpaca.trading.requests import MarketOrderRequest
            from alpaca.trading.enums import OrderSide, TimeInForce

            alpaca_side = OrderSide.BUY if side == "buy" else OrderSide.SELL

            # Calculate notional (dollar amount) -- Alpaca supports fractional shares
            notional = trade_plan.proposed_size_usd

            request = MarketOrderRequest(
                symbol=symbol,
                notional=round(notional, 2),
                side=alpaca_side,
                time_in_force=TimeInForce.DAY,
            )

            result = self._trading_client.submit_order(request)

            order = Order(
                id=str(uuid.uuid4()),
                market=Market.STOCKS,
                symbol=symbol,
                direction=signal.direction,
                quantity=float(result.qty or result.notional or notional),
                price=float(result.filled_avg_price) if result.filled_avg_price else 0.0,
                order_type=order_type,
                status=self._map_order_status(str(result.status)),
                filled_quantity=float(result.filled_qty) if result.filled_qty else 0.0,
                filled_price=float(result.filled_avg_price) if result.filled_avg_price else None,
                fees=0.0,  # Alpaca is commission-free
                exchange_order_id=str(result.id),
                created_at=datetime.now(timezone.utc),
                submitted_at=datetime.now(timezone.utc),
                metadata={
                    "broker": "alpaca",
                    "order_type": order_type,
                    "notional": notional,
                },
            )

            self._open_orders[order.id] = order

            logger.info(
                "stock_order_placed",
                order_id=order.id,
                exchange_id=order.exchange_order_id,
                symbol=symbol,
                side=side,
                notional=notional,
                type=order_type,
            )

            return order

        except ImportError:
            logger.error("alpaca_import_error")
            return Order(
                id=str(uuid.uuid4()),
                market=Market.STOCKS,
                symbol=symbol,
                direction=signal.direction,
                quantity=trade_plan.proposed_size_usd,
                order_type=order_type,
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
                quantity=trade_plan.proposed_size_usd,
                order_type=order_type,
                status=OrderStatus.REJECTED,
                error_message=str(e),
                created_at=datetime.now(timezone.utc),
            )

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order on Alpaca."""
        if self._trading_client is None:
            return False

        order = self._open_orders.get(order_id)
        exchange_order_id = order.exchange_order_id if order else order_id

        if not exchange_order_id:
            logger.warning("cancel_order_no_exchange_id", order_id=order_id)
            return False

        try:
            self._trading_client.cancel_order_by_id(exchange_order_id)
            if order:
                order.status = OrderStatus.CANCELLED
                order.cancelled_at = datetime.now(timezone.utc)
                del self._open_orders[order_id]
            logger.info("stock_order_cancelled", order_id=order_id)
            return True
        except Exception:
            logger.exception("cancel_stock_order_failed", order_id=order_id)
            return False

    async def close_position(self, position: Position, reason: CloseReason) -> Order:
        """Close an open stock position by liquidating it via Alpaca."""
        if self._trading_client is None:
            raise RuntimeError("Executor not initialized.")

        try:
            result = self._trading_client.close_position(position.symbol)

            order = Order(
                id=str(uuid.uuid4()),
                trade_id=position.trade_id,
                market=Market.STOCKS,
                symbol=position.symbol,
                direction=Direction.SELL if position.direction == Direction.BUY else Direction.BUY,
                quantity=position.quantity,
                price=float(result.filled_avg_price) if hasattr(result, "filled_avg_price") and result.filled_avg_price else 0.0,
                order_type="market",
                status=OrderStatus.FILLED,
                filled_quantity=position.quantity,
                filled_price=float(result.filled_avg_price) if hasattr(result, "filled_avg_price") and result.filled_avg_price else None,
                fees=0.0,
                exchange_order_id=str(result.id) if hasattr(result, "id") else None,
                created_at=datetime.now(timezone.utc),
                submitted_at=datetime.now(timezone.utc),
                filled_at=datetime.now(timezone.utc),
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
            logger.exception("stock_close_position_failed", symbol=position.symbol)
            return Order(
                id=str(uuid.uuid4()),
                market=Market.STOCKS,
                symbol=position.symbol,
                direction=Direction.SELL if position.direction == Direction.BUY else Direction.BUY,
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
        """Fetch the current status of an order from Alpaca."""
        if self._trading_client is None:
            return OrderStatus.REJECTED

        order = self._open_orders.get(order_id)
        if order is None or order.exchange_order_id is None:
            return OrderStatus.REJECTED

        try:
            result = self._trading_client.get_order_by_id(order.exchange_order_id)
            return self._map_order_status(str(result.status))
        except Exception:
            logger.exception("get_stock_order_status_failed", order_id=order_id)
            return OrderStatus.REJECTED

    async def get_account_balance(self) -> float:
        """Return the available cash balance from Alpaca."""
        if self._trading_client is None:
            return 0.0

        try:
            account = self._trading_client.get_account()
            return float(account.cash)
        except Exception:
            logger.exception("get_stock_balance_failed")
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
            self._trading_client.cancel_orders()
            count = len(self._open_orders)
            self._open_orders.clear()
            logger.info("all_stock_orders_cancelled", count=count)
            return count
        except Exception:
            logger.exception("cancel_all_stock_orders_failed")
            return 0

    async def close_all_positions(self, reason: CloseReason) -> list[Order]:
        """Liquidate all open stock positions via Alpaca."""
        if self._trading_client is None:
            return []

        orders: list[Order] = []
        try:
            self._trading_client.close_all_positions(cancel_orders=True)
            logger.info("all_stock_positions_closed", reason=reason.value)
        except Exception:
            logger.exception("close_all_stock_positions_failed")

        return orders

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _map_order_status(alpaca_status: str) -> OrderStatus:
        """Map Alpaca status strings to :class:`OrderStatus`."""
        mapping = {
            "new": OrderStatus.PENDING,
            "accepted": OrderStatus.PENDING,
            "pending_new": OrderStatus.PENDING,
            "accepted_for_bidding": OrderStatus.PENDING,
            "filled": OrderStatus.FILLED,
            "partially_filled": OrderStatus.PARTIALLY_FILLED,
            "cancelled": OrderStatus.CANCELLED,
            "canceled": OrderStatus.CANCELLED,
            "expired": OrderStatus.CANCELLED,
            "rejected": OrderStatus.REJECTED,
            "pending_cancel": OrderStatus.PENDING,
            "pending_replace": OrderStatus.PENDING,
            "stopped": OrderStatus.CANCELLED,
            "suspended": OrderStatus.CANCELLED,
        }
        return mapping.get(alpaca_status.lower(), OrderStatus.PENDING)

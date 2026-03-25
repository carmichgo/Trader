"""CCXT-based order executor for crypto exchanges.

Places and manages orders on Binance, Bybit, and other CCXT-supported
exchanges.  Supports market and limit orders, leveraged positions,
and position closing.
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


class CryptoExecutor(BaseExecutor):
    """Crypto exchange executor backed by CCXT.

    Translates :class:`TradePlan` objects into exchange orders,
    manages order lifecycle, and tracks positions.

    Parameters
    ----------
    exchange_id:
        CCXT exchange identifier (e.g. ``"binance"``, ``"bybit"``).
    api_key:
        Exchange API key.
    api_secret:
        Exchange API secret.
    sandbox:
        If ``True``, use the exchange's testnet/sandbox mode.
    default_order_type:
        Default order type: ``"limit"`` or ``"market"``.
    """

    def __init__(
        self,
        exchange_id: str = "binance",
        api_key: str = "",
        api_secret: str = "",
        sandbox: bool = True,
        default_order_type: str = "limit",
    ) -> None:
        self.exchange_id = exchange_id
        self.api_key = api_key
        self.api_secret = api_secret
        self.sandbox = sandbox
        self.default_order_type = default_order_type

        self._exchange: Any = None
        self._open_orders: dict[str, Order] = {}

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Create the CCXT exchange instance and load markets."""
        try:
            import ccxt.async_support as ccxt_async

            exchange_class = getattr(ccxt_async, self.exchange_id, None)
            if exchange_class is None:
                raise ValueError(f"Unsupported exchange: {self.exchange_id}")

            config: dict[str, Any] = {
                "apiKey": self.api_key,
                "secret": self.api_secret,
                "enableRateLimit": True,
                "options": {"defaultType": "future"},
            }

            if self.sandbox:
                config["sandbox"] = True

            self._exchange = exchange_class(config)
            await self._exchange.load_markets()

            logger.info(
                "crypto_executor_initialized",
                exchange=self.exchange_id,
                sandbox=self.sandbox,
            )
        except ImportError:
            logger.error("ccxt_not_installed", msg="pip install ccxt")
            raise

    async def close(self) -> None:
        """Close the exchange connection."""
        if self._exchange is not None:
            await self._exchange.close()
            self._exchange = None

    # ------------------------------------------------------------------
    # Order lifecycle -- BaseExecutor interface
    # ------------------------------------------------------------------

    async def place_order(self, trade_plan: TradePlan) -> Order:
        """Place an order on the exchange based on *trade_plan*.

        Translates the risk-approved plan into exchange parameters,
        sets leverage if needed, and submits the order.
        """
        if self._exchange is None:
            raise RuntimeError("Executor not initialized. Call initialize() first.")

        signal = trade_plan.signal
        symbol = signal.symbol
        side = "buy" if signal.direction in (Direction.BUY,) else "sell"
        order_type = self.default_order_type

        # Calculate quantity from USD size and current price
        ticker = await self._exchange.fetch_ticker(symbol)
        current_price = ticker["last"]
        quantity = trade_plan.proposed_size_usd / current_price

        # Set leverage if > 1
        if trade_plan.proposed_leverage > 1.0:
            try:
                await self._exchange.set_leverage(
                    int(trade_plan.proposed_leverage), symbol
                )
                logger.info(
                    "leverage_set",
                    symbol=symbol,
                    leverage=trade_plan.proposed_leverage,
                )
            except Exception:
                logger.exception("set_leverage_failed", symbol=symbol)

        # Place the order
        try:
            params: dict[str, Any] = {}

            # Add stop-loss and take-profit as exchange-native if supported
            if trade_plan.stop_loss_pct > 0:
                stop_price = (
                    current_price * (1 - trade_plan.stop_loss_pct)
                    if side == "buy"
                    else current_price * (1 + trade_plan.stop_loss_pct)
                )
                params["stopLoss"] = {"triggerPrice": stop_price}

            if trade_plan.take_profit_pct > 0:
                tp_price = (
                    current_price * (1 + trade_plan.take_profit_pct)
                    if side == "buy"
                    else current_price * (1 - trade_plan.take_profit_pct)
                )
                params["takeProfit"] = {"triggerPrice": tp_price}

            if order_type == "market":
                result = await self._exchange.create_order(
                    symbol, "market", side, quantity, params=params
                )
            else:
                result = await self._exchange.create_order(
                    symbol, "limit", side, quantity, current_price, params=params
                )

            order = Order(
                id=str(uuid.uuid4()),
                trade_id=None,
                market=Market.CRYPTO,
                symbol=symbol,
                direction=signal.direction,
                quantity=result.get("amount", quantity),
                price=result.get("price", current_price),
                order_type=order_type,
                status=self._map_order_status(result.get("status", "open")),
                filled_quantity=result.get("filled", 0.0),
                filled_price=result.get("average"),
                fees=result.get("fee", {}).get("cost", 0.0) if result.get("fee") else 0.0,
                exchange_order_id=result.get("id"),
                created_at=datetime.now(timezone.utc),
                submitted_at=datetime.now(timezone.utc),
                metadata={
                    "exchange": self.exchange_id,
                    "raw_response": str(result.get("info", {}))[:500],
                },
            )

            self._open_orders[order.id] = order

            logger.info(
                "order_placed",
                order_id=order.id,
                exchange_id=order.exchange_order_id,
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=current_price,
                type=order_type,
            )

            return order

        except Exception as e:
            logger.exception("place_order_failed", symbol=symbol, side=side)
            # Return a rejected order
            return Order(
                id=str(uuid.uuid4()),
                market=Market.CRYPTO,
                symbol=symbol,
                direction=signal.direction,
                quantity=quantity,
                price=current_price,
                order_type=order_type,
                status=OrderStatus.REJECTED,
                error_message=str(e),
                created_at=datetime.now(timezone.utc),
            )

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order on the exchange."""
        if self._exchange is None:
            return False

        # Find the order to get the exchange order ID and symbol
        order = self._open_orders.get(order_id)
        exchange_order_id = order.exchange_order_id if order else order_id
        symbol = order.symbol if order else None

        if not exchange_order_id:
            logger.warning("cancel_order_no_exchange_id", order_id=order_id)
            return False

        try:
            await self._exchange.cancel_order(exchange_order_id, symbol)
            if order:
                order.status = OrderStatus.CANCELLED
                order.cancelled_at = datetime.now(timezone.utc)
                del self._open_orders[order_id]
            logger.info("order_cancelled", order_id=order_id)
            return True
        except Exception:
            logger.exception("cancel_order_failed", order_id=order_id)
            return False

    async def close_position(self, position: Position, reason: CloseReason) -> Order:
        """Close an open position by submitting a counter-order."""
        if self._exchange is None:
            raise RuntimeError("Executor not initialized.")

        # Counter-direction
        close_side = "sell" if position.direction == Direction.BUY else "buy"

        try:
            result = await self._exchange.create_order(
                position.symbol,
                "market",
                close_side,
                position.quantity,
                params={"reduceOnly": True},
            )

            order = Order(
                id=str(uuid.uuid4()),
                trade_id=position.trade_id,
                market=Market.CRYPTO,
                symbol=position.symbol,
                direction=Direction.SELL if close_side == "sell" else Direction.BUY,
                quantity=result.get("amount", position.quantity),
                price=result.get("average") or result.get("price"),
                order_type="market",
                status=self._map_order_status(result.get("status", "closed")),
                filled_quantity=result.get("filled", position.quantity),
                filled_price=result.get("average"),
                fees=result.get("fee", {}).get("cost", 0.0) if result.get("fee") else 0.0,
                exchange_order_id=result.get("id"),
                created_at=datetime.now(timezone.utc),
                submitted_at=datetime.now(timezone.utc),
                filled_at=datetime.now(timezone.utc),
                metadata={
                    "close_reason": reason.value,
                    "exchange": self.exchange_id,
                },
            )

            logger.info(
                "position_closed",
                symbol=position.symbol,
                reason=reason.value,
                quantity=position.quantity,
                close_price=order.filled_price,
            )
            return order

        except Exception as e:
            logger.exception("close_position_failed", symbol=position.symbol)
            return Order(
                id=str(uuid.uuid4()),
                market=Market.CRYPTO,
                symbol=position.symbol,
                direction=Direction.SELL if close_side == "sell" else Direction.BUY,
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
        """Fetch the current status of an order from the exchange."""
        if self._exchange is None:
            return OrderStatus.REJECTED

        order = self._open_orders.get(order_id)
        if order is None or order.exchange_order_id is None:
            return OrderStatus.REJECTED

        try:
            result = await self._exchange.fetch_order(
                order.exchange_order_id, order.symbol
            )
            return self._map_order_status(result.get("status", "unknown"))
        except Exception:
            logger.exception("get_order_status_failed", order_id=order_id)
            return OrderStatus.REJECTED

    async def get_account_balance(self) -> float:
        """Return the available USDT balance."""
        if self._exchange is None:
            return 0.0

        try:
            balance = await self._exchange.fetch_balance()
            usdt = balance.get("USDT", balance.get("free", {}))
            if isinstance(usdt, dict):
                return float(usdt.get("free", 0.0))
            return float(usdt) if usdt else 0.0
        except Exception:
            logger.exception("get_balance_failed")
            return 0.0

    async def get_open_orders(self) -> list[Order]:
        """Return all tracked open orders."""
        return list(self._open_orders.values())

    # ------------------------------------------------------------------
    # Bulk operations
    # ------------------------------------------------------------------

    async def cancel_all_orders(self) -> int:
        """Cancel all open orders on the exchange."""
        if self._exchange is None:
            return 0

        cancelled = 0
        for order_id in list(self._open_orders.keys()):
            if await self.cancel_order(order_id):
                cancelled += 1

        logger.info("all_orders_cancelled", count=cancelled)
        return cancelled

    async def close_all_positions(self, reason: CloseReason) -> list[Order]:
        """Close all open positions on the exchange."""
        if self._exchange is None:
            return []

        orders: list[Order] = []
        try:
            positions = await self._exchange.fetch_positions()
            for pos_data in positions:
                contracts = abs(float(pos_data.get("contracts", 0)))
                if contracts <= 0:
                    continue

                side = pos_data.get("side", "long")
                symbol = pos_data.get("symbol", "")
                direction = Direction.BUY if side == "long" else Direction.SHORT

                position = Position(
                    id=str(uuid.uuid4()),
                    market=Market.CRYPTO,
                    symbol=symbol,
                    direction=direction,
                    quantity=contracts,
                    entry_price=float(pos_data.get("entryPrice", 0)),
                    current_price=float(pos_data.get("markPrice", 0)),
                    leverage=float(pos_data.get("leverage", 1)),
                )

                order = await self.close_position(position, reason)
                orders.append(order)

        except Exception:
            logger.exception("close_all_positions_failed")

        return orders

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _map_order_status(exchange_status: str) -> OrderStatus:
        """Map exchange-specific status strings to :class:`OrderStatus`."""
        mapping = {
            "open": OrderStatus.PENDING,
            "closed": OrderStatus.FILLED,
            "canceled": OrderStatus.CANCELLED,
            "cancelled": OrderStatus.CANCELLED,
            "expired": OrderStatus.CANCELLED,
            "rejected": OrderStatus.REJECTED,
            "partially_filled": OrderStatus.PARTIALLY_FILLED,
        }
        return mapping.get(exchange_status.lower(), OrderStatus.PENDING)

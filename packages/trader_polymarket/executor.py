"""Polymarket CLOB order executor.

Places and manages orders on Polymarket's Central Limit Order Book
for prediction market trading.
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


# TODO: Configure Polymarket credentials in .env:
#   POLYMARKET_API_KEY=...
#   POLYMARKET_API_SECRET=...
#   POLYMARKET_FUNDER_ADDRESS=...
#   POLYMARKET_PRIVATE_KEY=...  (for transaction signing)


class PolymarketExecutor(BaseExecutor):
    """Polymarket CLOB order executor.

    Places limit and market orders on prediction markets through
    the Polymarket CLOB API.  Handles order signing, submission,
    and lifecycle tracking.

    Parameters
    ----------
    api_key:
        Polymarket API key.
    api_secret:
        Polymarket API secret for HMAC signing.
    funder_address:
        Ethereum address used for funding.
    private_key:
        Private key for transaction signing on Polygon.
    base_url:
        CLOB API base URL.
    """

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        funder_address: str = "",
        private_key: str = "",
        base_url: str = "https://clob.polymarket.com",
    ) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.funder_address = funder_address
        self.private_key = private_key
        self.base_url = base_url

        self._clob_client: Any = None
        self._open_orders: dict[str, Order] = {}

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Create the Polymarket CLOB client."""
        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import ApiCreds

            creds = ApiCreds(
                api_key=self.api_key,
                api_secret=self.api_secret,
                api_passphrase="",  # Polymarket uses key+secret
            )

            self._clob_client = ClobClient(
                self.base_url,
                key=self.private_key,
                chain_id=137,  # Polygon mainnet
                creds=creds,
                funder=self.funder_address,
            )

            logger.info("polymarket_executor_initialized")

        except ImportError:
            logger.error(
                "py_clob_client_not_installed",
                msg="pip install py-clob-client",
            )
            raise

    async def close(self) -> None:
        """Clean up resources."""
        self._clob_client = None

    # ------------------------------------------------------------------
    # Order lifecycle -- BaseExecutor interface
    # ------------------------------------------------------------------

    async def place_order(self, trade_plan: TradePlan) -> Order:
        """Place an order on the Polymarket CLOB.

        Polymarket orders are for shares of YES or NO outcomes at a
        given price (0.00-1.00).  Position size is in USD.
        """
        if self._clob_client is None:
            raise RuntimeError("Executor not initialized. Call initialize() first.")

        signal = trade_plan.signal
        symbol = signal.symbol  # condition_id
        side = "BUY" if signal.direction == Direction.BUY else "SELL"
        size_usd = trade_plan.proposed_size_usd

        try:
            from py_clob_client.clob_types import OrderArgs
            import asyncio

            loop = asyncio.get_event_loop()

            # Build order arguments
            # Price comes from the signal metadata or defaults to midpoint
            price = signal.metadata.get("price", 0.50)

            # Get the token ID for the YES outcome
            token_id = signal.metadata.get("token_id", symbol)

            order_args = OrderArgs(
                price=price,
                size=size_usd / price if price > 0 else size_usd,
                side=side,
                token_id=token_id,
            )

            # Create signed order (synchronous call)
            signed_order = await loop.run_in_executor(
                None,
                lambda: self._clob_client.create_order(order_args),
            )

            # Submit the order
            result = await loop.run_in_executor(
                None,
                lambda: self._clob_client.post_order(signed_order),
            )

            exchange_order_id = result.get("orderID", "") if isinstance(result, dict) else str(result)

            order = Order(
                id=str(uuid.uuid4()),
                market=Market.POLYMARKET,
                symbol=symbol,
                direction=signal.direction,
                quantity=size_usd / price if price > 0 else size_usd,
                price=price,
                order_type="limit",
                status=OrderStatus.SUBMITTED,
                exchange_order_id=exchange_order_id,
                created_at=datetime.now(timezone.utc),
                submitted_at=datetime.now(timezone.utc),
                metadata={
                    "token_id": token_id,
                    "side": side,
                    "size_usd": size_usd,
                },
            )

            self._open_orders[order.id] = order

            logger.info(
                "polymarket_order_placed",
                order_id=order.id,
                exchange_id=exchange_order_id,
                symbol=symbol,
                side=side,
                price=price,
                size_usd=size_usd,
            )

            return order

        except ImportError:
            logger.error("py_clob_client_import_error")
            return Order(
                id=str(uuid.uuid4()),
                market=Market.POLYMARKET,
                symbol=symbol,
                direction=signal.direction,
                quantity=size_usd,
                order_type="limit",
                status=OrderStatus.REJECTED,
                error_message="py-clob-client not installed",
                created_at=datetime.now(timezone.utc),
            )
        except Exception as e:
            logger.exception("polymarket_order_failed", symbol=symbol)
            return Order(
                id=str(uuid.uuid4()),
                market=Market.POLYMARKET,
                symbol=symbol,
                direction=signal.direction,
                quantity=size_usd,
                order_type="limit",
                status=OrderStatus.REJECTED,
                error_message=str(e),
                created_at=datetime.now(timezone.utc),
            )

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order on Polymarket."""
        if self._clob_client is None:
            return False

        order = self._open_orders.get(order_id)
        if order is None:
            logger.warning("cancel_order_not_found", order_id=order_id)
            return False

        try:
            import asyncio

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self._clob_client.cancel(order.exchange_order_id),
            )

            order.status = OrderStatus.CANCELLED
            order.cancelled_at = datetime.now(timezone.utc)
            del self._open_orders[order_id]

            logger.info("polymarket_order_cancelled", order_id=order_id)
            return True

        except Exception:
            logger.exception("polymarket_cancel_failed", order_id=order_id)
            return False

    async def close_position(self, position: Position, reason: CloseReason) -> Order:
        """Close a Polymarket position by selling shares.

        For prediction markets, closing means selling the shares
        back on the CLOB at the current market price.
        """
        if self._clob_client is None:
            raise RuntimeError("Executor not initialized.")

        close_side = "SELL" if position.direction == Direction.BUY else "BUY"

        try:
            from py_clob_client.clob_types import OrderArgs
            import asyncio

            loop = asyncio.get_event_loop()

            token_id = position.metadata.get("token_id", position.symbol)
            price = position.current_price or 0.50

            order_args = OrderArgs(
                price=price,
                size=position.quantity,
                side=close_side,
                token_id=token_id,
            )

            signed_order = await loop.run_in_executor(
                None, lambda: self._clob_client.create_order(order_args)
            )
            result = await loop.run_in_executor(
                None, lambda: self._clob_client.post_order(signed_order)
            )

            exchange_id = result.get("orderID", "") if isinstance(result, dict) else str(result)

            order = Order(
                id=str(uuid.uuid4()),
                trade_id=position.trade_id,
                market=Market.POLYMARKET,
                symbol=position.symbol,
                direction=Direction.SELL if close_side == "SELL" else Direction.BUY,
                quantity=position.quantity,
                price=price,
                order_type="limit",
                status=OrderStatus.SUBMITTED,
                exchange_order_id=exchange_id,
                created_at=datetime.now(timezone.utc),
                submitted_at=datetime.now(timezone.utc),
                metadata={
                    "close_reason": reason.value,
                    "token_id": token_id,
                },
            )

            logger.info(
                "polymarket_position_closed",
                symbol=position.symbol,
                reason=reason.value,
                quantity=position.quantity,
            )
            return order

        except Exception as e:
            logger.exception("polymarket_close_failed", symbol=position.symbol)
            return Order(
                id=str(uuid.uuid4()),
                market=Market.POLYMARKET,
                symbol=position.symbol,
                direction=Direction.SELL,
                quantity=position.quantity,
                order_type="limit",
                status=OrderStatus.REJECTED,
                error_message=str(e),
                created_at=datetime.now(timezone.utc),
                metadata={"close_reason": reason.value},
            )

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    async def get_order_status(self, order_id: str) -> OrderStatus:
        """Check order status on Polymarket."""
        if self._clob_client is None:
            return OrderStatus.REJECTED

        order = self._open_orders.get(order_id)
        if order is None or order.exchange_order_id is None:
            return OrderStatus.REJECTED

        try:
            import asyncio

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self._clob_client.get_order(order.exchange_order_id),
            )

            status_str = result.get("status", "unknown") if isinstance(result, dict) else "unknown"
            return self._map_status(status_str)

        except Exception:
            logger.exception("polymarket_get_status_failed", order_id=order_id)
            return OrderStatus.REJECTED

    async def get_account_balance(self) -> float:
        """Return available USDC balance on Polymarket."""
        if self._clob_client is None:
            return 0.0

        # TODO: Implement balance check via Polygon USDC contract query
        # or Polymarket balance endpoint.
        logger.debug("polymarket_balance_check_not_implemented")
        return 0.0

    async def get_open_orders(self) -> list[Order]:
        """Return all tracked open orders."""
        return list(self._open_orders.values())

    async def cancel_all_orders(self) -> int:
        """Cancel all open orders."""
        if self._clob_client is None:
            return 0

        try:
            import asyncio

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, lambda: self._clob_client.cancel_all()
            )

            count = len(self._open_orders)
            self._open_orders.clear()
            logger.info("polymarket_all_orders_cancelled", count=count)
            return count

        except Exception:
            logger.exception("polymarket_cancel_all_failed")
            return 0

    async def close_all_positions(self, reason: CloseReason) -> list[Order]:
        """Close all positions by selling shares.

        Note: Polymarket doesn't expose position endpoints directly.
        This relies on tracked positions from the portfolio.
        """
        logger.warning(
            "close_all_positions_limited",
            msg="Polymarket position closing requires portfolio tracking. "
            "Use the trader's portfolio.active_trades for position data.",
        )
        return []

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _map_status(status_str: str) -> OrderStatus:
        """Map Polymarket status strings to :class:`OrderStatus`."""
        mapping = {
            "live": OrderStatus.PENDING,
            "matched": OrderStatus.FILLED,
            "cancelled": OrderStatus.CANCELLED,
            "expired": OrderStatus.CANCELLED,
        }
        return mapping.get(status_str.lower(), OrderStatus.PENDING)

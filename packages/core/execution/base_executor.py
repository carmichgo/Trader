"""Abstract base class for trade execution backends."""

from __future__ import annotations

from abc import ABC, abstractmethod

from packages.core.models import CloseReason, Order, OrderStatus, Position
from packages.core.risk.manager import TradePlan


class BaseExecutor(ABC):
    """Unified interface that every exchange / market executor must implement.

    Concrete subclasses wrap exchange-specific SDKs (e.g. CCXT for crypto,
    Polymarket CLOB client, Alpaca for stocks) behind this common API so
    the rest of the system stays exchange-agnostic.
    """

    # ------------------------------------------------------------------
    # Order lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    async def place_order(self, trade_plan: TradePlan) -> Order:
        """Translate a risk-approved *trade_plan* into an exchange order.

        The implementation must:
        1. Map the plan's direction / size / price to exchange params.
        2. Submit the order to the exchange.
        3. Return an ``Order`` with at least ``exchange_order_id`` populated.
        """

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Request cancellation for a live order.

        Parameters
        ----------
        order_id:
            The internal order id **or** the ``exchange_order_id``.

        Returns
        -------
        bool
            ``True`` if the exchange acknowledged the cancellation.
        """

    @abstractmethod
    async def close_position(self, position: Position, reason: CloseReason) -> Order:
        """Close an open *position* by submitting a counter-order.

        Parameters
        ----------
        position:
            The position to flatten.
        reason:
            Why the position is being closed (stop-loss, take-profit, etc.).

        Returns
        -------
        Order
            The closing order that was placed.
        """

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    @abstractmethod
    async def get_order_status(self, order_id: str) -> OrderStatus:
        """Fetch the current status of *order_id* from the exchange."""

    @abstractmethod
    async def get_account_balance(self) -> float:
        """Return the available (free) account balance in USD."""

    @abstractmethod
    async def get_open_orders(self) -> list[Order]:
        """Return all orders that are not yet terminal (filled/cancelled)."""

    # ------------------------------------------------------------------
    # Bulk operations
    # ------------------------------------------------------------------

    @abstractmethod
    async def cancel_all_orders(self) -> int:
        """Cancel every open order on the exchange.

        Returns
        -------
        int
            The number of orders that were successfully cancelled.
        """

    @abstractmethod
    async def close_all_positions(self, reason: CloseReason) -> list[Order]:
        """Flatten every open position.

        Parameters
        ----------
        reason:
            The close reason applied to every position.

        Returns
        -------
        list[Order]
            One closing order per position that was flattened.
        """

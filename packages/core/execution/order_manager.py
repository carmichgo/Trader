"""Order lifecycle tracking and state-machine management."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from packages.core.models import Order, OrderStatus

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Allowed transitions
# ------------------------------------------------------------------

_VALID_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.CREATED: {OrderStatus.SUBMITTED, OrderStatus.CANCELLED, OrderStatus.REJECTED},
    OrderStatus.SUBMITTED: {OrderStatus.PENDING, OrderStatus.CANCELLED, OrderStatus.REJECTED},
    OrderStatus.PENDING: {
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.REJECTED,
    },
    OrderStatus.PARTIALLY_FILLED: {
        OrderStatus.PARTIALLY_FILLED,  # additional fills
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
    },
    OrderStatus.FILLED: set(),      # terminal – no further transitions
    OrderStatus.CANCELLED: set(),   # terminal
    OrderStatus.REJECTED: set(),    # terminal
}

_TERMINAL_STATES: frozenset[OrderStatus] = frozenset({
    OrderStatus.FILLED,
    OrderStatus.CANCELLED,
    OrderStatus.REJECTED,
})


# ------------------------------------------------------------------
# Audit log entry
# ------------------------------------------------------------------

class StateTransition(BaseModel):
    """Immutable record of a single order state change."""

    order_id: str
    from_status: OrderStatus
    to_status: OrderStatus
    reason: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class InvalidTransitionError(Exception):
    """Raised when an order transition violates the state machine."""


# ------------------------------------------------------------------
# Order Manager
# ------------------------------------------------------------------

class OrderManager:
    """Tracks every order through its lifecycle and records transitions.

    All state updates go through :py:meth:`update_status` which enforces the
    finite-state-machine rules and writes an audit entry for every change.
    """

    def __init__(self) -> None:
        # order_id -> latest Order snapshot
        self._orders: dict[str, Order] = {}
        # order_id -> chronological list of transitions
        self._transitions: dict[str, list[StateTransition]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def submit_order(self, order: Order) -> Order:
        """Register a new order and record its initial CREATED state.

        Parameters
        ----------
        order:
            An ``Order`` instance.  If it does not have an ``id`` one will
            be generated.

        Returns
        -------
        Order
            The same order, now tracked by the manager.

        Raises
        ------
        ValueError
            If an order with the same id is already tracked.
        """
        if order.id is None:
            order.id = self._generate_id()

        if order.id in self._orders:
            raise ValueError(f"Order {order.id} is already tracked")

        self._orders[order.id] = order
        self._transitions[order.id] = []

        logger.info(
            "Order %s registered  market=%s symbol=%s side=%s qty=%s status=%s",
            order.id,
            order.market.value,
            order.symbol,
            order.direction.value,
            order.quantity,
            order.status.value,
        )
        return order

    def update_status(
        self,
        order_id: str,
        new_status: OrderStatus,
        *,
        reason: str = "",
        filled_quantity: Optional[float] = None,
        filled_price: Optional[float] = None,
        error_message: Optional[str] = None,
    ) -> Order:
        """Transition *order_id* to *new_status*.

        Parameters
        ----------
        order_id:
            The id of the order to update.
        new_status:
            Target status.
        reason:
            Human-readable reason for the transition (recorded in the audit log).
        filled_quantity:
            Cumulative filled quantity (optional, for partial/full fills).
        filled_price:
            Average fill price (optional).
        error_message:
            Error detail when transitioning to REJECTED.

        Returns
        -------
        Order
            The updated order.

        Raises
        ------
        KeyError
            If *order_id* is not tracked.
        InvalidTransitionError
            If the transition is not allowed by the state machine.
        """
        order = self._get_order(order_id)
        old_status = order.status

        allowed = _VALID_TRANSITIONS.get(old_status, set())
        if new_status not in allowed:
            raise InvalidTransitionError(
                f"Cannot transition order {order_id} from {old_status.value} "
                f"to {new_status.value}. Allowed: {[s.value for s in allowed]}"
            )

        now = datetime.now(timezone.utc)

        # Record the transition before mutating the order.
        transition = StateTransition(
            order_id=order_id,
            from_status=old_status,
            to_status=new_status,
            reason=reason,
            timestamp=now,
        )
        self._transitions[order_id].append(transition)

        # Mutate the order snapshot.
        order.status = new_status
        order.updated_at = now

        if filled_quantity is not None:
            order.filled_quantity = filled_quantity
        if filled_price is not None:
            order.filled_price = filled_price
        if error_message is not None:
            order.error_message = error_message

        # Convenience timestamp fields.
        if new_status == OrderStatus.SUBMITTED:
            order.submitted_at = now
        elif new_status == OrderStatus.FILLED:
            order.filled_at = now
        elif new_status == OrderStatus.CANCELLED:
            order.cancelled_at = now

        logger.info(
            "Order %s  %s -> %s  reason=%r",
            order_id,
            old_status.value,
            new_status.value,
            reason,
        )
        return order

    def get_open_orders(self) -> list[Order]:
        """Return all orders that are **not** in a terminal state."""
        return [
            o for o in self._orders.values()
            if o.status not in _TERMINAL_STATES
        ]

    def get_order_history(self, order_id: Optional[str] = None) -> list[StateTransition]:
        """Return the full transition history.

        Parameters
        ----------
        order_id:
            If given, return only transitions for that order.  Otherwise
            return all transitions across every tracked order, sorted by
            timestamp.
        """
        if order_id is not None:
            return list(self._transitions.get(order_id, []))

        all_transitions: list[StateTransition] = []
        for transitions in self._transitions.values():
            all_transitions.extend(transitions)
        all_transitions.sort(key=lambda t: t.timestamp)
        return all_transitions

    def get_order(self, order_id: str) -> Order:
        """Return the current snapshot of an order.

        Raises
        ------
        KeyError
            If the order is not tracked.
        """
        return self._get_order(order_id)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_order(self, order_id: str) -> Order:
        try:
            return self._orders[order_id]
        except KeyError:
            raise KeyError(f"Order {order_id} is not tracked by OrderManager") from None

    @staticmethod
    def _generate_id() -> str:
        import uuid
        return f"ord-{uuid.uuid4().hex[:12]}"

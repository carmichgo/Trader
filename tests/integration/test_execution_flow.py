"""Integration tests for order lifecycle management.

These tests verify the OrderManager state machine transitions and
the full order lifecycle from creation through fill or cancellation.
"""

from __future__ import annotations

import pytest

from packages.core.execution.order_manager import (
    InvalidTransitionError,
    OrderManager,
    StateTransition,
)
from packages.core.models import Direction, Market, Order, OrderStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_order(**overrides) -> Order:
    defaults = dict(
        market=Market.CRYPTO,
        symbol="BTC/USDT",
        direction=Direction.BUY,
        quantity=0.1,
        price=65000.0,
        order_type="limit",
    )
    defaults.update(overrides)
    return Order(**defaults)


# ---------------------------------------------------------------------------
# Happy-path lifecycle
# ---------------------------------------------------------------------------


class TestOrderLifecycleHappyPath:
    """Full order lifecycle: CREATED -> SUBMITTED -> PENDING -> FILLED."""

    def test_full_fill_lifecycle(self) -> None:
        """An order should transition cleanly through all states to FILLED."""
        mgr = OrderManager()
        order = _make_order(id="ord-001")
        mgr.submit_order(order)

        assert order.status == OrderStatus.CREATED

        mgr.update_status("ord-001", OrderStatus.SUBMITTED, reason="sent to exchange")
        assert order.status == OrderStatus.SUBMITTED
        assert order.submitted_at is not None

        mgr.update_status("ord-001", OrderStatus.PENDING, reason="exchange ack")
        assert order.status == OrderStatus.PENDING

        mgr.update_status(
            "ord-001",
            OrderStatus.FILLED,
            reason="full fill",
            filled_quantity=0.1,
            filled_price=65000.0,
        )
        assert order.status == OrderStatus.FILLED
        assert order.filled_quantity == 0.1
        assert order.filled_price == 65000.0
        assert order.filled_at is not None

    def test_partial_fill_then_full_fill(self) -> None:
        """An order can go through partial fills before being fully filled."""
        mgr = OrderManager()
        order = _make_order(id="ord-002")
        mgr.submit_order(order)

        mgr.update_status("ord-002", OrderStatus.SUBMITTED)
        mgr.update_status("ord-002", OrderStatus.PENDING)
        mgr.update_status(
            "ord-002",
            OrderStatus.PARTIALLY_FILLED,
            filled_quantity=0.05,
            filled_price=65000.0,
        )
        assert order.status == OrderStatus.PARTIALLY_FILLED
        assert order.filled_quantity == 0.05

        mgr.update_status(
            "ord-002",
            OrderStatus.FILLED,
            filled_quantity=0.1,
            filled_price=65000.0,
        )
        assert order.status == OrderStatus.FILLED
        assert order.filled_quantity == 0.1


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


class TestOrderCancellation:
    """Orders can be cancelled from non-terminal states."""

    def test_cancel_from_pending(self) -> None:
        """A PENDING order can be cancelled."""
        mgr = OrderManager()
        order = _make_order(id="ord-003")
        mgr.submit_order(order)

        mgr.update_status("ord-003", OrderStatus.SUBMITTED)
        mgr.update_status("ord-003", OrderStatus.PENDING)
        mgr.update_status("ord-003", OrderStatus.CANCELLED, reason="user request")

        assert order.status == OrderStatus.CANCELLED
        assert order.cancelled_at is not None

    def test_cancel_from_partially_filled(self) -> None:
        """A PARTIALLY_FILLED order can be cancelled (partial fill stands)."""
        mgr = OrderManager()
        order = _make_order(id="ord-004")
        mgr.submit_order(order)

        mgr.update_status("ord-004", OrderStatus.SUBMITTED)
        mgr.update_status("ord-004", OrderStatus.PENDING)
        mgr.update_status("ord-004", OrderStatus.PARTIALLY_FILLED, filled_quantity=0.03)
        mgr.update_status("ord-004", OrderStatus.CANCELLED, reason="timeout")

        assert order.status == OrderStatus.CANCELLED
        assert order.filled_quantity == 0.03


# ---------------------------------------------------------------------------
# Invalid transitions
# ---------------------------------------------------------------------------


class TestInvalidTransitions:
    """The state machine should reject illegal transitions."""

    def test_cannot_transition_from_terminal(self) -> None:
        """A FILLED order cannot be moved to any other state."""
        mgr = OrderManager()
        order = _make_order(id="ord-005")
        mgr.submit_order(order)

        mgr.update_status("ord-005", OrderStatus.SUBMITTED)
        mgr.update_status("ord-005", OrderStatus.PENDING)
        mgr.update_status("ord-005", OrderStatus.FILLED, filled_quantity=0.1)

        with pytest.raises(InvalidTransitionError):
            mgr.update_status("ord-005", OrderStatus.CANCELLED)

    def test_cannot_skip_states(self) -> None:
        """A CREATED order cannot jump directly to FILLED."""
        mgr = OrderManager()
        order = _make_order(id="ord-006")
        mgr.submit_order(order)

        with pytest.raises(InvalidTransitionError):
            mgr.update_status("ord-006", OrderStatus.FILLED)

    def test_unknown_order_raises_key_error(self) -> None:
        """Updating a non-existent order should raise KeyError."""
        mgr = OrderManager()

        with pytest.raises(KeyError):
            mgr.update_status("nonexistent", OrderStatus.SUBMITTED)


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------


class TestAuditTrail:
    """The OrderManager records every transition for auditing."""

    def test_transition_history_recorded(self) -> None:
        """Every state change should be recorded in the audit log."""
        mgr = OrderManager()
        order = _make_order(id="ord-007")
        mgr.submit_order(order)

        mgr.update_status("ord-007", OrderStatus.SUBMITTED)
        mgr.update_status("ord-007", OrderStatus.PENDING)
        mgr.update_status("ord-007", OrderStatus.FILLED, filled_quantity=0.1)

        history = mgr.get_order_history("ord-007")
        assert len(history) == 3
        assert history[0].from_status == OrderStatus.CREATED
        assert history[0].to_status == OrderStatus.SUBMITTED
        assert history[2].to_status == OrderStatus.FILLED

    def test_open_orders_excludes_terminal(self) -> None:
        """get_open_orders should not include filled or cancelled orders."""
        mgr = OrderManager()
        o1 = _make_order(id="ord-open")
        o2 = _make_order(id="ord-filled")
        mgr.submit_order(o1)
        mgr.submit_order(o2)

        mgr.update_status("ord-filled", OrderStatus.SUBMITTED)
        mgr.update_status("ord-filled", OrderStatus.PENDING)
        mgr.update_status("ord-filled", OrderStatus.FILLED, filled_quantity=0.1)

        open_orders = mgr.get_open_orders()
        assert len(open_orders) == 1
        assert open_orders[0].id == "ord-open"

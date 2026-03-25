"""Execution engine: order placement, lifecycle tracking, and slippage estimation."""

from packages.core.execution.base_executor import BaseExecutor
from packages.core.execution.order_manager import (
    InvalidTransitionError,
    OrderManager,
    StateTransition,
)
from packages.core.execution.slippage_estimator import (
    OrderBook,
    OrderBookLevel,
    SlippageEstimator,
    SlippageRecord,
)

__all__ = [
    "BaseExecutor",
    "InvalidTransitionError",
    "OrderBook",
    "OrderBookLevel",
    "OrderManager",
    "SlippageEstimator",
    "SlippageRecord",
    "StateTransition",
]

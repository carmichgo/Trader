"""Core trade data models: Trade, Position, and Order."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class TradeStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class OrderStatus(str, Enum):
    CREATED = "created"
    SUBMITTED = "submitted"
    PENDING = "pending"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class CloseReason(str, Enum):
    TAKE_PROFIT = "take_profit"
    STOP_LOSS = "stop_loss"
    TIME_EXPIRY = "time_expiry"
    MANUAL = "manual"
    SIGNAL_REVERSAL = "signal_reversal"
    KILL_SWITCH = "kill_switch"


class Direction(str, Enum):
    BUY = "buy"
    SELL = "sell"
    SHORT = "short"


class Market(str, Enum):
    POLYMARKET = "polymarket"
    CRYPTO = "crypto"
    STOCKS = "stocks"


class Order(BaseModel):
    """Represents a single order submitted to an exchange or market."""

    id: Optional[str] = None
    trade_id: Optional[str] = None
    market: Market
    symbol: str
    direction: Direction
    quantity: float
    price: Optional[float] = None
    order_type: str = "limit"
    status: OrderStatus = OrderStatus.CREATED
    filled_quantity: float = 0.0
    filled_price: Optional[float] = None
    fees: float = 0.0
    exchange_order_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None
    submitted_at: Optional[datetime] = None
    filled_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    error_message: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


class Position(BaseModel):
    """Represents an open position in a market."""

    id: Optional[str] = None
    trade_id: Optional[str] = None
    market: Market
    symbol: str
    direction: Direction
    quantity: float
    entry_price: float
    current_price: Optional[float] = None
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    leverage: float = 1.0
    margin_used: float = 0.0
    liquidation_price: Optional[float] = None
    opened_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None
    metadata: dict = Field(default_factory=dict)


class Trade(BaseModel):
    """Represents a complete trade lifecycle from signal to close."""

    id: Optional[str] = None
    market: Market
    symbol: str
    direction: Direction
    strategy: Optional[str] = None
    signal_id: Optional[str] = None
    status: TradeStatus = TradeStatus.OPEN
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    quantity: float = 0.0
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    leverage: float = 1.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    fees_paid: float = 0.0
    net_pnl: float = 0.0
    close_reason: Optional[CloseReason] = None
    confidence: Optional[float] = None
    risk_score: Optional[float] = None
    orders: list[Order] = Field(default_factory=list)
    position: Optional[Position] = None
    is_paper_trade: bool = False
    opened_at: datetime = Field(default_factory=datetime.utcnow)
    closed_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    expiry_at: Optional[datetime] = None
    notes: Optional[str] = None
    metadata: dict = Field(default_factory=dict)

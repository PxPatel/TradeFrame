from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    ACKED = "ACKED"
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Intent:
    id: str
    strategy_name: str
    symbol: str
    target_qty: int
    reason: str
    created_at: datetime


@dataclass
class Order:
    client_order_id: str
    intent_id: str
    broker_order_id: str | None
    symbol: str
    side: Side
    qty: int
    order_type: str
    limit_price: float | None
    status: OrderStatus
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class Position:
    symbol: str
    quantity: int
    average_price: float


@dataclass(frozen=True)
class MarketSnapshot:
    prices: dict[str, float]
    market_open: bool


@dataclass(frozen=True)
class MarketContext:
    prices: dict[str, float]
    positions: dict[str, Position]
    market_open: bool
    daily_realized_loss: float
    state_fresh: bool


@dataclass(frozen=True)
class RiskConfig:
    max_orders_per_day: int
    max_position_notional: float
    daily_loss_limit: float
    symbol_allowlist: frozenset[str]
    max_order_qty: int


@dataclass(frozen=True)
class Decision:
    approved: bool
    adjusted_qty: int | None
    reason: str
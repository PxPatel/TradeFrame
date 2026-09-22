from abc import ABC, abstractmethod
from dataclasses import dataclass

from core.models import MarketSnapshot, Order, OrderStatus, Position


@dataclass(frozen=True)
class BrokerOrderResult:
    status: OrderStatus
    broker_order_id: str | None = None
    fill_price: float | None = None


class Broker(ABC):
    @abstractmethod
    def place_order(self, order: Order) -> BrokerOrderResult: ...

    @abstractmethod
    def get_positions(self) -> list[Position]: ...

    @abstractmethod
    def get_open_orders(self) -> list[Order]: ...


class MarketDataProvider(ABC):
    @abstractmethod
    def get_snapshot(self, symbols: list[str]) -> MarketSnapshot: ...


class MarketDataProvider(ABC):
    @abstractmethod
    def get_prices(self, symbols: list[str]) -> dict[str, float]: ...
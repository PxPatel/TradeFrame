from copy import deepcopy

from core.models import Order, OrderStatus, Position, Side
from .broker_interface import Broker, BrokerOrderResult


class PaperBroker(Broker):
    """Immediate-fill broker for deterministic tests and paper runs."""
    def __init__(self, prices: dict[str, float], positions: list[Position] | None = None):
        self.prices = prices
        self.orders: dict[str, Order] = {}
        self.positions: dict[str, Position] = {position.symbol: position for position in (positions or [])}

    def place_order(self, order: Order) -> BrokerOrderResult:
        if order.client_order_id in self.orders:
            existing = self.orders[order.client_order_id]
            return BrokerOrderResult(existing.status, existing.broker_order_id, self.prices[order.symbol])
        price = self.prices[order.symbol]
        current = self.positions.get(order.symbol, Position(order.symbol, 0, 0.0))
        signed_qty = order.qty if order.side is Side.BUY else -order.qty
        quantity = current.quantity + signed_qty
        self.positions[order.symbol] = Position(order.symbol, quantity, price if quantity else 0.0)
        filled = deepcopy(order)
        filled.status = OrderStatus.FILLED
        filled.broker_order_id = "paper-" + order.client_order_id
        self.orders[order.client_order_id] = filled
        return BrokerOrderResult(OrderStatus.FILLED, filled.broker_order_id, price)

    def get_positions(self) -> list[Position]:
        return list(self.positions.values())

    def get_open_orders(self) -> list[Order]:
        return [order for order in self.orders.values() if order.status not in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED)]
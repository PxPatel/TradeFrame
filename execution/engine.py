import uuid
from datetime import datetime, timezone

from core.models import Intent, MarketContext, Order, OrderStatus, Side
from core.risk_manager import RiskManager
from core.state_store import StateStore
from .broker_interface import Broker


class ExecutionEngine:
    def __init__(self, broker: Broker, state_store: StateStore, risk_manager: RiskManager, order_type: str):
        self.broker = broker
        self.state_store = state_store
        self.risk_manager = risk_manager
        self.order_type = order_type

    def execute(self, intent: Intent, context: MarketContext) -> Order | None:
        self.state_store.save_intent(intent)
        decision = self.risk_manager.evaluate(intent, context)
        if not decision.approved or decision.adjusted_qty == 0:
            return None
        current_qty = context.positions.get(intent.symbol, self.state_store.get_position(intent.symbol)).quantity
        delta = decision.adjusted_qty - current_qty
        if delta == 0:
            self.state_store.record_event("intent_noop", {"intent_id": intent.id, "symbol": intent.symbol})
            return None
        now = datetime.now(timezone.utc)
        order = Order(str(uuid.uuid4()), intent.id, None, intent.symbol,
                      Side.BUY if delta > 0 else Side.SELL, abs(delta), self.order_type, None,
                      OrderStatus.PENDING, now, now)
        self.state_store.save_order(order)
        try:
            result = self.broker.place_order(order)
        except (TimeoutError, ConnectionError):
            order.status = OrderStatus.UNKNOWN
            order.updated_at = datetime.now(timezone.utc)
            self.state_store.update_order(order)
            return order
        order.status = result.status
        order.broker_order_id = result.broker_order_id
        order.updated_at = datetime.now(timezone.utc)
        self.state_store.update_order(order)
        if result.status is OrderStatus.FILLED and result.fill_price is not None:
            current_position = context.positions.get(order.symbol, self.state_store.get_position(order.symbol))
            realized_pnl = ((result.fill_price - current_position.average_price) * order.qty
                            if order.side is Side.SELL else 0.0)
            self.state_store.record_fill(order.client_order_id, order.symbol, order.side,
                                         order.qty, result.fill_price, realized_pnl)
            positions = {position.symbol: position for position in self.broker.get_positions()}
            position = positions.get(order.symbol)
            if position is not None:
                self.state_store.save_position(position)
        return order
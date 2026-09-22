import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from core.models import Intent, MarketContext, Order, OrderStatus, Position, Side
from core.risk_manager import RiskManager
from core.state_store import StateStore
from .broker_interface import Broker


@dataclass(frozen=True)
class ExecutionPolicy:
    order_type: str


class IntentTranslator:
    def __init__(self, policy: ExecutionPolicy):
        self.policy = policy

    def translate(self, intent: Intent, current_qty: int, target_qty: int) -> Order | None:
        delta = target_qty - current_qty
        if delta == 0:
            return None
        now = datetime.now(timezone.utc)
        return Order(
            str(uuid.uuid4()),
            intent.id,
            None,
            intent.symbol,
            Side.BUY if delta > 0 else Side.SELL,
            abs(delta),
            self.policy.order_type,
            None,
            OrderStatus.PENDING,
            now,
            now,
        )


class OrderService:
    def __init__(self, broker: Broker, state_store: StateStore):
        self.broker = broker
        self.state_store = state_store

    def submit(self, order: Order) -> tuple[Order, float | None]:
        self.state_store.save_order(order)
        try:
            result = self.broker.place_order(order)
        except (TimeoutError, ConnectionError):
            order.status = OrderStatus.UNKNOWN
            order.updated_at = datetime.now(timezone.utc)
            self.state_store.update_order(order)
            return order, None
        order.status = result.status
        order.broker_order_id = result.broker_order_id
        order.updated_at = datetime.now(timezone.utc)
        self.state_store.update_order(order)
        return order, result.fill_price


class FillService:
    def __init__(self, broker: Broker, state_store: StateStore):
        self.broker = broker
        self.state_store = state_store

    def apply(self, order: Order, fill_price: float | None, context: MarketContext):
        if order.status is not OrderStatus.FILLED or fill_price is None:
            return
        current_position = context.positions.get(order.symbol, self.state_store.get_position(order.symbol))
        realized_pnl = self._realized_pnl(current_position, order, fill_price)
        self.state_store.record_fill(order.client_order_id, order.symbol, order.side, order.qty, fill_price, realized_pnl)
        positions = {position.symbol: position for position in self.broker.get_positions()}
        position = positions.get(order.symbol)
        if position is not None:
            self.state_store.save_position(position)

    @staticmethod
    def _realized_pnl(position: Position, order: Order, fill_price: float) -> float:
        if order.side is Side.SELL and position.quantity > 0:
            close_qty = min(order.qty, position.quantity)
            return (fill_price - position.average_price) * close_qty
        if order.side is Side.BUY and position.quantity < 0:
            close_qty = min(order.qty, abs(position.quantity))
            return (position.average_price - fill_price) * close_qty
        return 0.0


class ExecutionEngine:
    def __init__(self, state_store: StateStore, risk_manager: RiskManager, translator: IntentTranslator,
                 order_service: OrderService, fill_service: FillService):
        self.state_store = state_store
        self.risk_manager = risk_manager
        self.translator = translator
        self.order_service = order_service
        self.fill_service = fill_service

    def execute(self, intent: Intent, context: MarketContext) -> Order | None:
        self.state_store.save_intent(intent)
        decision = self.risk_manager.evaluate(intent, context)
        if not decision.approved or decision.adjusted_qty == 0:
            return None
        current_qty = context.positions.get(intent.symbol, self.state_store.get_position(intent.symbol)).quantity
        order = self.translator.translate(intent, current_qty, int(decision.adjusted_qty))
        if order is None:
            self.state_store.record_event("intent_noop", {"intent_id": intent.id, "symbol": intent.symbol})
            return None
        persisted_order, fill_price = self.order_service.submit(order)
        self.fill_service.apply(persisted_order, fill_price, context)
        return persisted_order

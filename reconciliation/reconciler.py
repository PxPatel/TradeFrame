from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from core.kill_switch import KillSwitch
from core.models import Order, OrderStatus, Position
from core.state_store import StateStore
from execution.broker_interface import Broker


@dataclass(frozen=True)
class Mismatch:
    kind: str
    symbol: str | None
    severity: str
    detail: str
    auto_healed: bool = False


class Reconciler:
    def __init__(self, broker: Broker, state_store: StateStore, kill_switch: KillSwitch | None = None):
        self.broker = broker
        self.state_store = state_store
        self.kill_switch = kill_switch

    def run(self) -> list[Mismatch]:
        broker_positions = {position.symbol: position for position in self.broker.get_positions()}
        local_positions = {position.symbol: position for position in self.state_store.get_positions()
                           if position.quantity != 0}
        mismatches = self._position_mismatches(broker_positions, local_positions, self.state_store)
        mismatches.extend(self._order_mismatches(self.broker.get_open_orders(),
                                                  self.state_store.get_open_orders()))
        if mismatches and any(item.severity == "high" for item in mismatches) and self.kill_switch:
            self.kill_switch.halt("high-severity reconciliation mismatch")
        for mismatch in mismatches:
            self.state_store.record_event("reconciliation_mismatch", mismatch.__dict__)
        return mismatches

    @staticmethod
    def _position_mismatches(
        broker_positions: dict[str, Position], local_positions: dict[str, Position], state_store: StateStore
    ) -> list[Mismatch]:
        mismatches = []
        for symbol in sorted(set(broker_positions) | set(local_positions)):
            broker = broker_positions.get(symbol, Position(symbol, 0, 0.0))
            local = local_positions.get(symbol, Position(symbol, 0, 0.0))
            if local.quantity != broker.quantity:
                if local.quantity == 0 and broker.quantity != 0:
                    mismatches.append(Mismatch("position_broker_only", symbol, "high",
                                               f"local={local.quantity}, broker={broker.quantity}"))
                    continue
                if local.quantity != 0 and broker.quantity == 0:
                    mismatches.append(Mismatch("position_local_only", symbol, "high",
                                               f"local={local.quantity}, broker={broker.quantity}"))
                    continue
                state_store.save_position(broker)
                mismatches.append(Mismatch("position_drift", symbol, "medium",
                                           f"local={local.quantity}, broker={broker.quantity}", auto_healed=True))
        return mismatches

    @staticmethod
    def _order_mismatches(broker_orders: list[Order], local_orders: list[Order]) -> list[Mismatch]:
        broker_ids = {order.client_order_id for order in broker_orders}
        local_ids = {order.client_order_id for order in local_orders}
        mismatches = []
        for client_order_id in sorted(broker_ids - local_ids):
            mismatches.append(Mismatch("order_broker_only", None, "high",
                                       f"broker order has no local record: {client_order_id}"))
        now = datetime.now(timezone.utc)
        for client_order_id in sorted(local_ids - broker_ids):
            order = next(item for item in local_orders if item.client_order_id == client_order_id)
            if order.status is OrderStatus.UNKNOWN and (now - order.updated_at) > timedelta(minutes=5):
                mismatches.append(Mismatch("order_unknown_stale", order.symbol, "high",
                                           f"local UNKNOWN order unresolved: {client_order_id}"))
            else:
                mismatches.append(Mismatch("order_local_only", order.symbol, "high",
                                           f"local open order absent from broker: {client_order_id}"))
        return mismatches
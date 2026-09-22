from core.kill_switch import KillSwitch
from core.models import Position
from core.state_store import StateStore
from execution.paper_broker import PaperBroker
from reconciliation.reconciler import Reconciler
from core.models import OrderStatus, Side, Order
from datetime import datetime, timezone


def test_reconciliation_halts_on_unknown_broker_position(tmp_path):
    switch = KillSwitch(tmp_path / "KILL_SWITCH")
    broker = PaperBroker({"AAPL": 100.0})
    broker.positions["AAPL"] = Position("AAPL", 5, 100.0)

    mismatches = Reconciler(broker, StateStore(tmp_path / "trading.db"), switch).run()

    assert mismatches[0].severity == "high"
    assert switch.halted


def test_reconciliation_detects_local_only_open_order(tmp_path):
    store = StateStore(tmp_path / "trading.db")
    now = datetime.now(timezone.utc)
    store.save_order(Order("local-order", "intent", None, "AAPL", Side.BUY, 1,
                           "MKT", None, OrderStatus.UNKNOWN, now, now))

    mismatches = Reconciler(PaperBroker({"AAPL": 100.0}), store).run()

    assert any(item.kind == "order_local_only" and item.severity == "high" for item in mismatches)
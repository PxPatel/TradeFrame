from datetime import datetime, timedelta, timezone

from core.models import Order, OrderStatus, Position, Side
from core.state_store import StateStore
from execution.paper_broker import PaperBroker
from reconciliation.reconciler import Reconciler
from strategies.registry import default_strategy_registry


def test_strategy_registry_builds_example_strategy():
    strategy = default_strategy_registry().create(
        "example_slow_swing", ("AAPL", "MSFT"), {"target_qty": 3}
    )
    assert strategy.name == "example_slow_swing"
    assert strategy.target_qty == 3


def test_reconciliation_auto_heals_position_drift(tmp_path):
    store = StateStore(tmp_path / "trading.db")
    store.save_position(Position("AAPL", 1, 100.0))
    broker = PaperBroker({"AAPL": 100.0}, [Position("AAPL", 5, 101.0)])

    mismatches = Reconciler(broker, store).run()

    assert any(item.kind == "position_drift" and item.auto_healed for item in mismatches)
    healed = store.get_position("AAPL")
    assert healed.quantity == 5


def test_reconciliation_marks_stale_unknown_orders_high(tmp_path):
    store = StateStore(tmp_path / "trading.db")
    stale = datetime.now(timezone.utc) - timedelta(minutes=10)
    store.save_order(
        Order(
            "unknown-order",
            "intent",
            None,
            "AAPL",
            Side.BUY,
            1,
            "MKT",
            None,
            OrderStatus.UNKNOWN,
            stale,
            stale,
        )
    )

    mismatches = Reconciler(PaperBroker({"AAPL": 100.0}), store).run()

    assert any(item.kind == "order_unknown_stale" and item.severity == "high" for item in mismatches)

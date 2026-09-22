from datetime import datetime, timezone

from core.models import Intent, MarketContext, RiskConfig
from core.risk_manager import RiskManager
from core.risk_rules import default_risk_rules
from core.state_store import StateStore
from execution.engine import ExecutionEngine, ExecutionPolicy, FillService, IntentTranslator, OrderService
from execution.paper_broker import PaperBroker


def test_repeating_target_intent_does_not_duplicate_order(tmp_path):
    store = StateStore(tmp_path / "trading.db")
    broker = PaperBroker({"AAPL": 100.0})
    risk_config = RiskConfig(6, 5000.0, 200.0, frozenset({"AAPL"}), 1000)
    risk = RiskManager(default_risk_rules(risk_config, store, None), store)
    engine = ExecutionEngine(
        store,
        risk,
        IntentTranslator(ExecutionPolicy(order_type="MKT")),
        OrderService(broker, store),
        FillService(broker, store),
    )
    intent = Intent("intent-1", "test", "AAPL", 10, "test target", datetime.now(timezone.utc))
    context = MarketContext({"AAPL": 100.0}, {}, True, 0.0, True)

    first = engine.execute(intent, context)
    second = engine.execute(intent, MarketContext({"AAPL": 100.0}, {"AAPL": broker.positions["AAPL"]}, True, 0.0, True))

    assert first is not None
    assert first.status.value == "FILLED"
    assert second is None
    assert len(broker.orders) == 1
    assert broker.positions["AAPL"].quantity == 10
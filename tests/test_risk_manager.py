from datetime import datetime, timezone

from core.models import Intent, MarketContext, RiskConfig
from core.risk_manager import RiskManager
from core.risk_rules import default_risk_rules
from core.state_store import StateStore


def test_risk_manager_fails_closed_when_state_is_stale(tmp_path):
    store = StateStore(tmp_path / "trading.db")
    risk_config = RiskConfig(6, 5000.0, 200.0, frozenset(), 1000)
    risk = RiskManager(default_risk_rules(risk_config, store, None), store)
    intent = Intent("i", "test", "AAPL", 1, "test", datetime.now(timezone.utc))

    decision = risk.evaluate(intent, MarketContext({"AAPL": 100.0}, {}, True, 0.0, False))

    assert not decision.approved
    assert decision.reason == "state is stale"


def test_risk_manager_rejects_unknown_symbol(tmp_path):
    store = StateStore(tmp_path / "trading.db")
    risk_config = RiskConfig(6, 5000.0, 200.0, frozenset({"AAPL"}), 1000)
    risk = RiskManager(default_risk_rules(risk_config, store, None), store)
    intent = Intent("i", "test", "TSLA", 1, "test", datetime.now(timezone.utc))

    decision = risk.evaluate(intent, MarketContext({"TSLA": 250.0}, {}, True, 0.0, True))

    assert not decision.approved
    assert decision.reason == "symbol is not allowed"
from collections.abc import Sequence

from .models import Decision, Intent, MarketContext
from .risk_rules import RiskRule
from .state_store import StateStore


class RiskManager:
    def __init__(self, rules: Sequence[RiskRule], state_store: StateStore):
        self.rules = tuple(rules)
        self.state_store = state_store

    def evaluate(self, intent: Intent, context: MarketContext) -> Decision:
        for rule in self.rules:
            decision = rule.evaluate(intent, context)
            if not decision.approved:
                self.state_store.record_event(
                    "risk_rejected",
                    {"symbol": intent.symbol, "reason": decision.reason, "rule": getattr(rule, "name", "unknown")},
                )
                return decision
        return Decision(True, intent.target_qty, "ok")
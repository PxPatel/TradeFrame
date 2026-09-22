from abc import ABC, abstractmethod
from datetime import datetime, time, timezone

from .kill_switch import KillSwitch
from .models import Decision, Intent, MarketContext, RiskConfig
from .state_store import StateStore


class RiskRule(ABC):
    name: str

    @abstractmethod
    def evaluate(self, intent: Intent, context: MarketContext) -> Decision: ...


class StateFreshRule(RiskRule):
    name = "state"

    def evaluate(self, intent: Intent, context: MarketContext) -> Decision:
        return Decision(context.state_fresh, None if not context.state_fresh else intent.target_qty,
                        "state is stale" if not context.state_fresh else "ok")


class KillSwitchRule(RiskRule):
    name = "kill_switch"

    def __init__(self, kill_switch: KillSwitch | None):
        self.kill_switch = kill_switch

    def evaluate(self, intent: Intent, context: MarketContext) -> Decision:
        halted = self.kill_switch is not None and self.kill_switch.halted
        return Decision(not halted, None if halted else intent.target_qty, "kill switch is active" if halted else "ok")


class TargetBoundsRule(RiskRule):
    name = "target"

    def __init__(self, config: RiskConfig):
        self.config = config

    def evaluate(self, intent: Intent, context: MarketContext) -> Decision:
        valid = 0 <= intent.target_qty <= self.config.max_order_qty
        return Decision(valid, None if not valid else intent.target_qty,
                        "invalid or excessive target quantity" if not valid else "ok")


class SymbolAllowlistRule(RiskRule):
    name = "symbol"

    def __init__(self, config: RiskConfig):
        self.config = config

    def evaluate(self, intent: Intent, context: MarketContext) -> Decision:
        valid = not self.config.symbol_allowlist or intent.symbol in self.config.symbol_allowlist
        return Decision(valid, None if not valid else intent.target_qty, "symbol is not allowed" if not valid else "ok")


class MarketOpenRule(RiskRule):
    name = "market"

    def evaluate(self, intent: Intent, context: MarketContext) -> Decision:
        return Decision(context.market_open, None if not context.market_open else intent.target_qty,
                        "market is closed" if not context.market_open else "ok")


class DailyLossRule(RiskRule):
    name = "loss"

    def __init__(self, config: RiskConfig):
        self.config = config

    def evaluate(self, intent: Intent, context: MarketContext) -> Decision:
        valid = context.daily_realized_loss < self.config.daily_loss_limit
        return Decision(valid, None if not valid else intent.target_qty, "daily loss limit reached" if not valid else "ok")


class DailyRateRule(RiskRule):
    name = "rate"

    def __init__(self, config: RiskConfig, state_store: StateStore):
        self.config = config
        self.state_store = state_store

    def evaluate(self, intent: Intent, context: MarketContext) -> Decision:
        start = datetime.combine(datetime.now(timezone.utc).date(), time.min, timezone.utc)
        valid = self.state_store.count_orders_since(start) < self.config.max_orders_per_day
        return Decision(valid, None if not valid else intent.target_qty, "daily order limit reached" if not valid else "ok")


class MaxExposureRule(RiskRule):
    name = "exposure"

    def __init__(self, config: RiskConfig):
        self.config = config

    def evaluate(self, intent: Intent, context: MarketContext) -> Decision:
        price = context.prices.get(intent.symbol)
        valid = price is not None and intent.target_qty * price <= self.config.max_position_notional
        return Decision(valid, None if not valid else intent.target_qty,
                        "position exposure is too large or price is missing" if not valid else "ok")


class DuplicateOpenOrderRule(RiskRule):
    name = "duplicate"

    def __init__(self, state_store: StateStore):
        self.state_store = state_store

    def evaluate(self, intent: Intent, context: MarketContext) -> Decision:
        valid = not self.state_store.get_open_orders(intent.symbol)
        return Decision(valid, None if not valid else intent.target_qty, "an open order already exists" if not valid else "ok")


def default_risk_rules(
    config: RiskConfig, state_store: StateStore, kill_switch: KillSwitch | None, rule_order: tuple[str, ...] | None = None
) -> list[RiskRule]:
    available: dict[str, RiskRule] = {
        "state": StateFreshRule(),
        "kill_switch": KillSwitchRule(kill_switch),
        "target": TargetBoundsRule(config),
        "symbol": SymbolAllowlistRule(config),
        "market": MarketOpenRule(),
        "loss": DailyLossRule(config),
        "rate": DailyRateRule(config, state_store),
        "exposure": MaxExposureRule(config),
        "duplicate": DuplicateOpenOrderRule(state_store),
    }
    order = rule_order or tuple(available.keys())
    try:
        return [available[name] for name in order]
    except KeyError as exc:
        raise ValueError(f"unknown risk rule configured: {exc.args[0]}") from exc

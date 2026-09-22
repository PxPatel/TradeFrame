from datetime import datetime, time, timezone

from .kill_switch import KillSwitch
from .models import Decision, Intent, MarketContext, RiskConfig
from .state_store import StateStore


class RiskManager:
    def __init__(self, config: RiskConfig, state_store: StateStore, kill_switch: KillSwitch | None = None):
        self.config = config
        self.state_store = state_store
        self.kill_switch = kill_switch

    def evaluate(self, intent: Intent, context: MarketContext) -> Decision:
        checks = (self._check_state, self._check_kill_switch, self._check_target,
                  self._check_symbol, self._check_market, self._check_loss,
                  self._check_rate, self._check_exposure, self._check_duplicate)
        for check in checks:
            decision = check(intent, context)
            if not decision.approved:
                self.state_store.record_event("risk_rejected", {"symbol": intent.symbol, "reason": decision.reason})
                return decision
        return Decision(True, intent.target_qty, "ok")

    def _check_state(self, intent, context):
        return Decision(context.state_fresh, None if not context.state_fresh else intent.target_qty,
                        "state is stale" if not context.state_fresh else "ok")

    def _check_kill_switch(self, intent, context):
        halted = self.kill_switch is not None and self.kill_switch.halted
        return Decision(not halted, None if halted else intent.target_qty, "kill switch is active" if halted else "ok")

    def _check_target(self, intent, context):
        valid = 0 <= intent.target_qty <= self.config.max_order_qty
        return Decision(valid, None if not valid else intent.target_qty, "invalid or excessive target quantity" if not valid else "ok")

    def _check_symbol(self, intent, context):
        valid = not self.config.symbol_allowlist or intent.symbol in self.config.symbol_allowlist
        return Decision(valid, None if not valid else intent.target_qty, "symbol is not allowed" if not valid else "ok")

    def _check_market(self, intent, context):
        return Decision(context.market_open, None if not context.market_open else intent.target_qty, "market is closed" if not context.market_open else "ok")

    def _check_loss(self, intent, context):
        valid = context.daily_realized_loss < self.config.daily_loss_limit
        return Decision(valid, None if not valid else intent.target_qty, "daily loss limit reached" if not valid else "ok")

    def _check_rate(self, intent, context):
        start = datetime.combine(datetime.now(timezone.utc).date(), time.min, timezone.utc)
        valid = self.state_store.count_orders_since(start) < self.config.max_orders_per_day
        return Decision(valid, None if not valid else intent.target_qty, "daily order limit reached" if not valid else "ok")

    def _check_exposure(self, intent, context):
        price = context.prices.get(intent.symbol)
        valid = price is not None and intent.target_qty * price <= self.config.max_position_notional
        return Decision(valid, None if not valid else intent.target_qty, "position exposure is too large or price is missing" if not valid else "ok")

    def _check_duplicate(self, intent, context):
        valid = not self.state_store.get_open_orders(intent.symbol)
        return Decision(valid, None if not valid else intent.target_qty, "an open order already exists" if not valid else "ok")
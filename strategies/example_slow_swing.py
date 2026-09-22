from uuid import uuid4

from core.models import Intent, MarketContext, utc_now
from .base import Strategy


class ExampleSlowSwing(Strategy):
    """Small example strategy: target one lot only when a quote is available."""
    name = "example_slow_swing"

    def __init__(self, symbol: str, target_qty: int):
        self.symbol = symbol
        self.target_qty = target_qty

    def evaluate(self, context: MarketContext) -> list[Intent]:
        if self.symbol not in context.prices:
            return []
        return [Intent(str(uuid4()), self.name, self.symbol, self.target_qty,
                       "example paper target", utc_now())]
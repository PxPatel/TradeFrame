from uuid import uuid4

from core.models import Intent, MarketContext, utc_now
from .base import Strategy


class ExampleSlowSwing(Strategy):
    """Small example strategy: target one lot only when a quote is available."""
    name = "example_slow_swing"

    def __init__(self, symbols: tuple[str, ...], target_qty: int):
        self.symbols = symbols
        self.target_qty = target_qty

    def evaluate(self, context: MarketContext) -> list[Intent]:
        intents: list[Intent] = []
        for symbol in self.symbols:
            if symbol not in context.prices:
                continue
            intents.append(Intent(str(uuid4()), self.name, symbol, self.target_qty,
                                  "example paper target", utc_now()))
        return intents
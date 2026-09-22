from collections.abc import Callable

from .base import Strategy
from .example_slow_swing import ExampleSlowSwing

StrategyBuilder = Callable[[tuple[str, ...], dict], Strategy]


class StrategyRegistry:
    def __init__(self):
        self._builders: dict[str, StrategyBuilder] = {}

    def register(self, name: str, builder: StrategyBuilder):
        self._builders[name] = builder

    def create(self, name: str, symbols: tuple[str, ...], config: dict) -> Strategy:
        if name not in self._builders:
            raise ValueError(f"unsupported configured strategy: {name}")
        return self._builders[name](symbols, config)


def default_strategy_registry() -> StrategyRegistry:
    registry = StrategyRegistry()
    registry.register(
        ExampleSlowSwing.name,
        lambda symbols, config: ExampleSlowSwing(
            symbols, int(config.get("target_qty", 1))
        ),
    )
    return registry

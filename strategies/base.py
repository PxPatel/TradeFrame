from abc import ABC, abstractmethod

from core.models import Intent, MarketContext


class Strategy(ABC):
    name: str

    @abstractmethod
    def evaluate(self, context: MarketContext) -> list[Intent]:
        """Return target-position intents for the current market snapshot."""
import os
from dataclasses import dataclass

from config.loader import AppConfig, config_from_environment
from core.kill_switch import KillSwitch
from core.models import Intent, MarketContext, RiskConfig, utc_now
from core.risk_manager import RiskManager
from core.risk_rules import default_risk_rules
from core.state_store import StateStore
from execution.broker_interface import Broker, MarketDataProvider
from execution.engine import ExecutionEngine, ExecutionPolicy, FillService, IntentTranslator, OrderService
from execution.paper_broker import PaperBroker
from execution.webull_client import WebullBroker, WebullMarketData
from strategies.base import Strategy
from strategies.registry import default_strategy_registry


@dataclass
class Runtime:
    config: AppConfig
    store: StateStore
    broker: Broker
    market_data: MarketDataProvider
    engine: ExecutionEngine
    strategy: Strategy

    def strategy_cycle(self):
        snapshot = self.market_data.get_snapshot(list(self.config.symbols))
        if isinstance(self.broker, PaperBroker):
            self.broker.prices = snapshot.prices
        positions = {position.symbol: position for position in self.broker.get_positions()}
        context = MarketContext(snapshot.prices, positions, snapshot.market_open,
                                self.store.get_daily_realized_loss(), True)
        return [self.engine.execute(intent, context)
                for intent in self.strategy.evaluate(context)]

    def flatten_cycle(self):
        snapshot = self.market_data.get_snapshot(list(self.config.symbols))
        if isinstance(self.broker, PaperBroker):
            self.broker.prices = snapshot.prices
        positions = {position.symbol: position for position in self.broker.get_positions()}
        context = MarketContext(snapshot.prices, positions, snapshot.market_open,
                                self.store.get_daily_realized_loss(), True)
        intents: list[Intent] = []
        for symbol, position in positions.items():
            if position.quantity != 0:
                intents.append(Intent(f"flatten-{symbol}-{utc_now().isoformat()}", "flatten", symbol, 0,
                                      "explicit flatten request", utc_now()))
        return [self.engine.execute(intent, context) for intent in intents]


def build_runtime() -> Runtime:
    config = config_from_environment()
    _validate_config(config)
    store = StateStore(config.database_path)
    kill_switch = KillSwitch(config.kill_switch_path)
    api_client = _build_api_client(config)
    market_data = WebullMarketData(api_client, market=config.market)
    if config.mode == "paper":
        broker: Broker = PaperBroker({}, store.get_positions())
    else:
        broker = WebullBroker(api_client, _required_env("WEBULL_ACCOUNT_ID"),
                              region=config.region, market=config.market,
                              order_type=config.order_type, time_in_force=config.time_in_force,
                              entrust_type=config.entrust_type)
    risk_config = RiskConfig(config.max_orders_per_day, config.max_position_notional,
                             config.daily_loss_limit, frozenset(config.symbols), config.max_order_qty)
    risk = RiskManager(default_risk_rules(risk_config, store, kill_switch, config.risk_rule_order), store)
    translator = IntentTranslator(ExecutionPolicy(order_type=config.order_type))
    order_service = OrderService(broker, store)
    fill_service = FillService(broker, store)
    engine = ExecutionEngine(store, risk, translator, order_service, fill_service)
    strategy = default_strategy_registry().create(config.strategy_name, config.symbols, config.strategy_config)
    return Runtime(config, store, broker, market_data, engine, strategy)


def _build_api_client(config: AppConfig):
    app_key = _required_env("WEBULL_APP_KEY")
    app_secret = _required_env("WEBULL_APP_SECRET")
    try:
        from webull.core.client import ApiClient
    except ImportError as exc:
        raise RuntimeError("install tradeframe[webull] to use the Webull API") from exc
    api_client = ApiClient(app_key, app_secret, config.region)
    endpoint = os.environ.get("WEBULL_API_ENDPOINT")
    if endpoint:
        api_client.add_endpoint(config.region, endpoint)
    return api_client


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} must be configured in the environment")
    return value


def _validate_config(config: AppConfig):
    if config.mode == "live" and config.market_data_provider != "webull":
        raise ValueError("live mode currently requires market_data.provider=webull")
    if config.order_type not in {"MKT", "LMT"}:
        raise ValueError("execution.order_type must be one of: MKT, LMT")
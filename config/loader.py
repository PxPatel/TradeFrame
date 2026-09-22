import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class AppConfig:
    mode: str
    symbols: tuple[str, ...]
    strategy_name: str
    strategy_config: dict[str, Any]
    database_path: str
    kill_switch_path: str
    max_orders_per_day: int
    max_position_notional: float
    daily_loss_limit: float
    max_order_qty: int
    risk_rule_order: tuple[str, ...]
    order_type: str
    time_in_force: str
    entrust_type: str
    market: str
    region: str
    market_data_provider: str
    paper_fill_price: float | None


def load_config(path: str | Path) -> AppConfig:
    with Path(path).open(encoding="utf-8") as file:
        raw = yaml.safe_load(file) or {}
    risk = _section(raw, "risk")
    runtime = _section(raw, "runtime")
    strategy = _section(raw, "strategy")
    market_data = _section(raw, "market_data")
    execution = _section(raw, "execution")
    broker = _section(raw, "broker")
    symbols = tuple(_required(raw, "symbol_allowlist"))
    if not symbols or any(not isinstance(symbol, str) for symbol in symbols):
        raise ValueError("symbol_allowlist must contain at least one symbol")
    strategy_name = _required(strategy, "name")
    strategy_config = dict(strategy.get("config") or {})
    if strategy_name == "example_slow_swing":
        target_qty = strategy.get("target_qty")
        if target_qty is not None and "target_qty" not in strategy_config:
            strategy_config["target_qty"] = target_qty
    strategy_config.setdefault("target_qty", 1)
    risk_rule_order = tuple(risk.get("rules", (
        "state", "kill_switch", "target", "symbol", "market",
        "loss", "rate", "exposure", "duplicate",
    )))
    config = AppConfig(
        mode=_required(raw, "mode"), symbols=symbols,
        strategy_name=strategy_name, strategy_config=strategy_config,
        database_path=_required(runtime, "database_path"), kill_switch_path=_required(runtime, "kill_switch_path"),
        max_orders_per_day=_required(risk, "max_orders_per_day"),
        max_position_notional=_required(risk, "max_position_notional"),
        daily_loss_limit=_required(risk, "daily_loss_limit"), max_order_qty=_required(risk, "max_order_qty"),
        risk_rule_order=risk_rule_order,
        order_type=_required(execution, "order_type"), time_in_force=_required(execution, "time_in_force"),
        entrust_type=_required(execution, "entrust_type"), market=_required(broker, "market"),
        region=_required(broker, "region"), market_data_provider=_required(market_data, "provider"),
        paper_fill_price=market_data.get("paper_fill_price"),
    )
    if config.mode not in {"paper", "live"}:
        raise ValueError("mode must be paper or live")
    if config.market_data_provider != "webull":
        raise ValueError("market_data.provider must be webull")
    if not isinstance(config.strategy_config.get("target_qty"), int):
        raise ValueError("strategy.config.target_qty must be an integer")
    if any(not isinstance(rule, str) for rule in config.risk_rule_order):
        raise ValueError("risk.rules must be a list of strings")
    return config


def config_from_environment() -> AppConfig:
    path = os.environ.get("TRADEFRAME_CONFIG")
    if not path:
        raise RuntimeError("TRADEFRAME_CONFIG must point to a YAML configuration file")
    return load_config(path)


def _section(raw: dict[str, Any], name: str) -> dict[str, Any]:
    value = raw.get(name)
    if not isinstance(value, dict):
        raise ValueError(f"missing YAML section: {name}")
    return value


def _required(raw: dict[str, Any], name: str):
    if name not in raw:
        raise ValueError(f"missing YAML value: {name}")
    return raw[name]
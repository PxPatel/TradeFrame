from config.loader import load_config


def test_yaml_contains_runtime_and_strategy_parameters(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
mode: paper
symbol_allowlist: [MSFT]
runtime: {database_path: state.db, kill_switch_path: STOP}
strategy: {name: example_slow_swing, target_qty: 7}
risk: {max_orders_per_day: 2, max_position_notional: 1000, daily_loss_limit: 50, max_order_qty: 20}
execution: {order_type: LMT, time_in_force: GTC, entrust_type: QTY}
broker: {region: us, market: US}
market_data: {provider: webull, paper_fill_price: null}
""", encoding="utf-8")

    config = load_config(config_file)

    assert config.symbols == ("MSFT",)
    assert config.strategy_target_qty == 7
    assert config.order_type == "LMT"
    assert config.database_path == "state.db"
# TradeFrame

Safety-first automated trading system. The current implementation is a paper-trading vertical slice:

```bash
export TRADEFRAME_CONFIG=/workspaces/TradeFrame/config/base.yaml
python -m runners.run_strategy
```

The runner has no trade-defining CLI arguments. It loads symbols, strategy parameters, risk limits, paths, mode, and order settings from YAML; secrets come from environment variables. The execution order is always `market data -> strategy -> intent -> risk gate -> SQLite journal -> broker`. In paper mode, the broker fills immediately; repeated target intents become no-ops once the target position is reached.

Strategies are loaded through a registry (`strategies/registry.py`) and receive their own `strategy.config` block from YAML.

## Development

Set `TRADEFRAME_CONFIG` to a YAML file, export the Webull credentials from `.env.example`, and run `python -m runners.run_strategy`. Cron should invoke that module without trade arguments. Run `python -m compileall -q config core execution reconciliation strategies runners tests`. Install the test extra with `python -m pip install -e '.[test]'`, then run `python -m pytest`.

To flatten positions manually, run `python -m runners.run_flatten --confirm`.

## Webull integration status

The adapter follows the official `webull-inc/webull-openapi-python-sdk` samples: `TradeClient`, `account.get_account_position`, `order_v2.place_order` with a caller-generated `client_order_id`, and `order.list_open_orders`. Install the optional SDK with `python -m pip install -e '.[webull]'`.

The SDK requires app credentials, an account ID for live mode, region endpoint configuration where applicable, and its token/2FA storage. The runner uses Webull for market data and selects `PaperBroker` or `WebullBroker` from YAML. Before live use, capture and fixture one sanitized response for the account region, verify order status mapping, and run reconciliation against a paper account. No live mode is enabled by default.

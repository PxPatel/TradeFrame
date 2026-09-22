# TradeFrame Decisions

This file records core decisions that either narrow, extend, or currently differ from `trading-system-design-doc.md`. It is an implementation record, not a replacement for the design document.

## 1. Configuration Is the Runtime Contract

**Decision:** The system is configured from YAML and environment variables, with no trade-defining CLI arguments.

**Implementation:** `TRADEFRAME_CONFIG` selects the YAML file. YAML defines mode, symbols, strategy parameters, risk limits, database paths, kill-switch path, market, and order settings. Environment variables provide secrets and connection identity such as Webull app credentials and account ID.

**Reason:** A scheduled trading engine must run autonomously after deployment. CLI arguments such as symbol, target quantity, or price are operational injection points and are not part of the runtime contract.

**Deviation from design:** The design describes YAML configuration but did not define a concrete loader or precedence model. TradeFrame uses one explicit YAML file selected by `TRADEFRAME_CONFIG`; there is currently no implicit default configuration and no CLI override layer.

## 2. No Manual Price or Intent Injection

**Decision:** The strategy runner accepts no symbol, price, quantity, or intent arguments.

**Implementation:** `python -m runners.run_strategy` loads the configured strategy and symbols, fetches market data, constructs `MarketContext`, evaluates the strategy, and executes the resulting intents.

**Reason:** The runner is an autonomous engine, not a manual trading tool. Manual testing belongs in unit tests and fixtures rather than production runner arguments.

## 3. Market Data Is a Separate Dependency

**Decision:** Market data is represented by a `MarketDataProvider` abstraction and is fetched before strategy evaluation.

**Implementation:** `WebullMarketData` uses the official SDK `DataClient.market_data.get_snapshot`. The provider returns normalized prices and market-open state through `MarketSnapshot`.

**Reason:** Strategies must consume a market snapshot rather than know how data is sourced. This also keeps the Webull SDK outside the broker-agnostic core.

**Current limitation:** The implementation uses sequential snapshot requests and parses a small set of known response field names. A sanitized response fixture from the actual account region is required before live operation.

## 4. Paper and Live Brokers Are Selected by YAML

**Decision:** Broker selection is controlled by `mode` in YAML.

**Implementation:** `paper` creates `PaperBroker`; `live` creates `WebullBroker` and requires `WEBULL_ACCOUNT_ID` in the environment. Both use the same broker interface.

**Reason:** Paper/live behavior must be a configuration choice, not a code edit or a different runner.

**Safety boundary:** Market data is fetched from Webull in both modes. In paper mode, fetched prices are used for simulated fills, but no live order is submitted.

## 5. Paper State Is Hydrated From SQLite

**Decision:** Paper broker positions are initialized from the persisted state store on every process start.

**Reason:** Cron processes are short-lived. An in-memory paper broker would forget positions between runs and could calculate target deltas incorrectly after a restart.

**Deviation from design:** The design calls for a paper broker but does not explicitly define how its simulated account survives process boundaries. SQLite is the source used to hydrate paper positions.

## 6. Strategy Selection Is Explicitly Limited

**Decision:** The configured strategy name is validated against a known strategy implementation.

**Implementation:** The current runtime supports `example_slow_swing` and constructs it from YAML parameters.

**Reason:** Silent fallback to a different strategy is unsafe in an automated trading system.

**Current limitation:** There is not yet a general plugin registry. Adding another strategy currently requires adding it to the runtime composition layer and its configuration validation.

## 7. Risk State Must Be Real, Not Assumed

**Decision:** The runtime does not assume that the market is open or that daily loss is zero.

**Implementation:** Market-open state comes from the market-data snapshot. Realized P&L is recorded in SQLite fills and supplied to the risk manager each cycle. Missing/stale state is rejected by the risk gate.

**Reason:** Defaults such as `market_open=True` or `daily_realized_loss=0` would turn unavailable information into permission to trade.

**Current limitation:** The P&L calculation is intentionally simple and currently derives realized P&L from local fills. Broker-authoritative fill reconciliation must replace or correct it before live use.

## 8. Order Settings Are Configuration, Not Code Constants

**Decision:** Order type, time-in-force, and entrust type are loaded from YAML and passed through the engine and Webull adapter.

**Reason:** Broker order semantics and strategy risk posture must be changeable without editing code.

**Current limitation:** The core model currently supports market/limit order fields but does not yet model every Webull order option. Unsupported order types should be rejected during config validation rather than passed through blindly.

## 9. Client Order ID Is Created Locally Before Network I/O

**Decision:** The execution engine generates and persists a UUID client order ID before calling the broker.

**Reason:** This preserves the design's idempotency guarantee across crashes and ambiguous broker responses.

**Webull detail:** The Webull adapter sends this value as `client_order_id`, following the official SDK examples. Ambiguous server failures become `UNKNOWN` and are resolved by reconciliation rather than blindly retried.

## 10. Reconciliation Treats Broker State as Authority

**Decision:** Reconciliation compares broker and local positions plus open orders, including records present on only one side.

**Implementation:** Broker-only and local-only positions/orders are high-severity mismatches and activate the kill switch when configured.

**Reason:** An unrecorded broker position or unresolved order is more dangerous than a normal local quantity drift.

**Deviation from initial implementation:** The first reconciliation pass compared only broker-present positions. It was expanded to include local-only state and open orders because those are critical failure modes in the design.

## 11. Webull SDK Is Optional at Import Time

**Decision:** Core logic, tests, and paper broker code do not require the Webull SDK to be importable. The runtime fails explicitly when the configured Webull provider is started without the optional dependency.

**Reason:** Risk, strategy, state, and idempotency behavior must be testable without network access or broker credentials.

## 12. Secrets Are Environment-Only

**Decision:** Webull app key, app secret, account ID, and Telegram credentials are not stored in YAML or source code.

**Reason:** YAML is suitable for operational policy, not credentials. `.env.example` documents names only; deployment must provide the actual values through the environment or a secret manager.

## 13. Live Trading Is Not Yet Production-Ready

**Decision:** The code supports a live broker boundary, but live mode remains gated by configuration and explicit credential presence.

**Required before live use:**

- Capture sanitized real Webull account-region responses for snapshots, positions, open orders, and order placement.
- Verify all Webull status and field mappings against those fixtures.
- Add broker-authoritative fill reconciliation and accurate realized P&L handling.
- Add a live-mode startup confirmation or equivalent deployment guard.
- Run paper mode through the configured scheduler for an extended observation period.
- Verify the kill switch and reconciliation jobs independently.

## 14. Operational Invocation

The intended invocation is configuration-only:

```bash
export TRADEFRAME_CONFIG=/path/to/config.yaml
python -m runners.run_strategy
python -m runners.run_reconcile
```

Cron, systemd, or a future daemon may invoke these modules. None should provide trade parameters at invocation time.

# Personal Automated Trading System — Design Doc

**Stack:** Python · **Now:** cron-triggered · **Later:** always-on daemon on a VM
**Philosophy:** boringly reliable > clever. Every failure mode should degrade toward "do nothing" and "tell you," never toward "do something surprising."

---

## 1. Design principles (the why behind every decision below)

1. **Separate "decide" from "act."** Strategy logic never touches the broker directly. It emits *intents*. A separate execution layer turns intents into orders. This is the single most important seam in the system — it's what lets you swap a cron job for a daemon later without rewriting strategies, and what lets you paper-test without lying to your strategy code.
2. **The broker is a hostile, unreliable dependency.** Webull's API can time out, double-respond, rate-limit, or return stale state. Treat every call as "might fail, might succeed-but-I-never-heard-back." This is why idempotency and reconciliation aren't optional extras — they're the core of the execution layer.
3. **State lives in a database, not in memory or in your head.** A cron job that runs and dies has no memory. If "have I already bought today" lives only in a Python variable, you will double-order the first time the process restarts. SQLite file = your system's memory.
4. **Risk manager is a gate, not a suggestion.** Every order passes through it. It has veto power over everything, including the kill switch's own unwind logic (with a documented exception, below).
5. **Config over code changes.** Paper/live, kill switch, position limits — all in config/env, never hardcoded, never requiring a code edit + redeploy to flip.

---

## 2. High-level flow

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐     ┌──────────────┐
│  Scheduler   │────▶│   Strategy   │────▶│    Risk     │────▶│  Execution   │
│ (cron/loop)  │     │  (decide)    │     │  Manager    │     │  Engine      │
└─────────────┘     └──────────────┘     │  (gate)     │     │ (act, once)  │
                            │             └─────────────┘     └──────┬───────┘
                            │                                        │
                            ▼                                        ▼
                     ┌─────────────┐                          ┌─────────────┐
                     │   Market     │                          │   Webull    │
                     │   Data       │                          │   Client    │
                     └─────────────┘                          └──────┬──────┘
                                                                       │
                     ┌─────────────────────────────────────────────────┐
                     │              State Store (SQLite)                │
                     │  orders · fills · positions · intents · events   │
                     └─────────────────────┬─────────────────────────┘
                                            │
                     ┌──────────────────────┴──────────────────────┐
                     │        Reconciliation Loop (separate run)     │
                     │  compares broker truth vs local state         │
                     └────────────────────────────────────────────┘
                                            │
                     ┌──────────────────────┴──────────────────────┐
                     │   Notifier (Telegram) · Structured Logs       │
                     └───────────────────────────────────────────────┘
```

**Strategy never calls the broker.** It reads market data + current position state and produces an `Intent` (e.g. "target 100 shares of AAPL"). Everything downstream of that is the same regardless of which strategy produced it — this is what makes adding a 2nd, 3rd, 10th strategy cheap later.

---

## 3. Directory structure

```
trading-system/
├── pyproject.toml
├── .env.example                # never commit real .env
├── config/
│   ├── base.yaml                # shared defaults
│   ├── paper.yaml                # paper-mode overrides
│   └── live.yaml                 # live-mode overrides (position limits, etc.)
│
├── core/                         # broker-agnostic domain logic — no Webull imports here
│   ├── models.py                 # Intent, Order, Fill, Position, Event (dataclasses/pydantic)
│   ├── risk_manager.py           # the gate — see §6
│   ├── kill_switch.py            # see §7
│   └── state_store.py            # SQLite read/write, single source of truth
│
├── strategies/
│   ├── base.py                    # Strategy ABC: .evaluate(context) -> list[Intent]
│   ├── example_slow_swing.py      # your current 2-4x/period strategy
│   └── example_timed.py           # a scheduled/timed-execution variant
│
├── execution/
│   ├── engine.py                  # Intent -> Order, idempotency, retries — see §5
│   ├── webull_client.py           # thin wrapper around the Webull SDK/API
│   └── broker_interface.py        # ABC the engine talks to (Webull impl + a PaperBroker impl)
│
├── reconciliation/
│   └── reconciler.py              # runs standalone; compares broker vs local truth
│
├── observability/
│   ├── logging_setup.py           # structlog config, one place
│   └── notifier.py                # Telegram alert sender
│
├── runners/                       # entrypoints — the ONLY files cron/systemd ever calls
│   ├── run_strategy.py            # cron target: evaluate + trade one cycle
│   ├── run_reconcile.py           # cron target: reconciliation pass
│   └── run_daemon.py              # future: long-running loop version of the above
│
├── data/
│   └── trading.db                 # SQLite (gitignored)
│
├── logs/                          # gitignored, rotated
│
└── tests/
    ├── test_risk_manager.py
    ├── test_execution_idempotency.py
    └── fixtures/
```

Why this shape:
- `core/` has **zero** Webull imports. You can unit-test risk logic and strategy logic with no network, no mocking a whole SDK.
- `strategies/` are plug-ins. New strategy = new file + one line of config. They don't know or care whether they're called by cron or a daemon.
- `runners/` is the *only* place that knows about "how am I being invoked." Cron calls `run_strategy.py`; later, a systemd service calls `run_daemon.py`, which internally just calls the same strategy-evaluation function on a loop. Nothing else changes.

---

## 4. Core data model

Keep this small and boring — SQLite tables mirror these almost 1:1.

```python
# core/models.py
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import uuid

class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

class OrderStatus(str, Enum):
    PENDING = "PENDING"       # created locally, not yet sent
    SUBMITTED = "SUBMITTED"   # sent to broker, awaiting ack
    ACKED = "ACKED"           # broker confirmed receipt
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"       # broker call failed ambiguously — needs reconciliation

@dataclass
class Intent:
    """What a strategy WANTS to happen. Not an order yet."""
    id: str
    strategy_name: str
    symbol: str
    target_qty: int            # target position, not delta — makes idempotency simpler
    reason: str                 # human-readable, goes straight into logs
    created_at: datetime

@dataclass
class Order:
    """What execution actually attempted, keyed by a client-generated idempotency key."""
    client_order_id: str        # UUID generated locally — THE idempotency key
    intent_id: str
    broker_order_id: str | None
    symbol: str
    side: Side
    qty: int
    order_type: str              # MKT, LMT, etc.
    limit_price: float | None
    status: OrderStatus
    created_at: datetime
    updated_at: datetime
```

`client_order_id` is generated **before** any network call and stored in SQLite **before** the order is sent. This is the linchpin of idempotency (§5).

---

## 5. Execution engine: idempotency & safety

This is where retail systems usually get burned. The rules:

1. **Generate the idempotency key locally, persist it, then act.**
   ```python
   order = Order(client_order_id=str(uuid.uuid4()), status=OrderStatus.PENDING, ...)
   state_store.save_order(order)          # committed to disk BEFORE we call Webull
   response = webull_client.place_order(order)   # pass client_order_id if API supports it
   ```
   If the process crashes between save and send, you have a `PENDING` order on restart — a known, inspectable state, not a mystery. If it crashes between send and response, you have a `SUBMITTED` order — reconciliation resolves it (§8), you never blindly resend.

2. **Never re-derive "should I trade" from scratch on every tick without checking existing state.** Before creating a new intent's order, check: is there already an open/pending order for this symbol from this strategy today? If yes, don't submit a second one. This is what actually prevents double-orders on a re-run of a cron job (e.g., cron fires twice, or you manually rerun after a crash).

3. **Target-quantity intents, not delta intents.** A strategy says "I want 100 shares of AAPL," not "buy 20 more." The engine diffs target vs. current known position to compute the order. This makes re-running the same evaluation safe — if you already hit the target, re-evaluating produces a no-op intent instead of a duplicate buy.

4. **Retries are narrow and explicit.** Only retry on clearly-safe-to-retry failures (connection timeout *before* any response, documented transient error codes). Anything ambiguous (timeout *after* partial response, 5xx after the request plausibly reached the server) → mark `UNKNOWN`, alert, and let reconciliation sort it out against broker truth. Never auto-retry blindly on "any exception."

5. **One writer.** Only the execution engine writes orders/fills to the state store. Strategies and risk manager only read. This avoids a whole category of race conditions later if you go multi-strategy or daemonized.

---

## 6. Risk Manager — the non-negotiable gate

Every single intent, from every strategy, passes through one `RiskManager.evaluate(intent, context) -> Decision` call before it can become an order. No exceptions, no strategy-specific bypass.

```python
# core/risk_manager.py
@dataclass
class Decision:
    approved: bool
    adjusted_qty: int | None   # risk manager can clamp, not just reject
    reason: str

class RiskManager:
    def __init__(self, config: RiskConfig, state_store: StateStore):
        ...

    def evaluate(self, intent: Intent, context: MarketContext) -> Decision:
        checks = [
            self._check_kill_switch,
            self._check_max_position_size,
            self._check_max_notional_exposure,
            self._check_daily_loss_limit,
            self._check_order_rate_limit,        # e.g. max N orders/day, sanity for a 2-4x strategy
            self._check_symbol_allowlist,
            self._check_market_hours,
            self._check_price_sanity,             # reject if intended price is wildly off from last quote
            self._check_duplicate_intent,          # already-open order for this symbol today?
        ]
        for check in checks:
            decision = check(intent, context)
            if not decision.approved:
                log.warning("risk_rejected", check=check.__name__, reason=decision.reason, intent=intent)
                return decision
        return Decision(approved=True, adjusted_qty=intent.target_qty, reason="ok")
```

Design choices worth calling out:
- **Fail closed.** If the risk manager can't determine current position/exposure (e.g., state store is stale or broker is unreachable for a position check), the default is **reject**, not approve. Silence and uncertainty should never be interpreted as "safe to trade."
- **Hard-coded ceiling, config-tunable floor.** Put an absolute max order size / max notional in code as a sanity backstop (e.g., "never more than $X per single order, period") in addition to the config-driven limits. This protects you from a config typo (`max_position: 10000` instead of `100`) blowing up your account.
- **Given your strategy is 2–4 executions per period**, a rate limiter that flags "more than N orders today" is a cheap, high-value trip-wire — a runaway loop or a bug that re-fires intents will hit this almost immediately instead of silently spamming orders.
- **The risk manager checks the kill switch, but the kill switch does not go through the risk manager for its own unwind orders** — see §7 for why, and the one narrow exception that remains.

---

## 7. Kill switch

Two layers, because a kill switch that can itself get stuck is not a kill switch:

**Layer 1 — Halt (default, always safe):** A flag (file, env var, or DB row — file is simplest and most robust, since it works even if the DB is the thing that's broken: `data/KILL_SWITCH` existing = halted). When present:
- No new intents are evaluated.
- No new orders are submitted.
- Reconciliation still runs (you still want to know what your actual positions/orders are while halted).
- This is your default "something's wrong, stop everything" lever. Flip it by touching/deleting a file — no code deploy needed, works over SSH from your phone.

**Layer 2 — Flatten (explicit, separate command):** A distinct, manually-invoked action (`runners/run_flatten.py --confirm`) that closes all open positions. This is **not** triggered automatically by Layer 1 — halting and liquidating are different decisions with different risk profiles, and auto-liquidating on every halt trigger (e.g., a transient network blip) could itself cause harm. Flattening is a human decision; halting can be automatic.

Automatic triggers that set Layer 1 (halt):
- Daily loss limit breached
- Reconciliation finds an unresolvable mismatch (see §8)
- Repeated broker errors within a short window (e.g., 3 failed calls in 5 minutes)
- Order rate-limit tripped (looks like a bug, not a strategy)

All of these fire the halt file write **and** a notification. None of them auto-flatten.

The one exception mentioned above: flatten orders themselves still pass through the risk manager's *sizing sanity checks* (price sanity, symbol allowlist) — you don't want a bug in the flatten path to send a garbage order either — but they bypass the "max orders per day" and "duplicate intent" checks, since their entire purpose is to override normal trading limits.

---

## 8. Reconciliation loop

Runs as its own scheduled job (cron, or on-heartbeat if daemonized), independent of the strategy cycle. Its only job: **is local state store truth == broker truth?**

```python
# reconciliation/reconciler.py
def reconcile():
    broker_positions = webull_client.get_positions()
    broker_open_orders = webull_client.get_open_orders()
    local_positions = state_store.get_positions()
    local_open_orders = state_store.get_orders(status__in=["SUBMITTED", "ACKED", "UNKNOWN"])

    mismatches = diff(broker_positions, local_positions) + diff(broker_open_orders, local_open_orders)

    if mismatches:
        log.error("reconciliation_mismatch", mismatches=mismatches)
        notifier.alert(f"Reconciliation mismatch: {summarize(mismatches)}")
        if any(m.severity == "high" for m in mismatches):
            kill_switch.halt(reason="unresolved reconciliation mismatch")
    else:
        log.info("reconciliation_ok")
```

What counts as high severity: a broker position/order that local state has **no record of at all** (something traded without your system's knowledge — most dangerous), or a `UNKNOWN`-status order that's been unresolved past a timeout. Quantity mismatches on known positions can often self-heal (just update local truth from broker truth, since broker is always the source of truth for "what actually happened") — but always log it either way, even the auto-healed ones, so you can spot a pattern.

**Broker state is always the source of truth.** Local state store is a cache/journal of *intent and attempted actions*, not authority. Reconciliation's job is to pull local state back in line with the broker, never the reverse.

---

## 9. Logging — sensible, not noisy

One config, structured, in `observability/logging_setup.py`, imported everywhere else. Use `structlog` (or stdlib `logging` with a JSON formatter if you want zero extra dependency weight) — key/value structured logs, not sentence-formatted strings, so you can grep/filter later without regex archaeology.

**Levels, used consistently:**
- `DEBUG` — market data pulls, intermediate calculations. Off by default, on when you're actively debugging a strategy.
- `INFO` — the "normal operation" trail: intent generated, risk decision, order submitted, order filled, reconciliation OK. This is your default level and should read like a clean story of what happened, in order, without you needing DEBUG to follow it.
- `WARNING` — risk rejection, retried-but-recovered errors, halted state encountered on startup.
- `ERROR` — reconciliation mismatch, unresolvable broker error, kill switch auto-triggered.

**Rules to avoid fatigue:**
- One log line per meaningful event, not per function call. "intent_created," "risk_decision," "order_submitted," "order_filled" — not a log line for every loop iteration or every field access.
- Every log line carries structured context (`symbol`, `strategy_name`, `client_order_id`, `intent_id`) so a single order's whole lifecycle is `grep`-able by ID across the file.
- Log to both console (for cron's stdout capture) and a rotating file (`logs/trading.log`, rotate daily or by size, keep ~30 days). `logging.handlers.RotatingFileHandler` or `TimedRotatingFileHandler` is plenty — no need for a log aggregation stack at this scale.
- Every run of `run_strategy.py` starts and ends with one summary line (`run_started`, `run_completed` with duration + outcome count) so you can scan logs day-to-day at a glance without reading every line.

---

## 10. Config & modes

```yaml
# config/base.yaml
mode: paper                 # paper | live — THE most important flag in the system
max_orders_per_day: 6
max_position_notional: 5000
daily_loss_limit: 200
symbol_allowlist: [AAPL, MSFT, SPY]
reconciliation_interval_minutes: 15
```

- `mode: paper` routes execution to `PaperBroker` (simulated fills against real market data) instead of `WebullBroker` — same interface (`broker_interface.py`), so strategy/risk code has zero awareness of which one it's talking to.
- Never let `mode` default to `live` implicitly. `base.yaml` defaults to `paper`; going live requires an explicit `--mode live` flag or `TRADING_MODE=live` env var at invocation, ideally with a confirmation prompt/flag the first time each day.
- Secrets (Webull credentials/tokens) live in `.env`, loaded via `python-dotenv` or environment, never in YAML, never committed.

---

## 11. Deployment path

**Now — cron, matches your current strategy:**
```
# crontab -e
*/30 9-16 * * 1-5   cd /path/to/trading-system && .venv/bin/python -m runners.run_strategy >> logs/cron.log 2>&1
*/15 9-16 * * 1-5   cd /path/to/trading-system && .venv/bin/python -m runners.run_reconcile >> logs/cron.log 2>&1
```
Simple, restart-safe (idempotency handles a double-fire), no always-on process to babysit on your laptop.

**Later — VM, when a strategy needs continuous monitoring:**
- `runners/run_daemon.py` wraps the same `evaluate → risk → execute` cycle in a loop with a sleep/heartbeat, instead of cron re-invoking the process.
- Run under `systemd` (a `.service` unit with `Restart=on-failure`) rather than `nohup`/`screen`, so a crash auto-restarts and you get real logs via `journalctl`.
- The reconciliation loop becomes a second systemd service (or a thread/async task in the same daemon) instead of a second crontab line.
- **Nothing in `core/`, `strategies/`, `execution/`, or `risk_manager` changes for this move.** Only `runners/` and the process supervisor change — which is the payoff of the "decide vs act vs invoke" separation from §1.

Either way, **the SQLite file is the thing to back up.** A simple daily copy to another disk/cloud folder is enough at this scale — don't reach for Postgres/replication until you actually have a reason to (multi-process concurrent writers being the main one).

---

## 12. Notifications — recommendation

Go with **Telegram** over email or console-only:
- A bot + `python-telegram-bot` (or even just `requests` against the Bot API, no dependency needed) gets you push notifications to your phone in ~10 lines of code.
- Free, no rate-limit concerns at your volume, no SMTP setup/deliverability headaches like email.
- Works identically whether the caller is a cron job on your laptop or a systemd service on a VM later — no infra dependency.

```python
# observability/notifier.py
import requests

def alert(message: str, level: str = "info"):
    prefix = {"info": "ℹ️", "warning": "⚠️", "error": "🚨"}[level]
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": f"{prefix} {message}"},
        timeout=5,
    )
```
Wire this to: kill switch triggers, reconciliation mismatches, order rejections by risk manager, and unhandled exceptions in any runner — not to routine "order filled successfully" events, or you'll start ignoring the channel. Console/file logs already have the full story; Telegram is for "you need to look at this."

---

## 13. What to build first (suggested order)

1. `core/models.py` + `core/state_store.py` (SQLite schema) — nothing works without this.
2. `execution/broker_interface.py` + `PaperBroker` implementation — lets you test the whole pipeline with zero real API risk.
3. `core/risk_manager.py` with the checks in §6, tested against `PaperBroker`.
4. `strategies/base.py` + one real strategy, running fully in paper mode via `runners/run_strategy.py` on cron.
5. `core/kill_switch.py` + `reconciliation/reconciler.py`.
6. `execution/webull_client.py` real implementation — only plug this in once 1–5 have run clean in paper mode for a stretch you're comfortable with.
7. `observability/notifier.py` wired to the trigger points above.

This order means you have a fully safe, fully observable, paper-trading system running on cron before Webull's real API ever gets a live order from you — and the swap from paper to live is a one-flag change, not a rewrite.
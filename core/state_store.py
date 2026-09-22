import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .models import Intent, Order, OrderStatus, Position, Side


def _timestamp(value: datetime) -> str:
    return value.isoformat()


class StateStore:
    """Small SQLite journal. Each operation commits before returning."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self):
        with self._connection() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS intents (
                    id TEXT PRIMARY KEY, strategy_name TEXT NOT NULL, symbol TEXT NOT NULL,
                    target_qty INTEGER NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS orders (
                    client_order_id TEXT PRIMARY KEY, intent_id TEXT NOT NULL, broker_order_id TEXT,
                    symbol TEXT NOT NULL, side TEXT NOT NULL, qty INTEGER NOT NULL,
                    order_type TEXT NOT NULL, limit_price REAL, status TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS orders_symbol_status ON orders(symbol, status);
                CREATE TABLE IF NOT EXISTS positions (
                    symbol TEXT PRIMARY KEY, quantity INTEGER NOT NULL, average_price REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS fills (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, client_order_id TEXT NOT NULL,
                    symbol TEXT NOT NULL, side TEXT NOT NULL, qty INTEGER NOT NULL,
                    fill_price REAL NOT NULL, realized_pnl REAL NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL,
                    payload TEXT NOT NULL, created_at TEXT NOT NULL
                );
            """)

    def save_intent(self, intent: Intent):
        with self._connection() as connection:
            connection.execute("INSERT OR IGNORE INTO intents VALUES (?, ?, ?, ?, ?, ?)",
                (intent.id, intent.strategy_name, intent.symbol, intent.target_qty,
                 intent.reason, _timestamp(intent.created_at)))

    def save_order(self, order: Order):
        with self._connection() as connection:
            connection.execute("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (order.client_order_id, order.intent_id, order.broker_order_id, order.symbol,
                 order.side.value, order.qty, order.order_type, order.limit_price,
                 order.status.value, _timestamp(order.created_at), _timestamp(order.updated_at)))

    def update_order(self, order: Order):
        with self._connection() as connection:
            connection.execute("UPDATE orders SET broker_order_id=?, status=?, updated_at=? WHERE client_order_id=?",
                (order.broker_order_id, order.status.value, _timestamp(order.updated_at), order.client_order_id))

    def get_open_orders(self, symbol: str | None = None) -> list[Order]:
        statuses = tuple(status.value for status in
                         (OrderStatus.PENDING, OrderStatus.SUBMITTED, OrderStatus.ACKED,
                          OrderStatus.PARTIAL, OrderStatus.UNKNOWN))
        placeholders = ",".join("?" for _ in statuses)
        query = f"SELECT * FROM orders WHERE status IN ({placeholders})"
        params: list[object] = list(statuses)
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        with self._connection() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._order(row) for row in rows]

    def count_orders_since(self, start: datetime) -> int:
        with self._connection() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM orders WHERE created_at >= ?",
                                     (_timestamp(start),)).fetchone()
        return int(row["count"])

    def get_position(self, symbol: str) -> Position:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM positions WHERE symbol = ?", (symbol,)).fetchone()
        return Position(symbol, int(row["quantity"]), float(row["average_price"])) if row else Position(symbol, 0, 0.0)

    def get_positions(self) -> list[Position]:
        with self._connection() as connection:
            rows = connection.execute("SELECT * FROM positions").fetchall()
        return [Position(row["symbol"], int(row["quantity"]), float(row["average_price"])) for row in rows]

    def save_position(self, position: Position):
        with self._connection() as connection:
            connection.execute("INSERT INTO positions VALUES (?, ?, ?) ON CONFLICT(symbol) DO UPDATE SET quantity=excluded.quantity, average_price=excluded.average_price",
                (position.symbol, position.quantity, position.average_price))

    def record_fill(self, client_order_id: str, symbol: str, side: Side, qty: int,
                    fill_price: float, realized_pnl: float):
        with self._connection() as connection:
            connection.execute("INSERT INTO fills(client_order_id, symbol, side, qty, fill_price, realized_pnl, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                               (client_order_id, symbol, side.value, qty, fill_price, realized_pnl,
                                _timestamp(datetime.now())))

    def get_daily_realized_loss(self) -> float:
        today = datetime.now().date().isoformat()
        with self._connection() as connection:
            row = connection.execute("SELECT COALESCE(SUM(realized_pnl), 0) AS pnl FROM fills WHERE substr(created_at, 1, 10) = ?",
                                     (today,)).fetchone()
        return max(0.0, -float(row["pnl"]))

    def record_event(self, event_type: str, payload: dict):
        with self._connection() as connection:
            connection.execute("INSERT INTO events(event_type, payload, created_at) VALUES (?, ?, ?)",
                               (event_type, json.dumps(payload, sort_keys=True), _timestamp(datetime.now())))

    @staticmethod
    def _order(row: sqlite3.Row) -> Order:
        return Order(row["client_order_id"], row["intent_id"], row["broker_order_id"], row["symbol"],
                     Side(row["side"]), row["qty"], row["order_type"], row["limit_price"],
                     OrderStatus(row["status"]), datetime.fromisoformat(row["created_at"]),
                     datetime.fromisoformat(row["updated_at"]))
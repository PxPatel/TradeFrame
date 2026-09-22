"""Webull OpenAPI adapter.

The official SDK exposes ``TradeClient.order_v2`` and accepts a
``client_order_id`` in the order payload. The SDK is optional so all core and
paper tests run without credentials or network access. Response payloads are
intentionally normalized here because the API's regional schemas differ.
"""

from datetime import datetime, timezone

from core.models import MarketSnapshot, Order, OrderStatus, Position, Side
from .broker_interface import Broker, BrokerOrderResult, MarketDataProvider


class WebullBroker(Broker):
    def __init__(self, api_client, account_id: str, *, region: str, market: str,
                 order_type: str, time_in_force: str, entrust_type: str):
        self.trade_client = self._load_trade_client(api_client)
        self.account_id = account_id
        self.region = region
        self.market = market
        self.order_type = order_type
        self.time_in_force = time_in_force
        self.entrust_type = entrust_type

    @staticmethod
    def _load_trade_client(api_client):
        try:
            from webull.trade.trade_client import TradeClient
        except ImportError as exc:
            raise RuntimeError("Install tradeframe[webull] to use the Webull broker") from exc
        return TradeClient(api_client)

    def place_order(self, order: Order) -> BrokerOrderResult:
        payload = {
            "client_order_id": order.client_order_id,
            "symbol": order.symbol,
            "instrument_type": "EQUITY",
            "market": self.market,
            "order_type": self.order_type,
            "quantity": str(order.qty),
            "side": order.side.value,
            "time_in_force": self.time_in_force,
            "entrust_type": self.entrust_type,
        }
        if order.limit_price is not None:
            payload["limit_price"] = str(order.limit_price)
        try:
            response = self.trade_client.order_v2.place_order(self.account_id, [payload])
        except (TimeoutError, ConnectionError):
            raise
        if response.status_code >= 500:
            raise TimeoutError("Webull returned a server error; order outcome is ambiguous")
        if response.status_code != 200:
            return BrokerOrderResult(OrderStatus.REJECTED)
        body = response.json() or {}
        broker_id = str(body.get("order_id") or body.get("orderId") or order.client_order_id)
        return BrokerOrderResult(OrderStatus.SUBMITTED, broker_id)

    def get_positions(self) -> list[Position]:
        response = self.trade_client.account.get_account_position(self.account_id)
        if response.status_code != 200:
            raise ConnectionError(f"Webull positions request failed: {response.status_code}")
        values = response.json() or []
        if isinstance(values, dict):
            values = values.get("positions", values.get("data", []))
        return [Position(str(value.get("symbol")), int(float(value.get("quantity", 0))),
                         float(value.get("average_price", value.get("avg_price", 0)))) for value in values]

    def get_open_orders(self) -> list[Order]:
        response = self.trade_client.order.list_open_orders(self.account_id, page_size=100)
        if response.status_code != 200:
            raise ConnectionError(f"Webull open-orders request failed: {response.status_code}")
        values = response.json() or []
        if isinstance(values, dict):
            values = values.get("orders", values.get("data", []))
        orders = []
        for value in values:
            status = str(value.get("status", "UNKNOWN")).upper()
            try:
                order_status = OrderStatus(status)
            except ValueError:
                order_status = OrderStatus.UNKNOWN
            orders.append(Order(
                str(value.get("client_order_id", value.get("clientOrderId", ""))),
                "reconciled", str(value.get("order_id", value.get("orderId", ""))),
                str(value.get("symbol", "")), Side(str(value.get("side", "BUY")).upper()),
                int(float(value.get("quantity", value.get("qty", 0)))),
                str(value.get("order_type", self.order_type)), None, order_status,
                datetime.now(timezone.utc), datetime.now(timezone.utc)))
        return orders


class WebullMarketData(MarketDataProvider):
    """Snapshot market-data adapter backed by the official Webull SDK."""

    def __init__(self, api_client, *, market: str):
        try:
            from webull.data.data_client import DataClient
        except ImportError as exc:
            raise RuntimeError("Install tradeframe[webull] to use Webull market data") from exc
        self.data_client = DataClient(api_client)
        self.market = market

    def get_snapshot(self, symbols: list[str]) -> MarketSnapshot:
        try:
            from webull.data.common.category import Category
            category = getattr(Category, f"{self.market.upper()}_STOCK").name
        except (ImportError, AttributeError) as exc:
            raise RuntimeError(f"Unsupported Webull market category: {self.market}") from exc

        prices = {}
        market_states = []
        for symbol in symbols:
            response = self.data_client.market_data.get_snapshot(
                symbol, category, extend_hour_required=False, overnight_required=False)
            if response.status_code != 200:
                raise ConnectionError(f"Webull snapshot request failed for {symbol}: {response.status_code}")
            price = self._extract_last_price(response.json() or {}, symbol)
            if price is None:
                raise ValueError(f"Webull snapshot for {symbol} did not contain a usable last price")
            prices[symbol] = price
            market_states.append(self._extract_market_open(response.json() or {}))
        return MarketSnapshot(prices, bool(market_states) and all(market_states))

    def get_prices(self, symbols: list[str]) -> dict[str, float]:
        return self.get_snapshot(symbols).prices

    @staticmethod
    def _extract_last_price(payload: dict, symbol: str) -> float | None:
        values = payload.get("data", payload)
        if isinstance(values, list):
            values = next((item for item in values if item.get("symbol") == symbol), values[0] if values else {})
        for key in ("last_price", "lastPrice", "latest", "latest_price", "close"):
            value = values.get(key) if isinstance(values, dict) else None
            if value not in (None, ""):
                return float(value)
        return None

    @staticmethod
    def _extract_market_open(payload: dict) -> bool:
        values = payload.get("data", payload)
        if isinstance(values, list):
            values = values[0] if values else {}
        status = values.get("market_status", values.get("marketStatus")) if isinstance(values, dict) else None
        if isinstance(status, bool):
            return status
        if isinstance(status, str):
            return status.upper() in {"OPEN", "RTH", "PRE", "POST", "TRADING"}
        return bool(values.get("is_market_open", False)) if isinstance(values, dict) else False
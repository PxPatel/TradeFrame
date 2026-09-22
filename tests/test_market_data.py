from execution.webull_client import WebullMarketData


def test_extract_last_price_supports_webull_snapshot_shapes():
    assert WebullMarketData._extract_last_price({"lastPrice": "185.25"}, "AAPL") == 185.25
    assert WebullMarketData._extract_last_price({"data": [{"symbol": "AAPL", "close": 184}]}, "AAPL") == 184.0
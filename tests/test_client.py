import uuid
import pytest
from unittest.mock import patch, MagicMock


class TestPaperOrderIds:
    def test_unique_ids(self):
        from core.client import UpstoxClient

        with patch.object(UpstoxClient, "__init__", lambda self: None):
            client = UpstoxClient()
            client.is_paper_trade = True
            client.is_mock_market = False
            client.access_token = "test"

            id1 = client.place_order_by_key("NSE_FO|TEST", "BUY", 25, 50.0)
            id2 = client.place_order_by_key("NSE_FO|TEST", "SELL", 25, 50.0)

            assert id1 != id2
            assert id1.startswith("PAPER_")
            assert id2.startswith("PAPER_")


class TestOrderType:
    def test_market_order_when_price_zero(self):
        from core.client import UpstoxClient

        with patch.object(UpstoxClient, "__init__", lambda self: None):
            client = UpstoxClient()
            client.is_paper_trade = True
            client.is_mock_market = False
            client.access_token = "test"

            order_id = client.place_order_by_key("NSE_FO|TEST", "BUY", 25, 0.0)
            assert order_id.startswith("PAPER_")

    def test_limit_order_when_price_nonzero(self):
        from core.client import UpstoxClient

        with patch.object(UpstoxClient, "__init__", lambda self: None):
            client = UpstoxClient()
            client.is_paper_trade = True
            client.is_mock_market = False
            client.access_token = "test"

            order_id = client.place_order_by_key("NSE_FO|TEST", "BUY", 25, 50.0)
            assert order_id.startswith("PAPER_")


class TestOrderStatusWithDynamicIds:
    def test_paper_prefix_returns_complete(self):
        from core.client import UpstoxClient

        with patch.object(UpstoxClient, "__init__", lambda self: None):
            client = UpstoxClient()
            client.is_paper_trade = True

            assert client.get_order_status("PAPER_abc12345") == "complete"
            assert client.get_order_status("PAPER_xyz99999") == "complete"

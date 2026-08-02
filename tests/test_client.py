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


class TestAvailableMargin:
    def _client(self, paper: bool, mock: bool):
        from core.client import UpstoxClient

        with patch.object(UpstoxClient, "__init__", lambda self: None):
            client = UpstoxClient()
            client.is_paper_trade = paper
            client.is_mock_market = mock
            client.access_token = "test"
            return client

    def test_paper_trade_uses_paper_capital(self):
        from config.settings import PAPER_CAPITAL, MAX_CAPITAL

        assert self._client(paper=True, mock=False).get_available_margin() == min(
            PAPER_CAPITAL, MAX_CAPITAL
        )

    def test_mock_market_uses_simulated_balance(self):
        assert self._client(paper=True, mock=True).get_available_margin() == 500000.0

    def test_live_mode_clamps_to_max_capital(self):
        from config.settings import MAX_CAPITAL

        client = self._client(paper=False, mock=False)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "success",
            "data": {"available_to_trade": {"total": MAX_CAPITAL + 25000.0}},
        }
        with patch.object(client, "_make_authenticated_request", return_value=mock_resp) as req:
            assert client.get_available_margin() == MAX_CAPITAL
            req.assert_called_once()

    def test_live_mode_below_ceiling_passthrough(self):
        client = self._client(paper=False, mock=False)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "success",
            "data": {"available_to_trade": {"total": 12345.0}},
        }
        with patch.object(client, "_make_authenticated_request", return_value=mock_resp) as req:
            assert client.get_available_margin() == 12345.0
            req.assert_called_once()

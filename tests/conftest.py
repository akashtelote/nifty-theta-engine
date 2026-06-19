import os
import pytest

# Force test-safe environment before any imports
os.environ.setdefault("PAPER_TRADE", "True")
os.environ.setdefault("MOCK_MARKET", "True")
os.environ.setdefault("DATABASE_URL", "postgresql://wheelbot:securepassword@localhost:5432/wheeldb_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")


@pytest.fixture
def mock_client(monkeypatch):
    """Provides a mock UpstoxClient that returns controllable values."""
    from unittest.mock import MagicMock
    client = MagicMock()
    client.is_paper_trade = True
    client.is_mock_market = True
    client.get_india_vix.return_value = 14.5
    client.get_available_margin.return_value = 500000.0
    client.get_market_quote_ltp.return_value = 22000.0
    client.get_order_status.return_value = "complete"
    client.place_order_by_key.return_value = "PAPER_test1234"
    client.cancel_order.return_value = True
    client.get_positions.return_value = []
    return client


@pytest.fixture
def mock_notifier():
    from unittest.mock import MagicMock
    return MagicMock()


@pytest.fixture
def mock_db_pool():
    """Provides a mock connection pool."""
    from unittest.mock import MagicMock
    pool = MagicMock()
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    cursor.fetchone.return_value = [True]  # For pg_try_advisory_lock
    conn.cursor.return_value = cursor
    pool.getconn.return_value = conn
    return pool


@pytest.fixture
def wheel(mock_client, mock_notifier, mock_db_pool, monkeypatch):
    """Provides a WheelStateMachine with all external dependencies mocked."""
    from strategies.wheel_strategy import WheelStateMachine

    # Patch __init__ to avoid real DB/API connections
    original_init = WheelStateMachine.__init__

    def patched_init(self):
        self.db_url = "postgresql://test:test@localhost/test"
        self._pool = mock_db_pool
        self.state = {}
        self.client = mock_client
        self.notifier = mock_notifier

    monkeypatch.setattr(WheelStateMachine, "__init__", patched_init)
    instance = WheelStateMachine()
    monkeypatch.setattr(WheelStateMachine, "__init__", original_init)

    # Patch _load_state to return self.state (avoid DB calls)
    monkeypatch.setattr(instance, "_load_state", lambda: instance.state)
    # Patch _save_state to be a no-op (avoid DB calls)
    monkeypatch.setattr(instance, "_save_state", lambda symbol: None)
    # Patch _archive_trade to be a no-op (avoid DB calls)
    monkeypatch.setattr(instance, "_archive_trade", lambda symbol, reason, pnl: None)

    return instance

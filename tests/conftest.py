import os
import pytest

# Force test-safe environment before any imports
os.environ.setdefault("PAPER_TRADE", "True")
os.environ.setdefault("MOCK_MARKET", "True")
os.environ.setdefault("DATABASE_URL", "postgresql://wheelbot:securepassword@localhost:5432/wheeldb_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")


@pytest.fixture(autouse=True)
def _stage6_entry_gates_open(monkeypatch):
    """Keep Stage-6 entry filters from blocking unit tests (unless a test overrides)."""
    from config import settings as settings_mod
    monkeypatch.setattr(settings_mod.settings, "SKIP_LOW_IVR", False)
    monkeypatch.setattr(settings_mod.settings, "EVENT_BLACKOUT_ENABLED", False)
    monkeypatch.setattr(settings_mod.settings, "TREND_FILTER_ENABLED", False)
    monkeypatch.setattr(settings_mod.settings, "ALLOW_SAME_WEEK_REENTRY", False)


@pytest.fixture(autouse=True)
def _pin_backtest_lot_size(monkeypatch):
    """Pin the backtest contract size so tests never depend on a downloaded file.

    PCSParams defaults lot_size from data/nse_fo_instruments.csv — a gitignored 9.5MB
    runtime artifact that exists on a dev box which has run the bot and never on a
    fresh checkout. Seven tests passed locally and failed in CI on exactly that.
    Patched here rather than at each call site because sweep_exit_params builds its
    own PCSParams inside backtest.py, where no test can reach the constructor.

    65 is the NSE Nifty lot these tests are written against. This does not blind us to
    a regression in the real lookup: tests/test_settings.py::TestLotSizeFromMaster
    exercises lot_size_from_master directly, including the missing-master path.
    """
    import backtest

    monkeypatch.setattr(backtest, "nifty_lot_size", lambda: 65)


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
    client.get_order_fill_price.return_value = None
    # Real NSE Nifty option lot size — tests must size the contract the exchange lists.
    client.get_lot_size.return_value = 65
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
        import threading
        self.db_url = "postgresql://test:test@localhost/test"
        self._pool = mock_db_pool
        self.state = {}
        self.client = mock_client
        self.notifier = mock_notifier
        self._exit_thresholds = {}
        self._exit_in_progress = set()
        self._exit_lock = threading.Lock()
        self._breach_first_seen = {}
        self.DEBOUNCE_SECONDS = 5.0
        self.INDEX_INSTRUMENT_KEYS = {"Nifty 50": "NSE_INDEX|Nifty 50"}

    monkeypatch.setattr(WheelStateMachine, "__init__", patched_init)
    instance = WheelStateMachine()
    monkeypatch.setattr(WheelStateMachine, "__init__", original_init)

    # Patch _load_state to return self.state (avoid DB calls)
    monkeypatch.setattr(instance, "_load_state", lambda: instance.state)
    # Patch _save_state to be a no-op (avoid DB calls)
    monkeypatch.setattr(instance, "_save_state", lambda symbol: None)
    # Patch _archive_trade to be a no-op (avoid DB calls)
    monkeypatch.setattr(
        instance, "_archive_trade", lambda symbol, reason, pnl, exit_slippage_per_leg=None: None
    )

    return instance

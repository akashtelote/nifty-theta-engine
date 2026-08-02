import threading
import time
import psycopg2
import psycopg2.pool
import os
import logging
from datetime import datetime, date
import pytz
import polars as pl
from core.client import UpstoxClient
import math
from core.notifier import Notifier
from config.settings import (
    LOT_SIZES,
    ALLOCATION_PCT_PER_TRADE,
    EXIT_SLIPPAGE_BUFFER_PCT,
    MAX_CAPITAL,
    settings,
    vix_regime_otm,
    get_redis_client,
)
from config.event_calendar import in_event_blackout
from core.ivr import ivr_allows_entry
from core.trend_filter import trend_allows_entry

logger = logging.getLogger(__name__)

IST = pytz.timezone('Asia/Kolkata')

class WheelStateMachine:
    def __init__(self):
        """
        Initializes the Wheel Strategy State Machine.
        Safely connects to the PostgreSQL database using DATABASE_URL.
        """
        self.db_url = os.getenv("DATABASE_URL", "postgresql://wheelbot:securepassword@localhost:5432/wheeldb")
        self._pool = psycopg2.pool.SimpleConnectionPool(1, 5, self.db_url)
        self._ensure_tables()

        self.state = self._load_state()
        self.client = UpstoxClient()
        self.notifier = Notifier()

        self._exit_thresholds: dict[str, dict] = {}
        self._exit_in_progress: set[str] = set()
        self._exit_lock = threading.Lock()
        self._breach_first_seen: dict[str, float] = {}
        self.DEBOUNCE_SECONDS = 5.0

        self.INDEX_INSTRUMENT_KEYS = {"Nifty 50": "NSE_INDEX|Nifty 50"}

    def _ensure_tables(self):
        conn = None
        try:
            conn = self._pool.getconn()
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS trade_history (
                    id SERIAL PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    short_instrument_key TEXT,
                    short_strike DOUBLE PRECISION,
                    short_entry_price DOUBLE PRECISION,
                    long_instrument_key TEXT,
                    long_strike DOUBLE PRECISION,
                    long_entry_price DOUBLE PRECISION,
                    quantity INTEGER,
                    net_credit_received DOUBLE PRECISION,
                    exit_reason TEXT,
                    realized_pnl DOUBLE PRECISION,
                    trade_date TEXT,
                    expiry_date TEXT,
                    closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.commit()
        except Exception as e:
            logger.error(f"Error ensuring tables exist: {e}")
        finally:
            if conn:
                self._pool.putconn(conn)

    def _load_state(self) -> dict:
        """
        Loads state from the PostgreSQL database and parses it into the nested dictionary format.
        """
        state = {}
        conn = None
        try:
            conn = self._pool.getconn()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT symbol, current_stage, short_instrument_key, short_strike, short_entry_price, short_order_id,
                       long_instrument_key, long_strike, long_entry_price, long_order_id, quantity, net_credit_received,
                       trade_date, expiry_date, realized_pnl
                FROM index_spread_state
            ''')
            rows = cursor.fetchall()
            for row in rows:
                (symbol, current_stage, short_instrument_key, short_strike, short_entry_price, short_order_id,
                 long_instrument_key, long_strike, long_entry_price, long_order_id, quantity, net_credit_received,
                 trade_date, expiry_date, realized_pnl) = row

                state[symbol] = {
                    "current_stage": current_stage,
                    "active_position": None if short_instrument_key is None else {
                        "instrument_key": short_instrument_key,
                        "strike": short_strike,
                        "expiry": expiry_date,
                        "entry_price": short_entry_price,
                        "order_id": short_order_id,
                        "quantity": quantity
                    },
                    "hedge_position": None if long_instrument_key is None else {
                        "instrument_key": long_instrument_key,
                        "strike": long_strike,
                        "expiry": expiry_date,
                        "entry_price": long_entry_price,
                        "order_id": long_order_id,
                        "quantity": quantity
                    },
                    "net_credit_received": net_credit_received if net_credit_received is not None else 0.0,
                    "realized_pnl": realized_pnl if realized_pnl is not None else 0.0
                }
        except psycopg2.Error as e:
            logger.error(f"Error loading state from database: {e}")
        finally:
            if conn:
                self._pool.putconn(conn)
        return state

    def _save_state(self, symbol: str):
        """
        Saves the state for a specific symbol to the PostgreSQL database.
        """
        symbol_state = self.state.get(symbol)
        if not symbol_state:
            return

        current_stage = symbol_state.get("current_stage", "IDLE")
        active_position = symbol_state.get("active_position")
        hedge_position = symbol_state.get("hedge_position")
        net_credit_received = symbol_state.get("net_credit_received", 0.0)
        realized_pnl = symbol_state.get("realized_pnl", 0.0)

        if active_position:
            short_instrument_key = active_position.get("instrument_key")
            short_strike = active_position.get("strike")
            short_entry_price = active_position.get("entry_price")
            short_order_id = active_position.get("order_id")
            quantity = active_position.get("quantity")
            expiry_date = active_position.get("expiry")
            trade_date = date.today().isoformat()
        else:
            short_instrument_key = None
            short_strike = None
            short_entry_price = None
            short_order_id = None
            quantity = None
            expiry_date = None
            trade_date = None

        if hedge_position:
            long_instrument_key = hedge_position.get("instrument_key")
            long_strike = hedge_position.get("strike")
            long_entry_price = hedge_position.get("entry_price")
            long_order_id = hedge_position.get("order_id")
            if quantity is None:
                quantity = hedge_position.get("quantity")
            # expiry_date should be the same as short
            if not expiry_date:
                expiry_date = hedge_position.get("expiry")
        else:
            long_instrument_key = None
            long_strike = None
            long_entry_price = None
            long_order_id = None

        conn = None
        try:
            conn = self._pool.getconn()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO index_spread_state
                (symbol, current_stage, short_instrument_key, short_strike, short_entry_price, short_order_id,
                 long_instrument_key, long_strike, long_entry_price, long_order_id, quantity, net_credit_received,
                 trade_date, expiry_date, realized_pnl)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (symbol) DO UPDATE SET
                    current_stage = EXCLUDED.current_stage,
                    short_instrument_key = EXCLUDED.short_instrument_key,
                    short_strike = EXCLUDED.short_strike,
                    short_entry_price = EXCLUDED.short_entry_price,
                    short_order_id = EXCLUDED.short_order_id,
                    long_instrument_key = EXCLUDED.long_instrument_key,
                    long_strike = EXCLUDED.long_strike,
                    long_entry_price = EXCLUDED.long_entry_price,
                    long_order_id = EXCLUDED.long_order_id,
                    quantity = EXCLUDED.quantity,
                    net_credit_received = EXCLUDED.net_credit_received,
                    trade_date = EXCLUDED.trade_date,
                    expiry_date = EXCLUDED.expiry_date,
                    realized_pnl = EXCLUDED.realized_pnl
            ''', (symbol, current_stage, short_instrument_key, short_strike, short_entry_price, short_order_id,
                  long_instrument_key, long_strike, long_entry_price, long_order_id, quantity, net_credit_received,
                  trade_date, expiry_date, realized_pnl))
            conn.commit()
        except psycopg2.Error as e:
            logger.error(f"Error saving state to database for {symbol}: {e}")
        finally:
            if conn:
                self._pool.putconn(conn)

    def _archive_trade(self, symbol: str, exit_reason: str, realized_pnl: float):
        symbol_state = self.state.get(symbol)
        if not symbol_state:
            return
        active = symbol_state.get("active_position") or {}
        hedge = symbol_state.get("hedge_position") or {}
        conn = None
        try:
            conn = self._pool.getconn()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO trade_history
                (symbol, short_instrument_key, short_strike, short_entry_price,
                 long_instrument_key, long_strike, long_entry_price,
                 quantity, net_credit_received, exit_reason, realized_pnl,
                 trade_date, expiry_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (
                symbol,
                active.get("instrument_key"), active.get("strike"), active.get("entry_price"),
                hedge.get("instrument_key"), hedge.get("strike"), hedge.get("entry_price"),
                active.get("quantity") or hedge.get("quantity"),
                symbol_state.get("net_credit_received", 0.0),
                exit_reason, realized_pnl,
                date.today().isoformat(), active.get("expiry") or hedge.get("expiry")
            ))
            conn.commit()
        except psycopg2.Error as e:
            logger.error(f"Error archiving trade for {symbol}: {e}")
        finally:
            if conn:
                self._pool.putconn(conn)

    def _unwind_hedge(self, symbol: str, long_instrument_key: str, quantity: int, long_order_id: str):
        msg = f"Unwinding dangling hedge for {symbol}: selling {quantity} of {long_instrument_key}"
        logger.warning(msg)
        self.notifier.send_notification(title="Unwinding Hedge", message=msg, level="WARNING")
        unwind_order_id = self.client.place_order_by_key(
            instrument_key=long_instrument_key, side="SELL", quantity=quantity, price=0.0
        )
        if not unwind_order_id:
            fail_msg = f"CRITICAL: Failed to unwind hedge for {symbol}. Long order {long_order_id} remains open. Manual intervention required."
            logger.critical(fail_msg)
            self.notifier.send_notification(title="CRITICAL: Unwind Failed", message=fail_msg, level="ERROR")
            return
        for _ in range(3):
            time.sleep(5)
            status = self.client.get_order_status(unwind_order_id)
            if status == "complete":
                ok_msg = f"Hedge unwound successfully for {symbol}. Unwind order: {unwind_order_id}"
                logger.info(ok_msg)
                self.notifier.send_notification(title="Hedge Unwound", message=ok_msg, level="INFO")
                return
        fail_msg = f"CRITICAL: Hedge unwind order {unwind_order_id} did not fill for {symbol}. Manual intervention required."
        logger.critical(fail_msg)
        self.notifier.send_notification(title="CRITICAL: Unwind Timeout", message=fail_msg, level="ERROR")

    def reconcile_positions(self):
        """Compares DB state against broker positions on startup. Alerts on mismatches."""
        if self.client.is_paper_trade:
            logger.info("Paper trade mode — skipping broker position reconciliation.")
            return

        self.state = self._load_state()
        broker_positions = self.client.get_positions()
        broker_keys = {p["instrument_token"] for p in broker_positions if p["quantity"] != 0}

        for symbol, data in self.state.items():
            if data.get("current_stage") not in ("STAGE_1_CSP", "STAGE_2_CC"):
                continue

            active = data.get("active_position") or {}
            hedge = data.get("hedge_position") or {}
            expected_keys = set()
            if active.get("instrument_key"):
                expected_keys.add(active["instrument_key"])
            if hedge.get("instrument_key"):
                expected_keys.add(hedge["instrument_key"])

            missing = expected_keys - broker_keys
            if missing:
                msg = f"RECONCILIATION MISMATCH for {symbol}: DB expects positions {missing} but broker has no matching open positions. Manual review required."
                logger.critical(msg)
                self.notifier.send_notification(title="Position Mismatch", message=msg, level="ERROR")

        orphan_keys = broker_keys - {
            k
            for data in self.state.values()
            for pos in (data.get("active_position") or {}, data.get("hedge_position") or {})
            if (k := pos.get("instrument_key"))
        }
        if orphan_keys:
            msg = f"RECONCILIATION: Broker has open positions {orphan_keys} not tracked in DB. These may be dangling from a crash."
            logger.warning(msg)
            self.notifier.send_notification(title="Orphan Positions", message=msg, level="WARNING")

    def ensure_symbol_state(self, symbol: str):
        """
        Ensures that a symbol has the default state initialized.
        If it doesn't exist in the state, initializes it.
        """
        if symbol not in self.state:
            logger.info(f"Initializing state for new symbol: {symbol}")
            self.state[symbol] = {
                "current_stage": "IDLE",
                "active_position": None,
                "hedge_position": None,
                "net_credit_received": 0.0,
                "realized_pnl": 0.0
            }
            self._save_state(symbol)

    def _select_target_call(self, chain_df: pl.DataFrame, spot_price: float, cost_basis: float, min_days: int = 10, max_days: int = 42) -> dict | None:
        if chain_df.is_empty():
            return None

        today = date.today()

        df = chain_df.filter(pl.col("type") == "CE")

        if df.is_empty():
            return None

        df = df.with_columns([
            pl.col("expiry").str.strptime(pl.Date, "%Y-%m-%d", strict=False).alias("parsed_expiry")
        ])

        df = df.filter(pl.col("parsed_expiry").is_not_null())

        if df.is_empty():
            return None

        df = df.with_columns([
            (pl.col("parsed_expiry") - today).dt.total_days().alias("dte")
        ])

        df = df.filter((pl.col("dte") >= min_days) & (pl.col("dte") <= max_days))

        if df.is_empty():
            return None

        # CRITICAL: strictly filter strike >= cost_basis
        df = df.filter(pl.col("strike") >= cost_basis)

        if df.is_empty():
            return None

        current_vix = self.client.get_india_vix()
        if current_vix is None:
            current_vix = 15.0

        if current_vix < 13.0:
            otm_pct = 0.06
        elif 13.0 <= current_vix <= 18.0:
            otm_pct = 0.10
        else:
            otm_pct = 0.15

        target_strike = max(spot_price * (1 + otm_pct), cost_basis)

        # Filter to ensure strikes are strictly greater than or equal to target_strike
        df = df.filter(pl.col("strike") >= target_strike)

        if df.is_empty():
            return None

        df = df.with_columns([
            (pl.col("strike") - target_strike).abs().alias("strike_diff")
        ])

        df = df.sort("strike_diff")

        if df.is_empty():
            return None

        return df.row(0, named=True)

    @staticmethod
    def _approx_put_delta(spot: float, strike: float, vix: float, dte: int) -> float:
        """Black–Scholes put delta (r=0) using India VIX as σ proxy. Returns value in [-1, 0]."""
        T = max(dte, 1) / 365.0
        sigma = max(float(vix), 1.0) / 100.0
        if spot <= 0 or strike <= 0:
            return -0.5
        d1 = (math.log(spot / strike) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
        cdf = 0.5 * (1.0 + math.erf(d1 / math.sqrt(2.0)))
        return cdf - 1.0

    @staticmethod
    def _leg_liquid(row: dict, max_spread_pct: float) -> bool:
        bid = row.get("bid")
        ask = row.get("ask")
        if bid is None or bid == 0:
            return False
        if ask is None:
            return False
        spread_pct = (ask - bid) / bid
        return spread_pct <= max_spread_pct

    def _select_target_put(
        self,
        chain_df: pl.DataFrame,
        spot_price: float,
        min_days: int | None = None,
        max_days: int | None = None,
        otm_pct: float | None = None,
        vix: float | None = None,
        lot_size: int = 25,
    ) -> tuple[dict | None, dict | None]:
        """Select short/long put by target-delta + min credit/width with liquidity guards.

        Hedge width from settings; aborts if width × lot_size exceeds MAX_CAPITAL.
        """
        if chain_df.is_empty():
            return None, None

        min_days = settings.ENTRY_MIN_DTE if min_days is None else min_days
        max_days = settings.ENTRY_MAX_DTE if max_days is None else max_days
        hedge_width = settings.HEDGE_WIDTH
        max_spread = settings.MAX_BID_ASK_SPREAD_PCT
        target_delta = settings.SHORT_PUT_TARGET_DELTA
        min_cw = settings.MIN_CREDIT_WIDTH_RATIO

        if hedge_width * lot_size > MAX_CAPITAL:
            logger.error(
                f"Hedge width {hedge_width} × lot {lot_size} = {hedge_width * lot_size:.0f} "
                f"exceeds MAX_CAPITAL {MAX_CAPITAL:.0f}. Aborting strike selection."
            )
            return None, None

        if otm_pct is None:
            otm_pct = settings.SHORT_PUT_BASE_OTM_PCT
        if vix is None:
            vix = 15.0

        today = date.today()
        df = chain_df.filter(pl.col("type") == "PE")
        if df.is_empty():
            return None, None

        df = df.with_columns([
            pl.col("expiry").str.strptime(pl.Date, "%Y-%m-%d", strict=False).alias("parsed_expiry")
        ])
        df = df.filter(pl.col("parsed_expiry").is_not_null())
        if df.is_empty():
            return None, None

        df = df.with_columns([
            (pl.col("parsed_expiry") - today).dt.total_days().alias("dte")
        ])
        df = df.filter((pl.col("dte") >= min_days) & (pl.col("dte") <= max_days))
        if df.is_empty():
            return None, None

        # OTM ceiling from regime; allow a band below for delta/credit search
        otm_ceiling = spot_price * (1.0 - otm_pct)
        otm_floor = spot_price * (1.0 - max(otm_pct * 2.5, otm_pct + 0.02))
        short_candidates = df.filter(
            (pl.col("strike") <= otm_ceiling) & (pl.col("strike") >= otm_floor)
        )
        if short_candidates.is_empty():
            short_candidates = df.filter(pl.col("strike") <= otm_ceiling)
        if short_candidates.is_empty():
            return None, None

        best: tuple[float, dict, dict] | None = None  # (score, short, long)

        for short_put_row in short_candidates.iter_rows(named=True):
            if not self._leg_liquid(short_put_row, max_spread):
                continue

            short_strike = short_put_row["strike"]
            short_expiry = short_put_row["expiry"]
            dte = int(short_put_row.get("dte") or min_days)
            hedge_target = short_strike - hedge_width

            hedge_df = df.filter(pl.col("expiry") == short_expiry)
            hedge_df = hedge_df.filter(pl.col("strike") <= hedge_target)
            if hedge_df.is_empty():
                continue
            hedge_df = hedge_df.with_columns(
                (pl.col("strike") - hedge_target).abs().alias("hedge_strike_diff")
            ).sort("hedge_strike_diff")
            long_put_row = hedge_df.row(0, named=True)

            if not self._leg_liquid(long_put_row, max_spread):
                continue

            width = short_strike - long_put_row["strike"]
            if width <= 0:
                continue
            if width * lot_size > MAX_CAPITAL:
                continue

            credit = float(short_put_row["bid"]) - float(long_put_row["ask"])
            if credit <= 0:
                continue
            cw_ratio = credit / width
            if cw_ratio < min_cw:
                continue

            delta = abs(self._approx_put_delta(spot_price, short_strike, vix, dte))
            # Lower is better: prefer near target delta, then higher credit/width
            score = abs(delta - target_delta) - 0.05 * cw_ratio
            if best is None or score < best[0]:
                best = (score, short_put_row, long_put_row)

        if best is None:
            logger.warning(
                "No liquid short/long put pair met delta/credit-width guards "
                f"(otm={otm_pct:.3f}, min_cw={min_cw}, width={hedge_width})."
            )
            return None, None

        return best[1], best[2]

    def _place_entry_leg_with_requote(
        self,
        instrument_key: str,
        side: str,
        quantity: int,
        start_price: float,
        market_price: float,
        symbol: str,
    ) -> tuple[str | None, float | None]:
        """Place a limit entry with limited requotes toward the marketable price.

        BUY walks start→ask; SELL walks start→bid. Returns (order_id, fill_price).
        """
        attempts = max(1, 1 + settings.ENTRY_REQUOTE_ATTEMPTS)
        step = settings.ENTRY_REQUOTE_STEP_PCT
        price = float(start_price)

        for attempt in range(attempts):
            if attempt > 0:
                price = round(price + (market_price - price) * step, 2)
                if side == "BUY":
                    price = min(price, float(market_price))
                else:
                    price = max(price, float(market_price))

            order_id = self.client.place_order_by_key(
                instrument_key=instrument_key, side=side, quantity=quantity, price=price
            )
            if not order_id:
                return None, None

            filled = False
            terminal_fail = False
            for _ in range(3):
                time.sleep(5)
                status = self.client.get_order_status(order_id)
                if status == "complete":
                    filled = True
                    break
                if status in ("rejected", "cancelled"):
                    terminal_fail = True
                    msg = f"{side} order {order_id} was {status} for {symbol} (attempt {attempt + 1}/{attempts})."
                    logger.warning(msg)
                    if attempt + 1 >= attempts:
                        self.notifier.send_notification(
                            title=f"Order {status.capitalize()}", message=msg, level="WARNING"
                        )
                        return None, None
                    break

            if filled:
                fill = self.client.get_order_fill_price(order_id)
                return order_id, fill if fill is not None else price

            if not terminal_fail:
                self.client.cancel_order(order_id)
                if attempt + 1 >= attempts:
                    msg = f"{side} order {order_id} timed out for {symbol}. Cancelled after {attempts} attempt(s)."
                    logger.warning(msg)
                    self.notifier.send_notification(title="Order Timeout", message=msg, level="WARNING")
                    return None, None
                logger.info(f"Requoting {side} for {symbol} toward market (attempt {attempt + 2}/{attempts}).")

        return None, None

    def _iso_week_key(self, on: date | None = None) -> str:
        d = on or date.today()
        iso = d.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"

    def _reentry_redis_key(self, symbol: str, week: str | None = None) -> str:
        return f"pcs:reentry_used:{symbol}:{week or self._iso_week_key()}"

    def _same_week_reentry_allowed(self, symbol: str) -> bool:
        """Allow at most one same-week re-entry after Take Profit."""
        if not settings.ALLOW_SAME_WEEK_REENTRY:
            return False
        data = self.state.get(symbol) or {}
        if data.get("current_stage") not in ("IDLE", "CLOSED"):
            return False
        week = self._iso_week_key()
        try:
            r = get_redis_client()
            if r.get(self._reentry_redis_key(symbol, week)):
                return False
            tp_ready = r.get(f"pcs:tp_ready:{symbol}:{week}")
            if tp_ready:
                return True
        except Exception as e:
            logger.warning(f"Redis re-entry check failed ({e}); falling back to in-memory.")
        return data.get("last_exit_reason") == "Take Profit"

    def _mark_tp_ready_for_reentry(self, symbol: str) -> None:
        try:
            r = get_redis_client()
            week = self._iso_week_key()
            r.set(f"pcs:tp_ready:{symbol}:{week}", "1", ex=10 * 24 * 3600)
        except Exception as e:
            logger.warning(f"Could not mark TP re-entry ready for {symbol}: {e}")

    def _consume_same_week_reentry(self, symbol: str) -> None:
        try:
            r = get_redis_client()
            week = self._iso_week_key()
            r.set(self._reentry_redis_key(symbol, week), "1", ex=10 * 24 * 3600)
            r.delete(f"pcs:tp_ready:{symbol}:{week}")
        except Exception as e:
            logger.warning(f"Could not persist re-entry consumption for {symbol}: {e}")

    def try_same_week_reentry(self) -> None:
        """After exits, attempt one same-week re-entry when IDLE after Take Profit (PROF-019)."""
        if not settings.ALLOW_SAME_WEEK_REENTRY:
            return
        now = datetime.now(IST)
        # Re-entry window Mon–Thu (and Friday morning before weekly entry)
        if now.weekday() > 4:
            return
        self.state = self._load_state()
        for symbol, data in self.state.items():
            if data.get("current_stage") not in ("IDLE", "CLOSED"):
                continue
            if data.get("last_exit_reason") != "Take Profit":
                continue
            if not self._same_week_reentry_allowed(symbol):
                continue
            logger.info(f"Attempting same-week re-entry for {symbol} after Take Profit.")
            self.execute_daily_cycle(
                symbol=symbol,
                quantity_shares=LOT_SIZES.get(symbol, 25),
                symbol_config={"allocation_pct": 1.0, "entry_session": "midweek", "same_week_reentry": True},
            )

    def execute_daily_cycle(self, symbol: str, quantity_shares: int, symbol_config: dict):
        # Reload state from DB before proceeding
        self.state = self._load_state()
        self.ensure_symbol_state(symbol)

        # Acquire PostgreSQL advisory lock to prevent concurrent execution for this symbol
        lock_conn = None
        try:
            lock_conn = self._pool.getconn()
            lock_cursor = lock_conn.cursor()
            lock_cursor.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (symbol,))
            acquired = lock_cursor.fetchone()[0]
            if not acquired:
                logger.warning(f"Could not acquire advisory lock for {symbol} — another process is already executing. Skipping.")
                self._pool.putconn(lock_conn)
                lock_conn = None
                return

            current_stage = self.state[symbol].get("current_stage", "IDLE")

            if current_stage in ("IDLE", "CLOSED"):
                logger.info(f"Executing daily cycle for {symbol} in IDLE state.")

                now_ist = datetime.now(IST)
                is_reentry = bool(symbol_config.get("same_week_reentry"))
                if is_reentry and not self._same_week_reentry_allowed(symbol):
                    logger.info(f"Same-week re-entry blocked for {symbol}.")
                    return

                current_vix = self.client.get_india_vix()
                regime_action, otm_pct = vix_regime_otm(current_vix)
                if regime_action == "skip":
                    thr = settings.VIX_MAX_THRESHOLD
                    msg = (
                        f"VIX circuit breaker triggered: VIX={current_vix:.1f} exceeds "
                        f"threshold {thr}. Skipping entry for {symbol}."
                    )
                    logger.warning(msg)
                    self.notifier.send_notification(title="VIX Circuit Breaker", message=msg, level="WARNING")
                    return

                # PROF-016 IVR gate
                ivr_ok, ivr, ivr_reason = ivr_allows_entry(
                    current_vix,
                    lookback_days=settings.IVR_LOOKBACK_DAYS,
                    min_percentile=settings.IVR_MIN_PERCENTILE,
                    skip_low_ivr=settings.SKIP_LOW_IVR,
                )
                if not ivr_ok:
                    msg = f"IVR entry skip for {symbol}: {ivr_reason}"
                    logger.info(msg)
                    self.notifier.send_notification(title="IVR Entry Skip", message=msg, level="INFO")
                    return
                if ivr is not None:
                    logger.info(f"IVR gate passed for {symbol}: {ivr_reason}")

                # PROF-018 event blackout
                if settings.EVENT_BLACKOUT_ENABLED:
                    blocked, ev = in_event_blackout(
                        now_ist.date(),
                        days_before=settings.EVENT_BLACKOUT_DAYS_BEFORE,
                        days_after=settings.EVENT_BLACKOUT_DAYS_AFTER,
                    )
                    if blocked:
                        msg = f"Event blackout skip for {symbol}: near event {ev}"
                        logger.info(msg)
                        self.notifier.send_notification(title="Event Blackout", message=msg, level="INFO")
                        return

                is_friday = now_ist.weekday() == 4
                entry_session = symbol_config.get("entry_session", "any")
                midweek_map = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4}
                midweek_days = {
                    midweek_map[d.strip().lower()]
                    for d in settings.MIDWEEK_ENTRY_DAYS.split(",")
                    if d.strip().lower() in midweek_map
                }
                is_midweek_day = now_ist.weekday() in midweek_days and not is_friday

                if entry_session == "friday":
                    if not is_friday:
                        # Explicit Friday session invoked off-Friday (tests / manual) — allow proceed
                        pass
                elif entry_session == "midweek" or (entry_session == "any" and is_midweek_day):
                    if not settings.ALLOW_MIDWEEK_ENTRY:
                        logger.info(f"Mid-week entry blocked for {symbol} (ALLOW_MIDWEEK_ENTRY=False).")
                        return
                    if current_vix is None or not (
                        settings.MIDWEEK_VIX_MIN <= current_vix <= settings.MIDWEEK_VIX_MAX
                    ):
                        msg = (
                            f"Mid-week entry skipped for {symbol}: VIX={current_vix} outside "
                            f"[{settings.MIDWEEK_VIX_MIN}, {settings.MIDWEEK_VIX_MAX}]."
                        )
                        logger.info(msg)
                        return
                    logger.info(
                        f"Mid-week entry allowed for {symbol}: VIX={current_vix:.1f}, OTM={otm_pct:.3f}"
                    )
                elif entry_session == "any" and not is_friday and not is_midweek_day:
                    logger.info(
                        f"Skipping entry for {symbol}: today is not Friday/mid-week session day."
                    )
                    return

                spot_price = self.client.get_market_quote_ltp(symbol)
                if spot_price is None:
                    msg = f"Failed to fetch LTP for {symbol}. Aborting daily cycle."
                    logger.warning(msg)
                    self.notifier.send_notification(title="LTP Fetch Failed", message=msg, level="WARNING")
                    return

                # PROF-018 trend filter
                trend_ok, sma_val, trend_reason = trend_allows_entry(
                    spot_price,
                    sma_days=settings.TREND_SMA_DAYS,
                    enabled=settings.TREND_FILTER_ENABLED,
                )
                if not trend_ok:
                    msg = f"Trend filter skip for {symbol}: {trend_reason}"
                    logger.info(msg)
                    self.notifier.send_notification(title="Trend Filter Skip", message=msg, level="INFO")
                    return

                chain_df = self.client.get_option_chain(symbol)
                lot_size = LOT_SIZES.get(symbol, 25)

                targets = self._select_target_put(
                    chain_df, spot_price, otm_pct=otm_pct, vix=current_vix or 15.0, lot_size=lot_size
                )
                if targets is None or targets[0] is None or targets[1] is None:
                    logger.warning(f"Could not find a suitable target PUT spread for {symbol}. Aborting daily cycle.")
                    return

                short_put, long_put = targets

                short_instrument_key = short_put.get("instrument_key")
                short_strike = short_put.get("strike")
                short_expiry = short_put.get("expiry")
                long_instrument_key = long_put.get("instrument_key")
                long_strike = long_put.get("strike")
                long_expiry = long_put.get("expiry")

                short_bid, short_ask = short_put.get("bid"), short_put.get("ask")
                long_bid, long_ask = long_put.get("bid"), long_put.get("ask")
                if short_bid in (None, 0, 0.0) or long_ask in (None, 0, 0.0):
                    msg = f"Target puts have missing liquidity (Bid/Ask = 0) for {symbol}. Aborting."
                    logger.warning(msg)
                    self.notifier.send_notification(title="Missing Liquidity", message=msg, level="WARNING")
                    return

                # Theoretical credit at natural bid/ask vs mid (PROF-012)
                theoretical_natural = float(short_bid) - float(long_ask)
                short_mid = (float(short_bid) + float(short_ask)) / 2.0 if short_ask else float(short_bid)
                long_mid = (float(long_bid) + float(long_ask)) / 2.0 if long_bid else float(long_ask)
                theoretical_mid = short_mid - long_mid

                if settings.ENTRY_USE_MID_PRICE:
                    short_entry_price = round(short_mid, 2)
                    long_entry_price = round(long_mid, 2)
                else:
                    short_entry_price = float(short_bid)
                    long_entry_price = float(long_ask)

                logger.info(
                    f"Targets selected for {symbol}: Short {short_strike} PE / Long {long_strike} PE "
                    f"exp {short_expiry}; mid credit {theoretical_mid:.2f}, natural {theoretical_natural:.2f}"
                )

                allocation_pct = symbol_config.get("allocation_pct", ALLOCATION_PCT_PER_TRADE)
                available_margin = self.client.get_available_margin()
                if available_margin is None or available_margin <= 0:
                    msg = f"Could not fetch available margin for {symbol}. Aborting."
                    logger.error(msg)
                    self.notifier.send_notification(title="Margin Fetch Failed", message=msg, level="ERROR")
                    return
                budget = available_margin * allocation_pct

                required_capital_per_lot = (short_strike - long_strike) * lot_size
                if required_capital_per_lot <= 0:
                    logger.error(f"Invalid required capital per lot ({required_capital_per_lot}) for {symbol}. Short strike: {short_strike}, Long strike: {long_strike}. Aborting.")
                    return
                if required_capital_per_lot > MAX_CAPITAL:
                    msg = (
                        f"Required capital per lot {required_capital_per_lot:.0f} exceeds "
                        f"MAX_CAPITAL {MAX_CAPITAL:.0f} for {symbol}. Aborting."
                    )
                    logger.error(msg)
                    self.notifier.send_notification(title="Capital Ceiling", message=msg, level="ERROR")
                    return

                num_lots = math.floor(budget / required_capital_per_lot)

                if num_lots == 0:
                    msg = f"CRITICAL: Insufficient funds to trade {symbol}. Budget: {budget:.2f} (margin={available_margin:.2f} x {allocation_pct:.0%}), Required for 1 lot: {required_capital_per_lot}. Aborting."
                    logger.critical(msg)
                    self.notifier.send_notification(title="Insufficient Funds", message=msg, level="ERROR")
                    return

                final_quantity = num_lots * lot_size

                # Leg 1: BUY hedge first (never naked short), with optional mid→ask requotes
                long_order_id, long_fill_price = self._place_entry_leg_with_requote(
                    instrument_key=long_instrument_key,
                    side="BUY",
                    quantity=final_quantity,
                    start_price=long_entry_price,
                    market_price=float(long_ask),
                    symbol=symbol,
                )
                if not long_order_id:
                    logger.error(f"Failed to place BUY hedge order for {symbol}.")
                    return

                # Leg 2: SELL short only after hedge fill
                short_order_id, short_fill_price = self._place_entry_leg_with_requote(
                    instrument_key=short_instrument_key,
                    side="SELL",
                    quantity=final_quantity,
                    start_price=short_entry_price,
                    market_price=float(short_bid),
                    symbol=symbol,
                )
                if not short_order_id:
                    msg = f"CRITICAL: Failed to place SELL short order for {symbol} after filling hedge. Attempting automated unwind."
                    logger.critical(msg)
                    self.notifier.send_notification(title="CRITICAL: Short Order Failed", message=msg, level="ERROR")
                    self._unwind_hedge(symbol, long_instrument_key, final_quantity, long_order_id)
                    return

                achieved_short = short_fill_price if short_fill_price is not None else short_entry_price
                achieved_long = long_fill_price if long_fill_price is not None else long_entry_price
                achieved_credit_per = achieved_short - achieved_long

                if self.client.is_paper_trade:
                    logger.info(
                        f"PAPER fill quality {symbol}: theoretical_mid={theoretical_mid:.2f}, "
                        f"theoretical_natural={theoretical_natural:.2f}, "
                        f"achieved={achieved_credit_per:.2f}"
                    )

                msg = (
                    f"Credit Spread placed successfully for {symbol}. STAGE_1_CSP entry: "
                    f"Short {short_strike} PE / Long {long_strike} PE expiring on {short_expiry}."
                )
                logger.info(msg)
                self.notifier.send_notification(title="Order Placed", message=msg, level="INFO")

                self.state[symbol]["current_stage"] = "STAGE_1_CSP"
                if is_reentry:
                    self._consume_same_week_reentry(symbol)
                self.state[symbol]["last_exit_reason"] = None
                self.state[symbol]["active_position"] = {
                    "strike": short_strike,
                    "expiry": short_expiry,
                    "instrument_key": short_instrument_key,
                    "entry_price": achieved_short,
                    "order_id": short_order_id,
                    "quantity": final_quantity
                }
                self.state[symbol]["hedge_position"] = {
                    "strike": long_strike,
                    "expiry": long_expiry,
                    "instrument_key": long_instrument_key,
                    "entry_price": achieved_long,
                    "order_id": long_order_id,
                    "quantity": final_quantity
                }
                self.state[symbol]["net_credit_received"] = achieved_credit_per * final_quantity
                self._save_state(symbol)
        finally:
            if lock_conn:
                try:
                    lock_cursor = lock_conn.cursor()
                    lock_cursor.execute("SELECT pg_advisory_unlock(hashtext(%s))", (symbol,))
                    lock_conn.commit()
                except psycopg2.Error as e:
                    logger.error(f"Error releasing advisory lock for {symbol}: {e}")
                finally:
                    self._pool.putconn(lock_conn)

    def active_instrument_keys(self) -> set[str]:
        """Returns all instrument keys that should be monitored in real-time."""
        keys: set[str] = set()
        for symbol, data in self.state.items():
            if data.get("current_stage") not in ("STAGE_1_CSP", "STAGE_2_CC"):
                continue
            active = data.get("active_position") or {}
            hedge = data.get("hedge_position") or {}
            if active.get("instrument_key"):
                keys.add(active["instrument_key"])
            if hedge.get("instrument_key"):
                keys.add(hedge["instrument_key"])
            if symbol in self.INDEX_INSTRUMENT_KEYS:
                keys.add(self.INDEX_INSTRUMENT_KEYS[symbol])
        return keys

    def refresh_exit_thresholds(self):
        """Populate/refresh the in-memory exit threshold cache from current state."""
        thresholds: dict[str, dict] = {}
        for symbol, data in self.state.items():
            if data.get("current_stage") not in ("STAGE_1_CSP",):
                continue
            active = data.get("active_position")
            hedge = data.get("hedge_position")
            if not active or not hedge:
                continue
            short_entry = active.get("entry_price", 0.0)
            long_entry = hedge.get("entry_price", 0.0)
            initial_credit = short_entry - long_entry
            thresholds[symbol] = {
                "short_strike": active.get("strike"),
                "short_instrument_key": active.get("instrument_key"),
                "long_instrument_key": hedge.get("instrument_key"),
                "quantity": active.get("quantity", LOT_SIZES.get(symbol, 25)),
                "initial_credit": initial_credit,
                "expiry": active.get("expiry"),
                "underlying_key": self.INDEX_INSTRUMENT_KEYS.get(symbol),
            }
        self._exit_thresholds = thresholds

    def on_realtime_tick(self, instrument_key: str, ltp: float):
        """Handle a real-time LTP tick. Debounces breach detection."""
        matched_symbol = None
        for symbol, t in self._exit_thresholds.items():
            if t.get("underlying_key") == instrument_key:
                matched_symbol = symbol
                break
        if matched_symbol is None:
            return

        if matched_symbol in self._exit_in_progress:
            return

        t = self._exit_thresholds[matched_symbol]
        short_strike = t["short_strike"]

        if ltp > short_strike:
            self._breach_first_seen.pop(matched_symbol, None)
            return

        now = time.monotonic()
        first_seen = self._breach_first_seen.get(matched_symbol)
        if first_seen is None:
            self._breach_first_seen[matched_symbol] = now
            logger.info(f"Real-time breach detected for {matched_symbol}: spot {ltp} <= strike {short_strike}. Debouncing...")
            return

        if (now - first_seen) < self.DEBOUNCE_SECONDS:
            return

        self._breach_first_seen.pop(matched_symbol, None)

        with self._exit_lock:
            if matched_symbol in self._exit_in_progress:
                return
            self._exit_in_progress.add(matched_symbol)

        logger.warning(f"Real-time exit triggered for {matched_symbol}: spot {ltp} <= strike {short_strike} (confirmed after {self.DEBOUNCE_SECONDS}s debounce)")

        try:
            self.state = self._load_state()
            data = self.state.get(matched_symbol, {})
            if data.get("current_stage") != "STAGE_1_CSP":
                return

            chain_df = self.client.get_option_chain(matched_symbol, expiry_date=t["expiry"])
            short_df = chain_df.filter(pl.col("instrument_key") == t["short_instrument_key"])
            long_df = chain_df.filter(pl.col("instrument_key") == t["long_instrument_key"])

            if short_df.is_empty() or long_df.is_empty():
                logger.error(f"Cannot fetch live quotes for {matched_symbol} exit. Will retry next tick.")
                return

            short_live_ask = short_df.row(0, named=True).get("ask")
            long_live_bid = long_df.row(0, named=True).get("bid")
            if short_live_ask is None or long_live_bid is None:
                return

            self.notifier.send_notification(
                title="Real-Time Stop Loss",
                message=f"Spot {ltp} breached short strike {short_strike} for {matched_symbol}. Executing exit.",
                level="WARNING"
            )

            self._execute_exit(matched_symbol, "Stop Loss (Real-Time)", {
                "short_instrument_key": t["short_instrument_key"],
                "long_instrument_key": t["long_instrument_key"],
                "quantity": t["quantity"],
                "short_live_ask": short_live_ask,
                "long_live_bid": long_live_bid,
                "initial_credit": t["initial_credit"],
                "current_cost_to_close": short_live_ask - long_live_bid,
            })
        finally:
            self._exit_in_progress.discard(matched_symbol)

    def _execute_exit(self, symbol: str, reason: str, snapshot: dict):
        """Execute a sequenced exit: buy-to-close short FIRST, then sell-to-close hedge.

        Mirrors the hedge-first entry order to prevent a naked-short window.
        If BTC fails, the intact spread is left untouched (safe to retry).
        If BTC fills but STC fails, the short is covered (benign long remains).
        """
        short_instrument_key = snapshot["short_instrument_key"]
        long_instrument_key = snapshot["long_instrument_key"]
        quantity = snapshot["quantity"]
        short_live_ask = snapshot["short_live_ask"]
        long_live_bid = snapshot["long_live_bid"]
        initial_credit = snapshot["initial_credit"]
        theoretical_cost = snapshot["current_cost_to_close"]

        # --- Leg 1: Buy-to-close the short (cover the dangerous leg first) ---
        btc_price = round(short_live_ask * (1 + EXIT_SLIPPAGE_BUFFER_PCT), 2)
        btc_order_id = self.client.place_order_by_key(
            instrument_key=short_instrument_key,
            side="BUY",
            quantity=quantity,
            price=btc_price,
            order_type="LIMIT"
        )

        if not btc_order_id:
            msg = f"Failed to place BTC order for {symbol}. Spread intact — will retry next cycle."
            logger.error(msg)
            self.notifier.send_notification(title="BTC Order Failed", message=msg, level="ERROR")
            return

        btc_filled = False
        for _ in range(3):
            time.sleep(2)
            btc_status = self.client.get_order_status(btc_order_id)
            if btc_status == "complete":
                btc_filled = True
                break
            elif btc_status in ("rejected", "cancelled"):
                msg = f"BTC order {btc_order_id} was {btc_status} for {symbol}. Spread intact — will retry next cycle."
                logger.error(msg)
                self.notifier.send_notification(title=f"BTC {btc_status.capitalize()}", message=msg, level="ERROR")
                return

        if not btc_filled:
            self.client.cancel_order(btc_order_id)
            msg = f"BTC order {btc_order_id} timed out for {symbol}. Cancelled. Spread intact — will retry next cycle."
            logger.error(msg)
            self.notifier.send_notification(title="BTC Timeout", message=msg, level="ERROR")
            return

        # --- Leg 2: Sell-to-close the hedge (short is now covered) ---
        stc_price = round(long_live_bid * (1 - EXIT_SLIPPAGE_BUFFER_PCT), 2)
        stc_order_id = self.client.place_order_by_key(
            instrument_key=long_instrument_key,
            side="SELL",
            quantity=quantity,
            price=stc_price,
            order_type="LIMIT"
        )

        stc_filled = False
        if stc_order_id:
            for _ in range(3):
                time.sleep(2)
                stc_status = self.client.get_order_status(stc_order_id)
                if stc_status == "complete":
                    stc_filled = True
                    break

        # --- Compute P&L from real fills when available ---
        btc_fill = self.client.get_order_fill_price(btc_order_id)
        stc_fill = self.client.get_order_fill_price(stc_order_id) if stc_order_id and stc_filled else None

        if btc_fill is not None and stc_fill is not None:
            actual_cost_to_close = btc_fill - stc_fill
        else:
            actual_cost_to_close = theoretical_cost

        pnl = (initial_credit - actual_cost_to_close) * quantity

        # Archive and close — the short is covered regardless of STC outcome
        self._archive_trade(symbol, reason, pnl)
        self.state[symbol]["realized_pnl"] += pnl
        self.state[symbol]["current_stage"] = "CLOSED"
        self.state[symbol]["last_exit_reason"] = reason
        self.state[symbol]["active_position"] = None
        self.state[symbol]["hedge_position"] = None
        self._save_state(symbol)
        if reason == "Take Profit":
            self._mark_tp_ready_for_reentry(symbol)

        if not stc_order_id or not stc_filled:
            residual_msg = f"Exit for {symbol}: short covered (BTC filled), but residual hedge {long_instrument_key} not closed. Manual close required."
            logger.warning(residual_msg)
            self.notifier.send_notification(title="Residual Hedge", message=residual_msg, level="WARNING")

        success_msg = f"Exit completed for {symbol} due to {reason}. P&L: {pnl:.2f}. State updated to CLOSED."
        logger.info(success_msg)
        self.notifier.send_notification(title="Exit Complete", message=success_msg, level="INFO")

    def check_exits(self):
        """Evaluate active positions for Take Profit, Stop Loss, and Time Stop conditions."""
        self.state = self._load_state()
        active_symbols = [s for s, d in self.state.items() if d.get("current_stage") == "STAGE_1_CSP"]
        if not active_symbols:
            logger.info("No active STAGE_1_CSP positions to evaluate.")
            return
        logger.info(f"Evaluating exits for {len(active_symbols)} active position(s): {active_symbols}")
        for symbol, data in self.state.items():
            if data.get("current_stage") != "STAGE_1_CSP":
                continue

            active_position = data.get("active_position")
            hedge_position = data.get("hedge_position")

            if not active_position or not hedge_position:
                continue

            expiry_str = active_position.get("expiry")
            if expiry_str:
                try:
                    expiry_date = datetime.strptime(str(expiry_str), "%Y-%m-%d").date()
                except (ValueError, TypeError):
                    expiry_date = None
                if expiry_date and date.today() > expiry_date:
                    short_entry_price = active_position.get("entry_price", 0.0)
                    long_entry_price = hedge_position.get("entry_price", 0.0)
                    initial_credit = short_entry_price - long_entry_price
                    quantity_shares = active_position.get("quantity", LOT_SIZES.get(symbol, 25))
                    pnl = initial_credit * quantity_shares
                    msg = f"Position for {symbol} expired on {expiry_date} while bot was offline. Assuming options expired worthless (max profit). P&L: {pnl:.2f}"
                    logger.warning(msg)
                    self.notifier.send_notification(title="Expired Position Auto-Closed", message=msg, level="WARNING")
                    self._archive_trade(symbol, "Expiry (offline)", pnl)
                    self.state[symbol]["realized_pnl"] = data.get("realized_pnl", 0.0) + pnl
                    self.state[symbol]["current_stage"] = "CLOSED"
                    self.state[symbol]["active_position"] = None
                    self.state[symbol]["hedge_position"] = None
                    self._save_state(symbol)
                    continue

            spot_price = self.client.get_market_quote_ltp(symbol)
            if spot_price is None:
                continue

            short_entry_price = active_position.get("entry_price", 0.0)
            long_entry_price = hedge_position.get("entry_price", 0.0)
            initial_credit = short_entry_price - long_entry_price

            short_instrument_key = active_position.get("instrument_key")
            long_instrument_key = hedge_position.get("instrument_key")
            expiry_str = active_position.get("expiry")
            quantity_shares = active_position.get("quantity", LOT_SIZES.get(symbol, 25))

            chain_df = self.client.get_option_chain(symbol, expiry_date=expiry_str)
            short_contract_df = chain_df.filter(pl.col("instrument_key") == short_instrument_key)
            long_contract_df = chain_df.filter(pl.col("instrument_key") == long_instrument_key)

            if short_contract_df.is_empty() or long_contract_df.is_empty():
                continue

            short_live_ask = short_contract_df.row(0, named=True).get("ask")
            long_live_bid = long_contract_df.row(0, named=True).get("bid")

            if short_live_ask is None or long_live_bid is None:
                continue

            current_cost_to_close = short_live_ask - long_live_bid
            short_strike = active_position.get("strike")

            tp_frac = settings.TP_RESIDUAL_CREDIT_FRACTION
            sl_mult = settings.SL_CREDIT_MULTIPLE
            take_profit = current_cost_to_close <= tp_frac * initial_credit
            stop_loss = current_cost_to_close >= sl_mult * initial_credit or spot_price <= short_strike

            now = datetime.now(IST)
            time_stop = (
                settings.TIME_STOP_WEEKDAY >= 0
                and now.weekday() == settings.TIME_STOP_WEEKDAY
                and now.hour >= settings.TIME_STOP_HOUR
            )

            dte_manage = False
            dte = None
            if settings.DTE_MANAGE_THRESHOLD >= 0 and expiry_str:
                try:
                    exp_d = datetime.strptime(str(expiry_str), "%Y-%m-%d").date()
                    dte = (exp_d - date.today()).days
                    dte_manage = dte <= settings.DTE_MANAGE_THRESHOLD
                except (ValueError, TypeError):
                    dte_manage = False

            delta_manage = False
            if settings.SHORT_DELTA_MANAGE > 0 and dte is not None:
                vix_now = self.client.get_india_vix() or 15.0
                abs_delta = abs(self._approx_put_delta(spot_price, float(short_strike), vix_now, max(dte, 0)))
                delta_manage = abs_delta >= settings.SHORT_DELTA_MANAGE

            if take_profit or stop_loss or time_stop or dte_manage or delta_manage:
                if take_profit:
                    reason = "Take Profit"
                elif stop_loss:
                    reason = "Stop Loss"
                elif delta_manage:
                    reason = "Delta Manage"
                elif dte_manage:
                    reason = "DTE Manage"
                else:
                    reason = "Time Stop"
                msg = f"[{reason}] Exit triggered for {symbol}. Initial Credit: {initial_credit:.2f}, Cost to Close: {current_cost_to_close:.2f}, Spot: {spot_price:.2f}. Initiating closing orders..."
                logger.info(msg)
                self.notifier.send_notification(
                    title=f"{reason} Triggered",
                    message=msg,
                    level="INFO" if take_profit or time_stop or dte_manage or delta_manage else "WARNING",
                )

                self._execute_exit(symbol, reason, {
                    "short_instrument_key": short_instrument_key,
                    "long_instrument_key": long_instrument_key,
                    "quantity": quantity_shares,
                    "short_live_ask": short_live_ask,
                    "long_live_bid": long_live_bid,
                    "initial_credit": initial_credit,
                    "current_cost_to_close": current_cost_to_close,
                })


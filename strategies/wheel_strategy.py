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
from config.settings import LOT_SIZES, VIX_MAX_THRESHOLD, ALLOCATION_PCT_PER_TRADE, EXIT_SLIPPAGE_BUFFER_PCT

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

        self.state = self._load_state()
        self.client = UpstoxClient()
        self.notifier = Notifier()

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

    def _select_target_put(self, chain_df: pl.DataFrame, spot_price: float, min_days: int = 10, max_days: int = 42) -> tuple[dict | None, dict | None]:
        if chain_df.is_empty():
            return None, None

        today = date.today()

        # Parse expiry dates and calculate days to expiry
        # Assuming expiry format is 'YYYY-MM-DD'
        df = chain_df.filter(pl.col("type") == "PE")

        if df.is_empty():
            return None, None

        # Calculate days to expiry
        # Safely parsing the date strings, ignoring invalid ones
        df = df.with_columns([
            pl.col("expiry").str.strptime(pl.Date, "%Y-%m-%d", strict=False).alias("parsed_expiry")
        ])

        # Filter out rows where parsing failed
        df = df.filter(pl.col("parsed_expiry").is_not_null())

        if df.is_empty():
            return None, None

        df = df.with_columns([
            (pl.col("parsed_expiry") - today).dt.total_days().alias("dte")
        ])

        # Filter by DTE
        df = df.filter((pl.col("dte") >= min_days) & (pl.col("dte") <= max_days))

        if df.is_empty():
            return None, None

        otm_pct = 0.01

        target_strike = spot_price * (1 - otm_pct)

        # Filter to ensure strikes are strictly less than or equal to target_strike
        short_df = df.filter(pl.col("strike") <= target_strike)

        if short_df.is_empty():
            return None, None

        # Find closest strike for Short Put
        short_df = short_df.with_columns([
            (pl.col("strike") - target_strike).abs().alias("strike_diff")
        ])

        short_df = short_df.sort("strike_diff")

        if short_df.is_empty():
            return None, None

        short_put_row = short_df.row(0, named=True)

        # Calculate Hedge Width
        short_strike = short_put_row["strike"]
        hedge_target_strike = short_strike - 100
        short_expiry = short_put_row["expiry"]

        # Filter for Long Put (Hedge) with the same expiry
        hedge_df = df.filter(pl.col("expiry") == short_expiry)

        # Strike must be less than or equal to hedge_target_strike
        hedge_df = hedge_df.filter(pl.col("strike") <= hedge_target_strike)

        if hedge_df.is_empty():
            return short_put_row, None

        hedge_df = hedge_df.with_columns([
            (pl.col("strike") - hedge_target_strike).abs().alias("hedge_strike_diff")
        ])

        hedge_df = hedge_df.sort("hedge_strike_diff")

        long_put_row = hedge_df.row(0, named=True)

        # Slippage Guardrails Check
        for leg_name, row in [("Short PE", short_put_row), ("Long PE", long_put_row)]:
            bid = row.get("bid")
            ask = row.get("ask")
            if bid is None or bid == 0:
                logger.warning(f"Bid price is missing or 0 for {leg_name}. Aborting trade to prevent slippage.")
                return None, None

            spread_pct = (ask - bid) / bid
            if spread_pct > 0.15:
                logger.warning(f"Bid-Ask spread too wide ({spread_pct * 100:.1f}%) for {leg_name}. Aborting trade to prevent slippage.")
                return None, None

        return short_put_row, long_put_row

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

                current_vix = self.client.get_india_vix()
                if current_vix is not None and current_vix > VIX_MAX_THRESHOLD:
                    msg = f"VIX circuit breaker triggered: VIX={current_vix:.1f} exceeds threshold {VIX_MAX_THRESHOLD}. Skipping entry for {symbol}."
                    logger.warning(msg)
                    self.notifier.send_notification(title="VIX Circuit Breaker", message=msg, level="WARNING")
                    return

                spot_price = self.client.get_market_quote_ltp(symbol)
                if spot_price is None:
                    msg = f"Failed to fetch LTP for {symbol}. Aborting daily cycle."
                    logger.warning(msg)
                    self.notifier.send_notification(title="LTP Fetch Failed", message=msg, level="WARNING")
                    return

                chain_df = self.client.get_option_chain(symbol)

                targets = self._select_target_put(chain_df, spot_price)
                if targets is None or targets[0] is None or targets[1] is None:
                    logger.warning(f"Could not find a suitable target PUT spread for {symbol}. Aborting daily cycle.")
                    return

                short_put, long_put = targets

                short_instrument_key = short_put.get("instrument_key")
                short_strike = short_put.get("strike")
                short_expiry = short_put.get("expiry")
                short_entry_price = short_put.get("bid") # using contract bid price for entry

                long_instrument_key = long_put.get("instrument_key")
                long_strike = long_put.get("strike")
                long_expiry = long_put.get("expiry")
                long_entry_price = long_put.get("ask") # using contract ask price for hedge entry

                if short_entry_price in (None, 0, 0.0) or long_entry_price in (None, 0, 0.0):
                    msg = f"Target puts have missing liquidity (Bid/Ask = 0) for {symbol}. Aborting."
                    logger.warning(msg)
                    self.notifier.send_notification(title="Missing Liquidity", message=msg, level="WARNING")
                    return

                logger.info(f"Targets selected for {symbol}: Short {short_strike} PE (Bid: {short_entry_price}), Long {long_strike} PE (Ask: {long_entry_price}), Expiring on {short_expiry}")

                allocation_pct = symbol_config.get("allocation_pct", ALLOCATION_PCT_PER_TRADE)
                available_margin = self.client.get_available_margin()
                if available_margin is None or available_margin <= 0:
                    msg = f"Could not fetch available margin for {symbol}. Aborting."
                    logger.error(msg)
                    self.notifier.send_notification(title="Margin Fetch Failed", message=msg, level="ERROR")
                    return
                budget = available_margin * allocation_pct
                lot_size = LOT_SIZES.get(symbol, 25)

                required_capital_per_lot = (short_strike - long_strike) * lot_size
                if required_capital_per_lot <= 0:
                    logger.error(f"Invalid required capital per lot ({required_capital_per_lot}) for {symbol}. Short strike: {short_strike}, Long strike: {long_strike}. Aborting.")
                    return

                num_lots = math.floor(budget / required_capital_per_lot)

                if num_lots == 0:
                    msg = f"CRITICAL: Insufficient funds to trade {symbol}. Budget: {budget:.2f} (margin={available_margin:.2f} x {allocation_pct:.0%}), Required for 1 lot: {required_capital_per_lot}. Aborting."
                    logger.critical(msg)
                    self.notifier.send_notification(title="Insufficient Funds", message=msg, level="ERROR")
                    return

                final_quantity = num_lots * lot_size

                # Leg 1: Execute the BUY (Hedge)
                long_order_id = self.client.place_order_by_key(instrument_key=long_instrument_key, side="BUY", quantity=final_quantity, price=long_entry_price)

                if not long_order_id:
                    logger.error(f"Failed to place BUY hedge order for {symbol}.")
                    return

                long_order_filled = False
                for _ in range(3):
                    time.sleep(5)
                    status = self.client.get_order_status(long_order_id)
                    if status == "complete":
                        long_order_filled = True
                        break
                    elif status in ("rejected", "cancelled"):
                        msg = f"Hedge order {long_order_id} was {status} for {symbol}. Aborting STAGE_1_CSP transition."
                        logger.warning(msg)
                        self.notifier.send_notification(title=f"Order {status.capitalize()}", message=msg, level="WARNING")
                        return

                if not long_order_filled:
                    self.client.cancel_order(long_order_id)
                    msg = f"Hedge order {long_order_id} timed out as pending limit order for {symbol}. Order cancelled. Aborting STAGE_1_CSP transition."
                    logger.warning(msg)
                    self.notifier.send_notification(title="Order Timeout", message=msg, level="WARNING")
                    return

                # Leg 2: Execute the SELL (Short) ONLY if the BUY order is completed
                short_order_id = self.client.place_order_by_key(instrument_key=short_instrument_key, side="SELL", quantity=final_quantity, price=short_entry_price)

                if not short_order_id:
                    msg = f"CRITICAL: Failed to place SELL short order for {symbol} after filling hedge. Attempting automated unwind."
                    logger.critical(msg)
                    self.notifier.send_notification(title="CRITICAL: Short Order Failed", message=msg, level="ERROR")
                    self._unwind_hedge(symbol, long_instrument_key, final_quantity, long_order_id)
                    return

                short_order_filled = False
                for _ in range(3):
                    time.sleep(5)
                    status = self.client.get_order_status(short_order_id)
                    if status == "complete":
                        short_order_filled = True
                        break
                    elif status in ("rejected", "cancelled"):
                        self.client.cancel_order(short_order_id)
                        msg = f"CRITICAL: Short order {short_order_id} was {status} for {symbol}. Attempting automated unwind."
                        logger.critical(msg)
                        self.notifier.send_notification(title="CRITICAL: Short Order Failed", message=msg, level="ERROR")
                        self._unwind_hedge(symbol, long_instrument_key, final_quantity, long_order_id)
                        return

                if not short_order_filled:
                    self.client.cancel_order(short_order_id)
                    msg = f"CRITICAL: Short order {short_order_id} timed out for {symbol}. Order cancelled. Attempting automated unwind."
                    logger.critical(msg)
                    self.notifier.send_notification(title="CRITICAL: Order Timeout", message=msg, level="ERROR")
                    self._unwind_hedge(symbol, long_instrument_key, final_quantity, long_order_id)
                    return

                msg = f"Credit Spread placed successfully for {symbol}. STAGE_1_CSP entry: Short {short_strike} PE / Long {long_strike} PE expiring on {short_expiry}."
                logger.info(msg)
                self.notifier.send_notification(title="Order Placed", message=msg, level="INFO")

                self.state[symbol]["current_stage"] = "STAGE_1_CSP"
                self.state[symbol]["active_position"] = {
                    "strike": short_strike,
                    "expiry": short_expiry,
                    "instrument_key": short_instrument_key,
                    "entry_price": short_entry_price,
                    "order_id": short_order_id,
                    "quantity": final_quantity
                }
                self.state[symbol]["hedge_position"] = {
                    "strike": long_strike,
                    "expiry": long_expiry,
                    "instrument_key": long_instrument_key,
                    "entry_price": long_entry_price,
                    "order_id": long_order_id,
                    "quantity": final_quantity
                }
                self.state[symbol]["net_credit_received"] = (short_entry_price - long_entry_price) * final_quantity
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

    def check_exits(self):
        """
        Periodically evaluate active positions for Take Profit, Stop Loss, and Time Stop conditions.
        """
        self.state = self._load_state()
        for symbol, data in self.state.items():
            if data.get("current_stage") != "STAGE_1_CSP":
                continue

            active_position = data.get("active_position")
            hedge_position = data.get("hedge_position")

            if not active_position or not hedge_position:
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

            # Condition 1: Take Profit (<= 20% initial credit)
            take_profit = current_cost_to_close <= 0.20 * initial_credit

            # Condition 2: Stop Loss (>= 200% initial credit OR spot breaches short strike)
            stop_loss = current_cost_to_close >= 2.0 * initial_credit or spot_price <= short_strike

            # Condition 3: Time Stop (Thursday Expiry >= 15:00 IST)
            now = datetime.now(IST)
            time_stop = now.weekday() == 3 and now.hour >= 15

            if take_profit or stop_loss or time_stop:
                reason = "Take Profit" if take_profit else ("Stop Loss" if stop_loss else "Time Stop")
                msg = f"[{reason}] Exit triggered for {symbol}. Initial Credit: {initial_credit:.2f}, Cost to Close: {current_cost_to_close:.2f}, Spot: {spot_price:.2f}. Initiating closing orders..."
                logger.info(msg)
                self.notifier.send_notification(title=f"{reason} Triggered", message=msg, level="INFO" if take_profit or time_stop else "WARNING")

                # Marketable-limit: buy above ask to guarantee fill
                btc_price = round(short_live_ask * (1 + EXIT_SLIPPAGE_BUFFER_PCT), 2)
                btc_order_id = self.client.place_order_by_key(
                    instrument_key=short_instrument_key,
                    side="BUY",
                    quantity=quantity_shares,
                    price=btc_price,
                    order_type="LIMIT"  # Marketable-limit for swift exit
                )

                # Marketable-limit: sell below bid to guarantee fill
                stc_price = round(long_live_bid * (1 - EXIT_SLIPPAGE_BUFFER_PCT), 2)
                stc_order_id = self.client.place_order_by_key(
                    instrument_key=long_instrument_key,
                    side="SELL",
                    quantity=quantity_shares,
                    price=stc_price,
                    order_type="LIMIT"  # Marketable-limit for swift exit
                )

                if btc_order_id and stc_order_id:
                    both_filled = False
                    for _ in range(3):
                        time.sleep(2)
                        btc_status = self.client.get_order_status(btc_order_id)
                        stc_status = self.client.get_order_status(stc_order_id)

                        if btc_status == "complete" and stc_status == "complete":
                            both_filled = True
                            break

                    if both_filled:
                        pnl = (initial_credit - current_cost_to_close) * quantity_shares
                        self._archive_trade(symbol, reason, pnl)
                        self.state[symbol]["realized_pnl"] += pnl
                        self.state[symbol]["current_stage"] = "CLOSED"
                        self.state[symbol]["active_position"] = None
                        self.state[symbol]["hedge_position"] = None
                        self._save_state(symbol)

                        success_msg = f"Exit completed for {symbol} due to {reason}. P&L: {pnl:.2f}. State updated to CLOSED."
                        logger.info(success_msg)
                        self.notifier.send_notification(title="Exit Complete", message=success_msg, level="INFO")
                    else:
                        fail_msg = f"Exit orders not fully filled for {symbol}. BTC={btc_status}, STC={stc_status}. State NOT updated — manual intervention required."
                        logger.error(fail_msg)
                        self.notifier.send_notification(title="Exit Verification Failed", message=fail_msg, level="ERROR")
                else:
                    logger.error(f"Failed to place closing orders for {symbol}.")


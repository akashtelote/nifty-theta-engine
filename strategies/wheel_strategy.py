import time
import sqlite3
import os
import logging
from datetime import datetime, date
import polars as pl
from core.client import UpstoxClient
import math
from core.notifier import Notifier

logger = logging.getLogger(__name__)

LOT_SIZES = {"RELIANCE": 250, "HDFCBANK": 550, "INFY": 400}

class WheelStateMachine:
    def __init__(self):
        """
        Initializes the Wheel Strategy State Machine.
        Safely loads or creates the data/wheel_state.db database to prevent
        race conditions during concurrent/daily executions.
        """
        self.db_file = "data/wheel_state.db"

        # Ensure data directory exists
        os.makedirs(os.path.dirname(self.db_file), exist_ok=True)

        self._initialize_db()
        self.state = self._load_state()
        self.client = UpstoxClient()
        self.notifier = Notifier()

    def _initialize_db(self):
        """
        Initializes the SQLite database and creates the wheel_state table if it doesn't exist.
        """
        try:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS wheel_state (
                    symbol TEXT PRIMARY KEY,
                    current_stage TEXT,
                    instrument_key TEXT,
                    strike_price REAL,
                    expiry TEXT,
                    trade_date TEXT,
                    entry_price REAL,
                    order_id TEXT,
                    assigned_shares INTEGER,
                    average_cost_basis REAL,
                    realized_pnl REAL
                )
            ''')
            conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Error initializing database: {e}")
        finally:
            if conn:
                conn.close()

    def _load_state(self) -> dict:
        """
        Loads state from the SQLite database and parses it into the nested dictionary format.
        """
        state = {}
        try:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM wheel_state")
            rows = cursor.fetchall()
            for row in rows:
                (symbol, current_stage, instrument_key, strike_price, expiry, trade_date,
                 entry_price, order_id, assigned_shares, average_cost_basis, realized_pnl) = row

                state[symbol] = {
                    "current_stage": current_stage,
                    "active_position": None if instrument_key is None else {
                        "instrument_key": instrument_key,
                        "strike": strike_price,
                        "expiry": expiry,
                        "entry_price": entry_price,
                        "order_id": order_id
                    },
                    "inventory": {
                        "assigned_shares": assigned_shares if assigned_shares is not None else 0,
                        "average_cost_basis": average_cost_basis if average_cost_basis is not None else 0.0
                    },
                    "realized_pnl": realized_pnl if realized_pnl is not None else 0.0
                }
        except sqlite3.Error as e:
            logger.error(f"Error loading state from database: {e}")
        finally:
            if 'conn' in locals() and conn:
                conn.close()
        return state

    def _save_state(self, symbol: str):
        """
        Saves the state for a specific symbol to the SQLite database.
        """
        symbol_state = self.state.get(symbol)
        if not symbol_state:
            return

        current_stage = symbol_state.get("current_stage", "IDLE")
        active_position = symbol_state.get("active_position")
        inventory = symbol_state.get("inventory", {})
        realized_pnl = symbol_state.get("realized_pnl", 0.0)

        assigned_shares = inventory.get("assigned_shares", 0)
        average_cost_basis = inventory.get("average_cost_basis", 0.0)

        if active_position:
            instrument_key = active_position.get("instrument_key")
            strike_price = active_position.get("strike")
            expiry = active_position.get("expiry")
            entry_price = active_position.get("entry_price")
            order_id = active_position.get("order_id")
            trade_date = date.today().isoformat()
        else:
            instrument_key = None
            strike_price = None
            expiry = None
            entry_price = None
            order_id = None
            trade_date = None

        try:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO wheel_state
                (symbol, current_stage, instrument_key, strike_price, expiry, trade_date,
                 entry_price, order_id, assigned_shares, average_cost_basis, realized_pnl)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (symbol, current_stage, instrument_key, strike_price, expiry, trade_date,
                  entry_price, order_id, assigned_shares, average_cost_basis, realized_pnl))
            conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Error saving state to database for {symbol}: {e}")
        finally:
            if 'conn' in locals() and conn:
                conn.close()

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
                "inventory": {
                    "assigned_shares": 0,
                    "average_cost_basis": 0.0
                },
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

    def _select_target_put(self, chain_df: pl.DataFrame, spot_price: float, min_days: int = 10, max_days: int = 42) -> dict | None:
        if chain_df.is_empty():
            return None

        today = date.today()

        # Parse expiry dates and calculate days to expiry
        # Assuming expiry format is 'YYYY-MM-DD'
        df = chain_df.filter(pl.col("type") == "PE")

        if df.is_empty():
            return None

        # Calculate days to expiry
        # Safely parsing the date strings, ignoring invalid ones
        df = df.with_columns([
            pl.col("expiry").str.strptime(pl.Date, "%Y-%m-%d", strict=False).alias("parsed_expiry")
        ])

        # Filter out rows where parsing failed
        df = df.filter(pl.col("parsed_expiry").is_not_null())

        if df.is_empty():
            return None

        df = df.with_columns([
            (pl.col("parsed_expiry") - today).dt.total_days().alias("dte")
        ])

        # Filter by DTE
        df = df.filter((pl.col("dte") >= min_days) & (pl.col("dte") <= max_days))

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

        target_strike = spot_price * (1 - otm_pct)

        # Filter to ensure strikes are strictly less than or equal to target_strike
        df = df.filter(pl.col("strike") <= target_strike)

        if df.is_empty():
            return None

        # Find closest strike
        df = df.with_columns([
            (pl.col("strike") - target_strike).abs().alias("strike_diff")
        ])

        df = df.sort("strike_diff")

        if df.is_empty():
            return None

        return df.row(0, named=True)



    def execute_daily_cycle(self, symbol: str, symbol_config: dict, is_live: bool = False):
        # Reload state from DB before proceeding
        self.state = self._load_state()
        self.ensure_symbol_state(symbol)

        current_stage = self.state[symbol].get("current_stage", "IDLE")

        if current_stage == "IDLE":
            logger.info(f"Executing daily cycle for {symbol} in IDLE state.")

            # VIX Circuit Breaker
            current_vix = self.client.get_india_vix()
            vix_max_threshold = float(os.getenv("VIX_MAX_THRESHOLD", 25.0))
            if current_vix is not None and current_vix > vix_max_threshold:
                msg = f"VIX Circuit Breaker Triggered: Current VIX ({current_vix}) exceeds maximum threshold ({vix_max_threshold}). Aborting daily cycle for {symbol}."
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

            target_put = self._select_target_put(chain_df, spot_price)
            if target_put is None:
                logger.warning(f"Could not find a suitable target PUT for {symbol}. Aborting daily cycle.")
                return

            instrument_key = target_put.get("instrument_key")
            strike = target_put.get("strike")
            expiry = target_put.get("expiry")
            entry_price = target_put.get("bid") # using contract bid price for entry

            if entry_price is None or entry_price == 0:
                msg = f"Target put has no valid bid price for {symbol}. Aborting."
                logger.warning(msg)
                self.notifier.send_notification(title="Missing Liquidity", message=msg, level="WARNING")
                return

            logger.info(f"Target selected: {strike} PE expiring on {expiry} for {symbol}. Bid price: {entry_price}")

            # Dynamic Position Sizing
            available_funds = self.client.get_available_margin()
            if available_funds is None:
                msg = f"Failed to fetch available margin for {symbol}. Aborting daily cycle to protect capital."
                logger.warning(msg)
                self.notifier.send_notification(title="Margin Fetch Failed", message=msg, level="WARNING")
                return

            allocation_pct = symbol_config.get("allocation_pct", 0.10)
            lot_size = LOT_SIZES.get(symbol, 1)

            target_capital = available_funds * allocation_pct
            required_capital_per_lot = strike * lot_size
            num_lots = math.floor(target_capital / required_capital_per_lot)

            if num_lots == 0:
                msg = f"Insufficient funds to trade {symbol}. Target capital: {target_capital}, Required for 1 lot: {required_capital_per_lot}. Aborting."
                logger.warning(msg)
                self.notifier.send_notification(title="Insufficient Funds", message=msg, level="WARNING")
                return

            final_quantity = num_lots * lot_size

            order_id = self.client.place_order_by_key(instrument_key=instrument_key, side="SELL", quantity=final_quantity, price=entry_price, is_live=is_live)

            if order_id:
                order_filled = False
                for _ in range(3):
                    time.sleep(5)
                    status = self.client.get_order_status(order_id)
                    if status == "complete":
                        order_filled = True
                        break
                    elif status in ("rejected", "cancelled"):
                        msg = f"Order {order_id} was {status} for {symbol}. Aborting STAGE_1_CSP transition."
                        logger.warning(msg)
                        self.notifier.send_notification(title=f"Order {status.capitalize()}", message=msg, level="WARNING")
                        return

                if not order_filled:
                    self.client.cancel_order(order_id)
                    msg = f"Order {order_id} timed out as pending limit order for {symbol}. Order cancelled. Aborting STAGE_1_CSP transition."
                    logger.warning(msg)
                    self.notifier.send_notification(title="Order Timeout", message=msg, level="WARNING")
                    return

                msg = f"Order placed successfully for {symbol}. STAGE_1_CSP entry: {strike} PE expiring on {expiry} at {entry_price}."
                logger.info(msg)
                self.notifier.send_notification(title="Order Placed", message=msg, level="INFO")
                self.state[symbol]["current_stage"] = "STAGE_1_CSP"
                self.state[symbol]["active_position"] = {
                    "strike": strike,
                    "expiry": expiry,
                    "instrument_key": instrument_key,
                    "entry_price": entry_price,
                    "order_id": order_id,
                    "quantity": final_quantity
                }
                self._save_state(symbol)
            else:
                logger.error("Failed to place order.")

        elif current_stage == "STAGE_1_CSP":
            logger.info(f"Executing daily cycle for {symbol} in STAGE_1_CSP state.")
            active_position = self.state[symbol].get("active_position")
            if not active_position:
                logger.error(f"Active position missing for {symbol} in STAGE_1_CSP state. Resetting to IDLE.")
                self.state[symbol]["current_stage"] = "IDLE"
                self._save_state(symbol)
                return

            quantity_shares = active_position.get("quantity", LOT_SIZES.get(symbol, 1))

            expiry_str = active_position.get("expiry")
            try:
                expiry_date = datetime.strptime(expiry_str, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                logger.error(f"Invalid expiry date format for {symbol}: {expiry_str}")
                return

            dte = (expiry_date - date.today()).days

            spot_price = self.client.get_market_quote_ltp(symbol)
            if spot_price is None:
                msg = f"Failed to fetch LTP for {symbol}. Aborting daily cycle."
                logger.warning(msg)
                self.notifier.send_notification(title="LTP Fetch Failed", message=msg, level="WARNING")
                return

            strike = active_position["strike"]
            entry_price = active_position["entry_price"]
            instrument_key = active_position["instrument_key"]

            # Defensive Trigger
            if dte <= 3 and spot_price <= strike:
                msg = f"[DEFENSE] Position for {symbol} is ITM with only {dte} days to expiry. Initiating defensive buy-back..."
                logger.warning(msg)
                self.notifier.send_notification(title="Defensive Roll Triggered", message=msg, level="WARNING")

                df = self.client.get_option_chain(symbol, expiry_date=expiry_str)
                contract_df = df.filter(pl.col("instrument_key") == instrument_key)

                if contract_df.is_empty():
                    logger.error(f"Could not find contract {instrument_key} in option chain for defensive roll.")
                    return

                contract_row = contract_df.row(0, named=True)
                buy_price = contract_row.get("ask")

                if buy_price is None or buy_price == 0.0:
                    buy_price = contract_row.get("last_price")

                if buy_price is None or buy_price == 0.0:
                    logger.error(f"No valid price (Ask or Last) found for {instrument_key} to buy back. Aborting.")
                    return

                logger.info(f"Attempting to buy back {instrument_key} at {buy_price}")
                order_id = self.client.place_order_by_key(
                    instrument_key=instrument_key,
                    side="BUY",
                    quantity=quantity_shares,
                    price=buy_price,
                    is_live=is_live
                )

                if order_id:
                    order_filled = False
                    for _ in range(3):
                        time.sleep(5)
                        status = self.client.get_order_status(order_id)
                        if status == "complete":
                            order_filled = True
                            break
                        elif status in ("rejected", "cancelled"):
                            abort_msg = f"Defensive order {order_id} was {status} for {symbol}. Aborting defensive roll."
                            logger.warning(abort_msg)
                            self.notifier.send_notification(title=f"Order {status.capitalize()}", message=abort_msg, level="WARNING")
                            return

                    if not order_filled:
                        self.client.cancel_order(order_id)
                        timeout_msg = f"Defensive order {order_id} timed out as pending limit order for {symbol}. Order cancelled. Aborting defensive roll."
                        logger.warning(timeout_msg)
                        self.notifier.send_notification(title="Order Timeout", message=timeout_msg, level="WARNING")
                        return

                    success_msg = f"Defensive buy-back completed successfully for {symbol}. Resetting state to IDLE."
                    logger.info(success_msg)
                    self.notifier.send_notification(title="Defensive Buy-Back Complete", message=success_msg, level="INFO")

                    self.state[symbol]["current_stage"] = "IDLE"
                    self.state[symbol]["active_position"] = None
                    self._save_state(symbol)
                    return
                else:
                    logger.error(f"Failed to place defensive buy order for {symbol}.")
                    return

            if expiry_date != date.today():
                logger.info("Holding position...")
                return

            if spot_price > strike:
                # Worthless Expiration (OTM)
                profit = entry_price * quantity_shares
                self.state[symbol]["realized_pnl"] += profit
                self.state[symbol]["current_stage"] = "IDLE"
                self.state[symbol]["active_position"] = None
                msg = f"Put expired worthless for {symbol}. Profit: {profit}. New realized PnL: {self.state[symbol]['realized_pnl']}"
                logger.info(msg)
                self.notifier.send_notification(title="Put Expired Worthless", message=msg, level="INFO")
            else:
                # Assignment (ITM)
                new_cost_basis = max(0.0, strike - entry_price)
                self.state[symbol]["inventory"]["assigned_shares"] = quantity_shares
                self.state[symbol]["inventory"]["average_cost_basis"] = new_cost_basis
                self.state[symbol]["current_stage"] = "STAGE_2_CC"
                self.state[symbol]["active_position"] = None
                msg = f"Put assigned for {symbol}. Assigned shares: {quantity_shares}. New cost basis: {new_cost_basis}"
                logger.info(msg)
                self.notifier.send_notification(title="Put Assigned", message=msg, level="INFO")

            self._save_state(symbol)

        elif current_stage == "STAGE_2_CC":
            logger.info(f"Executing daily cycle for {symbol} in STAGE_2_CC state.")
            active_position = self.state[symbol].get("active_position")

            # Since assignment happened in STAGE_1_CSP, the inventory has the assigned shares.
            # We use this as our CC selling quantity.
            quantity_shares = self.state[symbol]["inventory"]["assigned_shares"]
            if quantity_shares == 0:
                quantity_shares = LOT_SIZES.get(symbol, 1)

            if active_position is not None:
                quantity_shares = active_position.get("quantity", quantity_shares)

                expiry_str = active_position.get("expiry")
                try:
                    expiry_date = datetime.strptime(expiry_str, "%Y-%m-%d").date()
                except (ValueError, TypeError):
                    logger.error(f"Invalid expiry date format for {symbol}: {expiry_str}")
                    return

                if expiry_date != date.today():
                    logger.info("Holding covered call, expiry is not today.")
                    return

                spot_price = self.client.get_market_quote_ltp(symbol)
                if spot_price is None:
                    msg = f"Failed to fetch LTP for {symbol} on expiry day. Aborting daily cycle."
                    logger.warning(msg)
                    self.notifier.send_notification(title="LTP Fetch Failed", message=msg, level="WARNING")
                    return

                strike = active_position["strike"]
                entry_price = active_position["entry_price"]

                if spot_price <= strike:
                    # Worthless Expiration (OTM)
                    profit = entry_price * quantity_shares
                    self.state[symbol]["realized_pnl"] += profit
                    self.state[symbol]["active_position"] = None
                    msg = f"Call expired worthless for {symbol}. Profit: {profit}. Shares retained. New realized PnL: {self.state[symbol]['realized_pnl']}"
                    logger.info(msg)
                    self.notifier.send_notification(title="Call Expired Worthless", message=msg, level="INFO")
                else:
                    # Assignment (ITM) - Shares called away
                    capital_gains = (strike - self.state[symbol]["inventory"]["average_cost_basis"]) * quantity_shares
                    premium_profit = entry_price * quantity_shares
                    total_profit = capital_gains + premium_profit

                    self.state[symbol]["realized_pnl"] += total_profit
                    self.state[symbol]["inventory"]["assigned_shares"] = 0
                    self.state[symbol]["inventory"]["average_cost_basis"] = 0.0
                    self.state[symbol]["active_position"] = None
                    self.state[symbol]["current_stage"] = "IDLE"
                    msg = f"Shares called away for {symbol}. Total profit: {total_profit}. Cycle complete."
                    logger.info(msg)
                    self.notifier.send_notification(title="Shares Called Away", message=msg, level="INFO")

                self._save_state(symbol)
                return

            # We need to sell a call
            cost_basis = self.state[symbol]["inventory"]["average_cost_basis"]

            spot_price = self.client.get_market_quote_ltp(symbol)
            if spot_price is None:
                msg = f"Failed to fetch LTP for {symbol} in STAGE_2_CC. Aborting daily cycle."
                logger.warning(msg)
                self.notifier.send_notification(title="LTP Fetch Failed", message=msg, level="WARNING")
                return

            chain_df = self.client.get_option_chain(symbol)

            target_call = self._select_target_call(chain_df, spot_price, cost_basis)
            if target_call is None:
                logger.warning(f"No valid calls found above cost basis for {symbol}, holding shares.")
                return

            instrument_key = target_call.get("instrument_key")
            strike = target_call.get("strike")
            expiry = target_call.get("expiry")
            entry_price = target_call.get("bid") # using contract bid price for entry

            if entry_price is None or entry_price == 0 or entry_price == 0.0:
                msg = f"Selected contract has no liquidity (Bid = 0) for {symbol}. Aborting cycle."
                logger.warning(msg)
                self.notifier.send_notification(title="Missing Liquidity", message=msg, level="WARNING")
                return

            logger.info(f"Target Call selected: {strike} CE expiring on {expiry} for {symbol}. Bid price: {entry_price}")

            order_id = self.client.place_order_by_key(instrument_key=instrument_key, side="SELL", quantity=quantity_shares, price=entry_price, is_live=is_live)

            if order_id:
                order_filled = False
                for _ in range(3):
                    time.sleep(5)
                    status = self.client.get_order_status(order_id)
                    if status == "complete":
                        order_filled = True
                        break
                    elif status in ("rejected", "cancelled"):
                        msg = f"Order {order_id} was {status} for {symbol}. Aborting STAGE_2_CC entry."
                        logger.warning(msg)
                        self.notifier.send_notification(title=f"Order {status.capitalize()}", message=msg, level="WARNING")
                        return

                if not order_filled:
                    self.client.cancel_order(order_id)
                    msg = f"Order {order_id} timed out as pending limit order for {symbol}. Order cancelled. Aborting STAGE_2_CC entry."
                    logger.warning(msg)
                    self.notifier.send_notification(title="Order Timeout", message=msg, level="WARNING")
                    return

                msg = f"Order placed successfully for {symbol}. STAGE_2_CC entry: {strike} CE expiring on {expiry} at {entry_price}."
                logger.info(msg)
                self.notifier.send_notification(title="Order Placed", message=msg, level="INFO")
                self.state[symbol]["active_position"] = {
                    "strike": strike,
                    "expiry": expiry,
                    "instrument_key": instrument_key,
                    "entry_price": entry_price,
                    "order_id": order_id,
                    "quantity": quantity_shares
                }
                self._save_state(symbol)
            else:
                logger.error("Failed to place call order.")

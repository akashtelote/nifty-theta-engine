import time
import sqlite3
import os
import logging
from datetime import datetime, date
import polars as pl
from core.client import UpstoxClient
import math
from core.notifier import Notifier
import yfinance as yf
from ml_service.vix_inference_worker import VixRegimePredictor

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
        self.ml_predictor = VixRegimePredictor()

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
                    realized_pnl REAL,
                    hedge_instrument_key TEXT,
                    hedge_strike_price REAL,
                    hedge_entry_price REAL,
                    hedge_order_id TEXT
                )
            ''')

            # Migration block for existing databases
            for column_def in [
                "hedge_instrument_key TEXT",
                "hedge_strike_price REAL",
                "hedge_entry_price REAL",
                "hedge_order_id TEXT"
            ]:
                try:
                    cursor.execute(f"ALTER TABLE wheel_state ADD COLUMN {column_def}")
                except sqlite3.OperationalError:
                    # Column already exists
                    pass

            conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Error initializing database: {e}")
        finally:
            if 'conn' in locals() and conn:
                conn.close()

    def _load_state(self) -> dict:
        """
        Loads state from the SQLite database and parses it into the nested dictionary format.
        """
        state = {}
        try:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()
            cursor.execute('''
                SELECT symbol, current_stage, instrument_key, strike_price, expiry, trade_date,
                       entry_price, order_id, assigned_shares, average_cost_basis, realized_pnl,
                       hedge_instrument_key, hedge_strike_price, hedge_entry_price, hedge_order_id
                FROM wheel_state
            ''')
            rows = cursor.fetchall()
            for row in rows:
                (symbol, current_stage, instrument_key, strike_price, expiry, trade_date,
                 entry_price, order_id, assigned_shares, average_cost_basis, realized_pnl,
                 hedge_instrument_key, hedge_strike_price, hedge_entry_price, hedge_order_id) = row

                state[symbol] = {
                    "current_stage": current_stage,
                    "active_position": None if instrument_key is None else {
                        "instrument_key": instrument_key,
                        "strike": strike_price,
                        "expiry": expiry,
                        "entry_price": entry_price,
                        "order_id": order_id
                    },
                    "hedge_position": None if hedge_instrument_key is None else {
                        "instrument_key": hedge_instrument_key,
                        "strike": hedge_strike_price,
                        "entry_price": hedge_entry_price,
                        "order_id": hedge_order_id
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
        hedge_position = symbol_state.get("hedge_position")
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

        if hedge_position:
            hedge_instrument_key = hedge_position.get("instrument_key")
            hedge_strike_price = hedge_position.get("strike")
            hedge_entry_price = hedge_position.get("entry_price")
            hedge_order_id = hedge_position.get("order_id")
        else:
            hedge_instrument_key = None
            hedge_strike_price = None
            hedge_entry_price = None
            hedge_order_id = None

        try:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO wheel_state
                (symbol, current_stage, instrument_key, strike_price, expiry, trade_date,
                 entry_price, order_id, assigned_shares, average_cost_basis, realized_pnl,
                 hedge_instrument_key, hedge_strike_price, hedge_entry_price, hedge_order_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (symbol, current_stage, instrument_key, strike_price, expiry, trade_date,
                  entry_price, order_id, assigned_shares, average_cost_basis, realized_pnl,
                  hedge_instrument_key, hedge_strike_price, hedge_entry_price, hedge_order_id))
            conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Error saving state to database for {symbol}: {e}")
        finally:
            if 'conn' in locals() and conn:
                conn.close()

    def _fetch_macro_context(self) -> pl.LazyFrame:
        """
        Fetches the last 40 days of NIFTY 50 and India VIX data.
        Cleans and merges them into a single Polars DataFrame returning a LazyFrame.
        """
        logger.info("Fetching macro context for ML regime filter.")
        try:
            # Download last 40 days
            nifty = yf.download("^NSEI", period="40d", progress=False)
            vix = yf.download("^INDIAVIX", period="40d", progress=False)

            if nifty.empty or vix.empty:
                logger.warning("Failed to fetch NIFTY or VIX data from yfinance.")
                # Return empty frame that will trigger failsafe in predictor
                return pl.DataFrame({"Date": [], "NIFTY_Close": [], "VIX_Close": []}).lazy()

            # Flatten multi-index if necessary (yf sometimes returns multi-index for close)
            if isinstance(nifty.columns, pl.Series) or hasattr(nifty.columns, "levels"): # Check if MultiIndex
                 if "Close" in nifty:
                     nifty_close = nifty["Close"]["^NSEI"]
                 else:
                     nifty_close = nifty.iloc[:, 0] # fallback
            else:
                nifty_close = nifty["Close"] if "Close" in nifty else nifty.iloc[:, 0]

            if isinstance(vix.columns, pl.Series) or hasattr(vix.columns, "levels"):
                if "Close" in vix:
                    vix_close = vix["Close"]["^INDIAVIX"]
                else:
                    vix_close = vix.iloc[:, 0]
            else:
                vix_close = vix["Close"] if "Close" in vix else vix.iloc[:, 0]

            import pandas as pd
            nifty_date = pd.to_datetime(nifty.index).tz_localize(None)
            vix_date = pd.to_datetime(vix.index).tz_localize(None)

            nifty_df = pl.DataFrame({
                "Date": nifty_date,
                "NIFTY_Close": nifty_close.values
            })

            vix_df = pl.DataFrame({
                "Date": vix_date,
                "VIX_Close": vix_close.values
            })

            # Cast Date to pl.Date
            nifty_df = nifty_df.with_columns(pl.col("Date").cast(pl.Date))
            vix_df = vix_df.with_columns(pl.col("Date").cast(pl.Date))

            # Merge, forward fill and drop nulls
            merged_df = nifty_df.join(vix_df, on="Date", how="left")
            merged_df = merged_df.with_columns(pl.col("VIX_Close").fill_null(strategy="forward"))
            merged_df = merged_df.drop_nulls()

            return merged_df.lazy()

        except Exception as e:
            logger.error(f"Error fetching macro context: {e}", exc_info=True)
            return pl.DataFrame({"Date": [], "NIFTY_Close": [], "VIX_Close": []}).lazy()

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

    def _select_target_put(self, chain_df: pl.DataFrame, spot_price: float, vix_prob: float, min_days: int = 10, max_days: int = 42) -> tuple[dict | None, dict | None]:
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

        if vix_prob < 0.30:
            otm_pct = 0.02
        elif 0.30 <= vix_prob < 0.60:
            otm_pct = 0.03
        else:
            otm_pct = 0.04

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
        hedge_target_strike = short_strike * 0.98
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

    def execute_daily_cycle(self, symbol: str, quantity_shares: int, symbol_config: dict, is_live: bool = False):
        # Reload state from DB before proceeding
        self.state = self._load_state()
        self.ensure_symbol_state(symbol)

        current_stage = self.state[symbol].get("current_stage", "IDLE")

        if current_stage == "IDLE":
            logger.info(f"Executing daily cycle for {symbol} in IDLE state.")

            # VIX Circuit Breaker with ML Regime Filter
            recent_data = self._fetch_macro_context()
            spike_prob = self.ml_predictor.predict_spike_probability(recent_data)
            logger.info(f"ML Regime Filter spike probability: {spike_prob:.4f}")

            if spike_prob >= 0.75:
                msg = f"ML Regime Filter triggered. High probability of volatility spike ({spike_prob:.4f}). Aborting trade execution for {symbol}."
                logger.warning(msg)
                self.notifier.send_notification(title="ML Regime Filter", message=msg, level="WARNING")
                return

            spot_price = self.client.get_market_quote_ltp(symbol)
            if spot_price is None:
                msg = f"Failed to fetch LTP for {symbol}. Aborting daily cycle."
                logger.warning(msg)
                self.notifier.send_notification(title="LTP Fetch Failed", message=msg, level="WARNING")
                return

            chain_df = self.client.get_option_chain(symbol)

            targets = self._select_target_put(chain_df, spot_price, spike_prob)
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
            required_capital_per_lot = (short_strike - long_strike) * lot_size
            if required_capital_per_lot <= 0:
                logger.error(f"Invalid required capital per lot ({required_capital_per_lot}) for {symbol}. Short strike: {short_strike}, Long strike: {long_strike}. Aborting.")
                return

            num_lots = math.floor(target_capital / required_capital_per_lot)

            if num_lots == 0:
                msg = f"Insufficient funds to trade {symbol}. Target capital: {target_capital}, Required for 1 lot: {required_capital_per_lot}. Aborting."
                logger.warning(msg)
                self.notifier.send_notification(title="Insufficient Funds", message=msg, level="WARNING")
                return

            final_quantity = num_lots * lot_size

            # Leg 1: Execute the BUY (Hedge)
            long_order_id = self.client.place_order_by_key(instrument_key=long_instrument_key, side="BUY", quantity=final_quantity, price=long_entry_price, is_live=is_live)

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
            short_order_id = self.client.place_order_by_key(instrument_key=short_instrument_key, side="SELL", quantity=final_quantity, price=short_entry_price, is_live=is_live)

            if not short_order_id:
                msg = f"CRITICAL: Failed to place SELL short order for {symbol} after filling hedge. Manual intervention required to close the dangling long put."
                logger.critical(msg)
                self.notifier.send_notification(title="CRITICAL: Short Order Failed", message=msg, level="ERROR")
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
                    msg = f"CRITICAL: Short order {short_order_id} was {status} for {symbol}. Manual intervention required to close the dangling long put."
                    logger.critical(msg)
                    self.notifier.send_notification(title="CRITICAL: Short Order Failed", message=msg, level="ERROR")
                    return

            if not short_order_filled:
                self.client.cancel_order(short_order_id)
                msg = f"CRITICAL: Short order {short_order_id} timed out as pending limit order for {symbol}. Order cancelled. Manual intervention required to close the dangling long put."
                logger.critical(msg)
                self.notifier.send_notification(title="CRITICAL: Order Timeout", message=msg, level="ERROR")
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
            self._save_state(symbol)

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
                # Dynamic Profit-Taking (50% Rule)
                hedge_position = self.state[symbol].get("hedge_position")
                if active_position and hedge_position:
                    short_entry_price = active_position.get("entry_price", 0.0)
                    long_entry_price = hedge_position.get("entry_price", 0.0)
                    initial_credit = short_entry_price - long_entry_price

                    short_instrument_key = active_position.get("instrument_key")
                    long_instrument_key = hedge_position.get("instrument_key")

                    chain_df = self.client.get_option_chain(symbol, expiry_date=expiry_str)

                    short_contract_df = chain_df.filter(pl.col("instrument_key") == short_instrument_key)
                    long_contract_df = chain_df.filter(pl.col("instrument_key") == long_instrument_key)

                    if not short_contract_df.is_empty() and not long_contract_df.is_empty():
                        short_live_ask = short_contract_df.row(0, named=True).get("ask")
                        long_live_bid = long_contract_df.row(0, named=True).get("bid")

                        if short_live_ask is not None and long_live_bid is not None:
                            current_cost_to_close = short_live_ask - long_live_bid

                            if current_cost_to_close <= 0.5 * initial_credit:
                                msg = f"[PROFIT TAKING] 50% Rule triggered for {symbol}. Initial Credit: {initial_credit:.2f}, Current Cost to Close: {current_cost_to_close:.2f}. Initiating closing orders..."
                                logger.info(msg)
                                self.notifier.send_notification(title="Profit Taking Triggered", message=msg, level="INFO")

                                # Buy to close Short Put
                                btc_order_id = self.client.place_order_by_key(
                                    instrument_key=short_instrument_key,
                                    side="BUY",
                                    quantity=quantity_shares,
                                    price=short_live_ask,
                                    is_live=is_live
                                )

                                # Sell to close Long Put
                                stc_order_id = self.client.place_order_by_key(
                                    instrument_key=long_instrument_key,
                                    side="SELL",
                                    quantity=quantity_shares,
                                    price=long_live_bid,
                                    is_live=is_live
                                )

                                if btc_order_id and stc_order_id:
                                    # Simplistic wait for both orders
                                    orders_filled = False
                                    for _ in range(3):
                                        time.sleep(5)
                                        btc_status = self.client.get_order_status(btc_order_id)
                                        stc_status = self.client.get_order_status(stc_order_id)

                                        if btc_status == "complete" and stc_status == "complete":
                                            orders_filled = True
                                            break
                                        elif "rejected" in (btc_status, stc_status) or "cancelled" in (btc_status, stc_status):
                                            abort_msg = f"Profit taking orders for {symbol} were rejected/cancelled. Aborting."
                                            logger.warning(abort_msg)
                                            self.notifier.send_notification(title="Profit Taking Failed", message=abort_msg, level="WARNING")
                                            return

                                    if not orders_filled:
                                        self.client.cancel_order(btc_order_id)
                                        self.client.cancel_order(stc_order_id)
                                        timeout_msg = f"Profit taking orders timed out as pending limit order for {symbol}. Orders cancelled."
                                        logger.warning(timeout_msg)
                                        self.notifier.send_notification(title="Profit Taking Timeout", message=timeout_msg, level="WARNING")
                                        return

                                    # Successful closing
                                    profit = (initial_credit - current_cost_to_close) * quantity_shares
                                    self.state[symbol]["realized_pnl"] += profit
                                    self.state[symbol]["current_stage"] = "IDLE"
                                    self.state[symbol]["active_position"] = None
                                    self.state[symbol]["hedge_position"] = None
                                    self._save_state(symbol)

                                    success_msg = f"Profit taking completed successfully for {symbol}. Profit: {profit}. Resetting state to IDLE."
                                    logger.info(success_msg)
                                    self.notifier.send_notification(title="Profit Taking Complete", message=success_msg, level="INFO")
                                    return
                                else:
                                    logger.error(f"Failed to place profit taking orders for {symbol}.")
                                    return

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

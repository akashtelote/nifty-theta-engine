import time
import psycopg2
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
        Safely connects to the PostgreSQL database using DATABASE_URL.
        """
        self.db_url = os.getenv("DATABASE_URL", "postgresql://wheelbot:securepassword@localhost:5432/wheeldb")

        self.state = self._load_state()
        self.client = UpstoxClient()
        self.notifier = Notifier()
        self.ml_predictor = VixRegimePredictor()

    def _load_state(self) -> dict:
        """
        Loads state from the PostgreSQL database and parses it into the nested dictionary format.
        """
        state = {}
        try:
            conn = psycopg2.connect(self.db_url)
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
            # Ensure the table exists or log a warning if it hasn't been initialized yet
        finally:
            if 'conn' in locals() and conn:
                conn.close()
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

        try:
            conn = psycopg2.connect(self.db_url)
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

            # Dynamic Position Sizing (Hardcoded Budget)
            BUDGET = 20000.0
            lot_size = LOT_SIZES.get(symbol, 25) # Default NIFTY lot size is 25

            required_capital_per_lot = (short_strike - long_strike) * lot_size
            if required_capital_per_lot <= 0:
                logger.error(f"Invalid required capital per lot ({required_capital_per_lot}) for {symbol}. Short strike: {short_strike}, Long strike: {long_strike}. Aborting.")
                return

            num_lots = math.floor(BUDGET / required_capital_per_lot)

            if num_lots == 0:
                msg = f"CRITICAL: Insufficient funds to trade {symbol}. Budget: {BUDGET}, Required for 1 lot: {required_capital_per_lot}. Aborting."
                logger.critical(msg)
                self.notifier.send_notification(title="Insufficient Funds", message=msg, level="ERROR")
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
            self.state[symbol]["net_credit_received"] = (short_entry_price - long_entry_price) * final_quantity
            self._save_state(symbol)

        elif current_stage == "STAGE_1_CSP":
            logger.info(f"Executing daily cycle for {symbol} in STAGE_1_CSP state.")
            active_position = self.state[symbol].get("active_position")
            if not active_position:
                logger.error(f"Active position missing for {symbol} in STAGE_1_CSP state. Resetting to IDLE.")
                self.state[symbol]["current_stage"] = "IDLE"
                self._save_state(symbol)
                return

            quantity_shares = active_position.get("quantity", LOT_SIZES.get(symbol, 25))

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

            if expiry_date != date.today():
                # Dynamic Profit-Taking (50% Rule) and Stop-Loss (200% Rule)
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
                                msg = f"[PROFIT TAKING] 50% Rule triggered for {symbol}. Initial Credit: {initial_credit:.2f}, Current Cost to Close: {current_cost_to_close:.2f}. Initiating closing orders (Limit)..."
                                logger.info(msg)
                                self.notifier.send_notification(title="Profit Taking Triggered", message=msg, level="INFO")

                                # Buy to close Short Put (Limit)
                                btc_order_id = self.client.place_order_by_key(
                                    instrument_key=short_instrument_key,
                                    side="BUY",
                                    quantity=quantity_shares,
                                    price=short_live_ask,
                                    is_live=is_live
                                )

                                # Sell to close Long Put (Limit)
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

                            elif current_cost_to_close >= 2.0 * initial_credit:
                                msg = f"[STOP LOSS] 200% Rule triggered for {symbol}. Initial Credit: {initial_credit:.2f}, Current Cost to Close: {current_cost_to_close:.2f}. Initiating emergency closing orders (Market)..."
                                logger.critical(msg)
                                self.notifier.send_notification(title="Stop Loss Triggered", message=msg, level="ERROR")

                                # Buy to close Short Put (Market)
                                btc_order_id = self.client.place_order_by_key(
                                    instrument_key=short_instrument_key,
                                    side="BUY",
                                    quantity=quantity_shares,
                                    price=0.0, # Market order
                                    is_live=is_live
                                )

                                # Sell to close Long Put (Market)
                                stc_order_id = self.client.place_order_by_key(
                                    instrument_key=long_instrument_key,
                                    side="SELL",
                                    quantity=quantity_shares,
                                    price=0.0, # Market order
                                    is_live=is_live
                                )

                                if btc_order_id and stc_order_id:
                                    # Since they are market orders, they should fill immediately, but we can verify briefly
                                    for _ in range(3):
                                        time.sleep(2)
                                        btc_status = self.client.get_order_status(btc_order_id)
                                        stc_status = self.client.get_order_status(stc_order_id)

                                        if btc_status == "complete" and stc_status == "complete":
                                            break

                                    loss = (initial_credit - current_cost_to_close) * quantity_shares
                                    self.state[symbol]["realized_pnl"] += loss
                                    self.state[symbol]["current_stage"] = "IDLE"
                                    self.state[symbol]["active_position"] = None
                                    self.state[symbol]["hedge_position"] = None
                                    self._save_state(symbol)

                                    success_msg = f"Stop loss completed successfully for {symbol}. Realized Loss: {loss}. Resetting state to IDLE."
                                    logger.info(success_msg)
                                    self.notifier.send_notification(title="Stop Loss Complete", message=success_msg, level="INFO")
                                    return
                                else:
                                    logger.error(f"Failed to place stop loss market orders for {symbol}.")
                                    return

                logger.info("Holding position...")
                return

            # Expiration Day Logic (Index Options Cash Settled)
            # Both legs are cash-settled against closing price, no physical assignment.
            hedge_position = self.state[symbol].get("hedge_position")
            short_entry_price = active_position.get("entry_price", 0.0)
            long_entry_price = hedge_position.get("entry_price", 0.0) if hedge_position else 0.0
            initial_credit = short_entry_price - long_entry_price

            short_strike = active_position["strike"]
            long_strike = hedge_position["strike"] if hedge_position else 0.0

            # Calculate settlement payout for the spread at expiration
            short_payout = max(0.0, short_strike - spot_price) * -1
            long_payout = max(0.0, long_strike - spot_price)

            settlement_value = short_payout + long_payout

            total_profit = (initial_credit + settlement_value) * quantity_shares

            self.state[symbol]["realized_pnl"] += total_profit
            self.state[symbol]["current_stage"] = "IDLE"
            self.state[symbol]["active_position"] = None
            self.state[symbol]["hedge_position"] = None

            msg = f"Spread cash-settled on expiration for {symbol}. Spot: {spot_price}, Initial Credit: {initial_credit:.2f}, Settlement: {settlement_value:.2f}. Total Profit: {total_profit}. New realized PnL: {self.state[symbol]['realized_pnl']}"
            logger.info(msg)
            self.notifier.send_notification(title="Spread Cash Settled", message=msg, level="INFO")

            self._save_state(symbol)


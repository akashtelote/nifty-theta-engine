import time
import json
import os
from filelock import FileLock, Timeout
import logging
from datetime import datetime, date
import polars as pl
from core.client import UpstoxClient
from core.notifier import Notifier

logger = logging.getLogger(__name__)

class WheelStateMachine:
    def __init__(self):
        """
        Initializes the Wheel Strategy State Machine.
        Safely loads or creates the data/wheel_state.json file to prevent
        race conditions during concurrent/daily executions.
        """
        self.state_file = "data/wheel_state.json"
        self.lock_file = "data/wheel_state.json.lock"

        # Ensure data directory exists
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)

        self.state = self._load_state()
        self.client = UpstoxClient()
        self.notifier = Notifier()

    def _load_state(self) -> dict:
        """
        Safely loads state from the JSON file using FileLock.
        If the file doesn't exist, initializes an empty state {}.
        """
        try:
            with FileLock(self.lock_file, timeout=10):
                if not os.path.exists(self.state_file):
                    logger.info(f"State file {self.state_file} not found. Initializing empty state.")
                    state = {}
                    with open(self.state_file, 'w') as f:
                        json.dump(state, f, indent=4)
                    return state

                with open(self.state_file, 'r') as f:
                    try:
                        return json.load(f)
                    except json.JSONDecodeError:
                        logger.error(f"State file {self.state_file} is corrupted. Re-initializing empty state.")
                        state = {}
                        with open(self.state_file, 'w') as f:
                            json.dump(state, f, indent=4)
                        return state
        except Timeout:
            logger.error("Timeout acquiring lock for wheel state file.")
            return {}

    def _save_state(self):
        """
        Safely saves the current state to the JSON file using FileLock.
        """
        try:
            with FileLock(self.lock_file, timeout=10):
                with open(self.state_file, 'w') as f:
                    json.dump(self.state, f, indent=4)
        except Timeout:
            logger.error("Timeout acquiring lock to save wheel state file.")

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
            self._save_state()

    def _select_target_call(self, chain_df: pl.DataFrame, spot_price: float, cost_basis: float, otm_pct: float = 0.05, min_days: int = 10, max_days: int = 42) -> dict | None:
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

        target_strike = max(spot_price * (1 + otm_pct), cost_basis)

        df = df.with_columns([
            (pl.col("strike") - target_strike).abs().alias("strike_diff")
        ])

        df = df.sort("strike_diff")

        if df.is_empty():
            return None

        return df.row(0, named=True)

    def _select_target_put(self, chain_df: pl.DataFrame, spot_price: float, otm_pct: float = 0.10, min_days: int = 10, max_days: int = 42) -> dict | None:
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

        target_strike = spot_price * (1 - otm_pct)

        # Find closest strike
        df = df.with_columns([
            (pl.col("strike") - target_strike).abs().alias("strike_diff")
        ])

        df = df.sort("strike_diff")

        if df.is_empty():
            return None

        return df.row(0, named=True)

    def execute_daily_cycle(self, symbol: str, quantity_shares: int, is_live: bool = False):
        # Reload state using FileLock before proceeding
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

            # Since place_order takes a symbol and looks up its instrument token (the underlying's instrument token),
            # but we want to trade the option contract, we need to bypass place_order or create a new method for placing order by instrument key.
            # I will modify client.py to accept an instrument_key or add a new method in client.py.

            # Let's check place_order in core/client.py. It has:
            # "instrument_token": self._get_instrument_token(symbol),
            # We want to send `instrument_key` of the option.

            # Since I am updating wheel_strategy, I'll call place_order_by_key instead.

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
                    "order_id": order_id
                }
                self._save_state()
            else:
                logger.error("Failed to place order.")

        elif current_stage == "STAGE_1_CSP":
            logger.info(f"Executing daily cycle for {symbol} in STAGE_1_CSP state.")
            active_position = self.state[symbol].get("active_position")
            if not active_position:
                logger.error(f"Active position missing for {symbol} in STAGE_1_CSP state. Resetting to IDLE.")
                self.state[symbol]["current_stage"] = "IDLE"
                self._save_state()
                return

            expiry_str = active_position.get("expiry")
            try:
                expiry_date = datetime.strptime(expiry_str, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                logger.error(f"Invalid expiry date format for {symbol}: {expiry_str}")
                return

            if expiry_date != date.today():
                logger.info("Holding position, expiry is not today.")
                return

            spot_price = self.client.get_market_quote_ltp(symbol)
            if spot_price is None:
                msg = f"Failed to fetch LTP for {symbol} on expiry day. Aborting daily cycle."
                logger.warning(msg)
                self.notifier.send_notification(title="LTP Fetch Failed", message=msg, level="WARNING")
                return

            strike = active_position["strike"]
            entry_price = active_position["entry_price"]

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

            self._save_state()

        elif current_stage == "STAGE_2_CC":
            logger.info(f"Executing daily cycle for {symbol} in STAGE_2_CC state.")
            active_position = self.state[symbol].get("active_position")

            if active_position is not None:
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

                self._save_state()
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
                    "order_id": order_id
                }
                self._save_state()
            else:
                logger.error("Failed to place call order.")

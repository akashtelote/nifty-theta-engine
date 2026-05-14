import logging
import os
import json
import requests
import time
import gzip
import io
import polars as pl
from filelock import FileLock, Timeout

from core.auth import authenticate_and_save_token

logger = logging.getLogger(__name__)

def fetch_data_safe(func, *args, **kwargs):
    """
    Wraps API calls in try-except blocks to catch timeouts and return None
    instead of hanging the bot.
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        logger.warning(f"Error or timeout during API call {func.__name__}: {e}")
        return None

class UpstoxClient:
    def __init__(self):
        """
        Initializes the Upstox API client by loading the access token.
        If the token file is missing or invalid, it triggers authentication.
        """
        self.access_token = None
        token_file = "data/token.json"

        try:
            if os.path.exists(token_file):
                with open(token_file, "r") as f:
                    token_data = json.load(f)
                    self.access_token = token_data.get("access_token")

            if not self.access_token:
                logger.info("Access token missing or invalid. Triggering authentication.")
                self.access_token = authenticate_and_save_token(force_refresh=False)

        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to read token file: {e}. Triggering authentication.")
            self.access_token = authenticate_and_save_token(force_refresh=False)

    def _get_instrument_token(self, symbol: str) -> str | None:
        """
        Looks up the real instrument token from the Upstox NSE equities master file.
        Caches the file locally for 24 hours.
        """
        csv_path = "data/nse_fo_instruments.csv"
        lock_path = "data/nse_fo_instruments.csv.lock"
        url = "https://assets.upstox.com/market-quote/instruments/exchange/NSE_FO.csv.gz"

        # Check if file exists and is less than 24 hours old
        is_stale = True
        if os.path.exists(csv_path):
            file_age = time.time() - os.path.getmtime(csv_path)
            if file_age < 86400:  # 24 hours in seconds
                is_stale = False

        if is_stale:
            try:
                # Use file lock to prevent race conditions during download
                with FileLock(lock_path, timeout=10):
                    # Recheck staleness inside lock in case another process just updated it
                    if os.path.exists(csv_path):
                        file_age = time.time() - os.path.getmtime(csv_path)
                        if file_age < 86400:
                            is_stale = False

                    if is_stale:
                        logger.info("Downloading Upstox NSE F&O instruments master file...")
                        response = requests.get(url, timeout=15)
                        response.raise_for_status()

                        # Decompress and save
                        with gzip.GzipFile(fileobj=io.BytesIO(response.content)) as gz:
                            with open(csv_path, 'wb') as f:
                                f.write(gz.read())
                        logger.info("Successfully downloaded and saved nse_fo_instruments.csv")
            except Timeout:
                logger.warning("Timeout acquiring lock for nse_fo_instruments.csv. Will try to use existing file if available.")
            except Exception as e:
                logger.error(f"Failed to download or save NSE F&O instruments file: {e}")
                if not os.path.exists(csv_path):
                    return None

        if not os.path.exists(csv_path):
            logger.error("NSE F&O instruments file not found and could not be downloaded.")
            return None

        try:
            # Read CSV and standardize
            df = pl.read_csv(csv_path)

            # Clean column names
            df = df.rename({col: col.strip().lower() for col in df.columns})

            # Look up the symbol
            filtered_df = df.filter(pl.col("tradingsymbol") == symbol)
            if filtered_df.height == 0:
                logger.error(f"Symbol '{symbol}' not found in instruments master.")
                return None

            instrument_key = str(filtered_df.select("instrument_key").item())
            return instrument_key

        except Exception as e:
            logger.error(f"Error parsing or reading NSE instruments file: {e}")
            return None

    def place_order(self, symbol: str, side: str, quantity: int, price: float, is_live: bool = False):
        """
        Places an order or routes a paper trade.
        """
        if not is_live:
            logger.info(f"Successfully routed PAPER trade: {side} {quantity} {symbol} @ ₹{price}")
            return "PAPER_ORDER_123"

        url = "https://api.upstox.com/v2/order/place"

        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }

        payload = {
            "quantity": quantity,
            "product": "D",
            "validity": "DAY",
            "price": price,
            "trigger_price": 0.0,
            "instrument_token": self._get_instrument_token(symbol),
            "order_type": "LIMIT",
            "transaction_type": side.upper()
        }

        logger.info(f"DEBUG - Token snippet: {str(self.access_token)[:15]}...")
        logger.info(f"DEBUG - Auth Header: {headers.get('Authorization')}")

        try:
            response = requests.post(url, headers=headers, json=payload)
            if response.status_code != 200:
                logger.error(f"Upstox API Error: {response.text}")
                return None

            data = response.json()
            return data.get("data", {}).get("order_id")

        except Exception as e:
            logger.error(f"Exception during live order placement: {e}")
            return None

    def get_option_chain(self, symbol: str, expiry_date: str = None) -> pl.DataFrame:
        """
        Fetches the option chain for a given symbol and optional expiry date.
        Returns a flattened Polars DataFrame with columns:
        instrument_key, type, strike, expiry, bid, ask, last_price
        """
        schema = {
            "instrument_key": pl.Utf8,
            "type": pl.Utf8,
            "strike": pl.Float64,
            "expiry": pl.Utf8,
            "bid": pl.Float64,
            "ask": pl.Float64,
            "last_price": pl.Float64
        }

        instrument_key = self._get_instrument_token(symbol)
        if not instrument_key:
            logger.error(f"Could not find instrument key for {symbol}")
            return pl.DataFrame(schema=schema)

        url = "https://api.upstox.com/v2/option/chain"
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Accept': 'application/json'
        }
        params = {
            "instrument_key": instrument_key
        }
        if expiry_date:
            params["expiry_date"] = expiry_date

        response = fetch_data_safe(requests.get, url, headers=headers, params=params, timeout=10)

        if not response:
            return pl.DataFrame(schema=schema)

        if response.status_code != 200:
            logger.error(f"Upstox API Error fetching option chain: {response.text}")
            return pl.DataFrame(schema=schema)

        data = response.json().get("data", [])

        flattened_data = []
        for item in data:
            strike_price = item.get("strike_price")
            expiry = item.get("expiry")

            # Extract Call Options
            if "call_options" in item:
                ce = item["call_options"]
                ce_market_data = ce.get("market_data", {})
                flattened_data.append({
                    "instrument_key": ce.get("instrument_key"),
                    "type": "CE",
                    "strike": strike_price,
                    "expiry": expiry,
                    "bid": ce_market_data.get("bid_price"),
                    "ask": ce_market_data.get("ask_price"),
                    "last_price": ce_market_data.get("ltp")
                })

            # Extract Put Options
            if "put_options" in item:
                pe = item["put_options"]
                pe_market_data = pe.get("market_data", {})
                flattened_data.append({
                    "instrument_key": pe.get("instrument_key"),
                    "type": "PE",
                    "strike": strike_price,
                    "expiry": expiry,
                    "bid": pe_market_data.get("bid_price"),
                    "ask": pe_market_data.get("ask_price"),
                    "last_price": pe_market_data.get("ltp")
                })

        # Ensure return is a DataFrame with expected columns even if empty
        if not flattened_data:
            return pl.DataFrame(schema=schema)

        df = pl.DataFrame(flattened_data)

        # Ensure correct types
        df = df.cast({
            "instrument_key": pl.Utf8,
            "type": pl.Utf8,
            "strike": pl.Float64,
            "expiry": pl.Utf8,
            "bid": pl.Float64,
            "ask": pl.Float64,
            "last_price": pl.Float64
        })

        return df

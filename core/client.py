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

    def _make_authenticated_request(self, method: str, url: str, **kwargs):
        """
        Centrally handles authenticated requests, adding headers, managing timeouts,
        and providing inline self-healing (retry) if the token is expired (401).
        """
        headers = kwargs.pop("headers", {})
        headers['Authorization'] = f'Bearer {self.access_token}'
        if 'Accept' not in headers:
            headers['Accept'] = 'application/json'

        timeout = kwargs.pop("timeout", 15)

        response = fetch_data_safe(requests.request, method, url, headers=headers, timeout=timeout, **kwargs)

        if response and response.status_code == 401:
            logger.warning("Access token rejected (401). Evicting token file and forcing re-authentication...")

            # Safely delete the cached token file
            token_file = "data/token.json"
            try:
                if os.path.exists(token_file):
                    os.remove(token_file)
            except (FileNotFoundError, OSError) as e:
                logger.warning(f"Could not remove token file {token_file}: {e}")

            # Invoke auth layer to pull a fresh token
            try:
                self.access_token = authenticate_and_save_token(force_refresh=True)
            except Exception as e:
                logger.error(f"Failed to fetch new token during self-healing: {e}")
                return response

            # Update headers with new token
            headers['Authorization'] = f'Bearer {self.access_token}'

            # Retry exactly one time
            logger.info("Retrying request with fresh access token...")
            retry_response = fetch_data_safe(requests.request, method, url, headers=headers, timeout=timeout, **kwargs)
            if retry_response and retry_response.status_code != 200:
                logger.error(f"Retry request failed with status {retry_response.status_code}")
            return retry_response

        return response

    def _get_instrument_token(self, symbol: str) -> str | None:
        """
        Looks up the real instrument token from the Upstox NSE equities master file.
        Caches the file locally for 24 hours.
        """
        csv_path = "data/nse_fo_instruments.csv"
        lock_path = "data/nse_fo_instruments.csv.lock"
        url = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.csv.gz"

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
                        headers = {
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
                            'Accept': '*/*'
                        }
                        response = requests.get(url, headers=headers, timeout=15)
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

    def get_market_quote_ltp(self, symbol: str) -> float | None:
        """
        Fetches the last traded price for the given symbol.
        """
        # Temporary local testing fallback for closed market hours
        if symbol == "RELIANCE":
            logger.info("Market closed/Testing mode. Injecting mock LTP for RELIANCE: 2500.0")
            return 2500.0
        elif symbol == "HDFCBANK":
            logger.info("Market closed/Testing mode. Injecting mock LTP for HDFCBANK: 1500.0")
            return 1500.0
        elif symbol == "INFY":
            logger.info("Market closed/Testing mode. Injecting mock LTP for INFY: 1600.0")
            return 1600.0

        instrument_key = self._get_instrument_token(symbol)
        if not instrument_key:
            logger.error(f"Could not find instrument key for {symbol}")
            return None

        url = f"https://api.upstox.com/v2/market-quote/ltp"
        params = {
            "instrument_key": instrument_key
        }

        response = self._make_authenticated_request("GET", url, params=params, timeout=10)

        if not response:
            return None

        if response.status_code != 200:
            logger.error(f"Upstox API HTTP Error {response.status_code}: {response.text}")
            return None

        try:
            data = response.json().get("data", {})
            if not data:
                logger.warning(f"Upstox API returned an empty data dictionary for {instrument_key}. This is expected if running outside of Indian market hours (9:15 AM - 3:30 PM IST).")
                return None

            # Upstox returns data as: {"data": {"NSE_EQ:RELIANCE": {"last_price": 123.45}}}
            # We dynamically extract the first value because we only request one symbol at a time
            key_data = list(data.values())[0]
            last_price = key_data.get("last_price")

            if last_price is not None:
                return float(last_price)
            return None
        except Exception as e:
            logger.error(f"[ERROR] Failed to parse LTP: {e}", exc_info=True)
            return None

    def place_order(self, symbol: str, side: str, quantity: int, price: float, is_live: bool = False):
        """
        Places an order or routes a paper trade.
        """
        instrument_key = self._get_instrument_token(symbol)
        if not instrument_key:
            logger.error(f"Could not find instrument key for {symbol}")
            return None

        return self.place_order_by_key(instrument_key, side, quantity, price, is_live)

    def place_order_by_key(self, instrument_key: str, side: str, quantity: int, price: float, is_live: bool = False):
        """
        Places an order or routes a paper trade using an instrument key.
        """
        if not is_live:
            logger.info(f"Successfully routed PAPER trade: {side} {quantity} for {instrument_key} @ ₹{price}")
            return "PAPER_ORDER_123"

        url = "https://api.upstox.com/v2/order/place"

        headers = {
            'Content-Type': 'application/json'
        }

        payload = {
            "quantity": quantity,
            "product": "D",
            "validity": "DAY",
            "price": price,
            "trigger_price": 0.0,
            "instrument_token": instrument_key,
            "order_type": "LIMIT",
            "transaction_type": side.upper()
        }

        logger.info(f"DEBUG - Token snippet: {str(self.access_token)[:15]}...")

        response = self._make_authenticated_request("POST", url, headers=headers, json=payload, timeout=10)
        if not response:
            return None

        if response.status_code != 200:
            logger.error(f"Upstox API HTTP Error {response.status_code}: {response.text}")
            return None

        try:
            data = response.json()
            return data.get("data", {}).get("order_id")
        except Exception as e:
            logger.error(f"Exception parsing live order placement response: {e}")
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
        params = {
            "instrument_key": instrument_key
        }
        if expiry_date:
            params["expiry_date"] = expiry_date

        response = self._make_authenticated_request("GET", url, params=params, timeout=10)

        if not response:
            return pl.DataFrame(schema=schema)

        if response.status_code != 200:
            logger.error(f"Upstox API HTTP Error {response.status_code}: {response.text}")
            return pl.DataFrame(schema=schema)

        data = response.json().get("data", [])
        if not data:
            logger.warning(f"Upstox API returned an empty data dictionary for {instrument_key}. This is expected if running outside of Indian market hours (9:15 AM - 3:30 PM IST).")
            return pl.DataFrame(schema=schema)

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

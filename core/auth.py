import os
import json
import logging
from datetime import datetime, timezone
from filelock import FileLock
from upstox_totp.client import UpstoxTOTP
from dotenv import load_dotenv
from config.settings import get_redis_client

logger = logging.getLogger(__name__)

TOKEN_FILE = "data/token.json"
LOCK_FILE = "data/token.json.lock"

# Shared Redis key with trading_bot
REDIS_TOKEN_KEY = "upstox:active_token"
# Match trading_bot TTL (24h) so stale tokens expire from the bus
REDIS_TOKEN_TTL_SECONDS = 86400

# 12 hours in seconds
TOKEN_MAX_AGE_SECONDS = 12 * 3600
# 5 minutes in seconds — anti OTP-spam guard
TOKEN_FORCE_REFRESH_GUARD_SECONDS = 300


def get_current_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_centralized_token() -> str | None:
    """Fetch the active token from the shared Redis bus."""
    try:
        r = get_redis_client()
        token = r.get(REDIS_TOKEN_KEY)
        return token or None
    except Exception as e:
        logger.error(f"Failed to connect to Redis or fetch token: {e}")
        return None


def _delete_centralized_token() -> None:
    """Delete the active token from the shared Redis bus."""
    try:
        r = get_redis_client()
        r.delete(REDIS_TOKEN_KEY)
    except Exception as e:
        logger.error(f"Failed to connect to Redis or delete token: {e}")


def _save_centralized_token(token: str) -> None:
    """Publish token to the shared Redis bus with TTL."""
    try:
        r = get_redis_client()
        r.set(REDIS_TOKEN_KEY, token, ex=REDIS_TOKEN_TTL_SECONDS)
    except Exception as e:
        logger.error(f"Failed to connect to Redis or save token: {e}")


def _mirror_token_locally(token: str, created_at: str | None = None) -> None:
    """Keep local token.json in sync with the shared bus."""
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    token_data = {
        "access_token": token,
        "created_at": created_at or get_current_timestamp(),
    }
    with open(TOKEN_FILE, "w") as f:
        json.dump(token_data, f, indent=4)


def _read_local_token() -> tuple[str | None, datetime | None]:
    if not os.path.exists(TOKEN_FILE):
        return None, None
    try:
        with open(TOKEN_FILE, "r") as f:
            data = json.load(f)
        access_token = data.get("access_token")
        created_at_str = data.get("created_at")
        created_at = datetime.fromisoformat(created_at_str) if created_at_str else None
        return access_token, created_at
    except Exception as e:
        logger.error(f"Error reading token file: {e}")
        return None, None


def authenticate_and_save_token(force_refresh: bool = False) -> str:
    """
    Resolve an Upstox access token in priority order:
      1. Shared Redis bus (upstox:active_token) — preferred, does not kill other sessions
      2. Local token.json if still within age / anti-spam window (also re-published to Redis)
      3. TOTP login fallback — last resort; invalidates other Upstox sessions

    Validity of a Redis/local token is proven by API use; 401 self-heal in the client
    triggers force_refresh only after Redis has been tried and found dead.
    """
    load_dotenv()

    if not force_refresh:
        centralized_token = get_centralized_token()
        if centralized_token:
            logger.info("Using Upstox token from Redis bus.")
            try:
                _mirror_token_locally(centralized_token)
            except Exception as e:
                logger.warning(f"Could not mirror Redis token to local file: {e}")
            return centralized_token

    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    lock = FileLock(LOCK_FILE)

    with lock:
        # Another process may have refreshed Redis while we waited for the lock
        if not force_refresh:
            centralized_token = get_centralized_token()
            if centralized_token:
                logger.info("Using Upstox token from Redis bus (post-lock).")
                _mirror_token_locally(centralized_token)
                return centralized_token

        current_time = datetime.now(timezone.utc)
        access_token, created_at = _read_local_token()

        if access_token and created_at:
            age_seconds = (current_time - created_at).total_seconds()

            if age_seconds < TOKEN_FORCE_REFRESH_GUARD_SECONDS:
                logger.warning(
                    f"Token is very new ({age_seconds:.1f}s old). "
                    "Prevented OTP spam; reusing local token and publishing to Redis."
                )
                _save_centralized_token(access_token)
                return access_token

            if not force_refresh and age_seconds < TOKEN_MAX_AGE_SECONDS:
                logger.info(
                    "Using existing local token (less than 12 hours old); publishing to Redis."
                )
                _save_centralized_token(access_token)
                return access_token

        if force_refresh:
            logger.info("force_refresh=True: clearing Redis token before TOTP login.")
            _delete_centralized_token()

        logger.critical(
            "Executing TOTP fallback login. WARNING: This will kill other active Upstox sessions!"
        )
        logger.info("Generating new Upstox token...")

        username = os.environ.get("UPSTOX_USER_ID")
        password = os.environ.get("UPSTOX_PASSWORD")
        pin_code = os.environ.get("UPSTOX_PIN_CODE")
        totp_secret = os.environ.get("UPSTOX_TOTP_SECRET")
        client_id = os.environ.get("UPSTOX_API_KEY")
        client_secret = os.environ.get("UPSTOX_API_SECRET")
        redirect_uri = os.environ.get("UPSTOX_REDIRECT_URI")

        if not all([username, password, pin_code, totp_secret, client_id, client_secret, redirect_uri]):
            logger.error("Missing required Upstox environment variables.")
            raise ValueError("Missing required Upstox environment variables.")

        try:
            client = UpstoxTOTP(
                username=username,
                password=password,
                pin_code=pin_code,
                totp_secret=totp_secret,
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
            )

            token_response = client.app_token.get_access_token()

            if not token_response.success or not token_response.data:
                raise RuntimeError(
                    f"Failed to fetch token, response not successful: {token_response.error}"
                )

            new_access_token = token_response.data.access_token
            if not new_access_token:
                raise RuntimeError(
                    f"Could not extract access token from response: {token_response.model_dump()}"
                )

            _mirror_token_locally(new_access_token, created_at=current_time.isoformat())
            _save_centralized_token(new_access_token)

            logger.info("Successfully generated and saved new token locally and to Redis.")
            return new_access_token

        except Exception as e:
            logger.error(f"Failed to authenticate with Upstox: {e}")
            raise

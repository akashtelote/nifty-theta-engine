import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from core.auth import authenticate_and_save_token
from core.smart_money import SmartMoneyFilter
from core.client import UpstoxClient
from core.scheduler import start_scheduler

# Basic logging configuration for all core modules
# Force IST (Asia/Kolkata) timezone for all standard library logging
ist = timezone(timedelta(hours=5, minutes=30))
logging.Formatter.converter = lambda *args: datetime.now(ist).timetuple()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

logger = logging.getLogger(__name__)

def run_trade(args):
    """Run a simulated paper trade or live trade."""
    logger.info(f"Initiating trade for {args.quantity} shares of {args.symbol} at ₹{args.price}...")

    client = UpstoxClient()
    order_id = client.place_order(args.symbol, args.side, args.quantity, args.price)

    if order_id:
        logger.info(f"Successfully routed trade. Order ID: {order_id}")

def main():
    parser = argparse.ArgumentParser(description="Indian Trading Bot - Unified CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")
    subparsers.required = True

    # Subcommand: auth
    auth_parser = subparsers.add_parser("auth", help="Generate or refresh the Upstox API token")

    # Subcommand: screen
    screen_parser = subparsers.add_parser("screen", help="Run the Smart Money Filter to find institutional whales")

    # Subcommand: trade
    trade_parser = subparsers.add_parser("trade", help="Run a simulated paper trade or live trade")
    trade_parser.add_argument("symbol", type=str, help="Trading symbol (e.g., Nifty 50)")
    trade_parser.add_argument("side", type=str, choices=["BUY", "SELL"], help="Order side (BUY/SELL)")
    trade_parser.add_argument("quantity", type=int, help="Quantity to trade")
    trade_parser.add_argument("price", type=float, help="Order price")

    # Subcommand: start
    start_parser = subparsers.add_parser("start", help="Start the daily scheduler")

    args = parser.parse_args()

    if args.command == "auth":
        logger.info("Executing auth command...")
        authenticate_and_save_token()
    elif args.command == "screen":
        logger.info("Executing screen command...")
        filter = SmartMoneyFilter()
        filter.process_smart_money()
    elif args.command == "trade":
        logger.info("Executing trade command...")
        run_trade(args)
    elif args.command == "start":
        logger.info("Executing start command...")
        start_scheduler()

if __name__ == "__main__":
    main()

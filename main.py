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
    if args.live:
        logger.warning("WARNING: INITIATING LIVE EXCHANGE ORDER!")
    else:
        logger.info(f"Initiating paper trade for {args.quantity} shares of {args.symbol} at ₹{args.price}...")

    client = UpstoxClient()
    order_id = client.place_order(args.symbol, args.side, args.quantity, args.price, is_live=args.live)

    if order_id:
        if args.live:
            logger.info(f"Successfully routed LIVE trade. Upstox Order ID: {order_id}")
        else:
            logger.info(f"Successfully routed PAPER trade. Mock Order ID: {order_id}")

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
    trade_parser.add_argument("symbol", type=str, help="Trading symbol (e.g., RELIANCE)")
    trade_parser.add_argument("side", type=str, choices=["BUY", "SELL"], help="Order side (BUY/SELL)")
    trade_parser.add_argument("quantity", type=int, help="Quantity to trade")
    trade_parser.add_argument("price", type=float, help="Order price")
    trade_parser.add_argument("--live", action="store_true", help="Execute a REAL trade on the Upstox exchange")

    # Subcommand: start
    start_parser = subparsers.add_parser("start", help="Start the daily scheduler")
    start_parser.add_argument("--live", action="store_true", help="Run the scheduled bot in REAL live trading mode")

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
        start_scheduler(args.live)

if __name__ == "__main__":
    main()

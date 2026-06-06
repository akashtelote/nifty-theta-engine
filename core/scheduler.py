import logging
import time
import pytz
import os
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from strategies.wheel_strategy import WheelStateMachine
from core.notifier import Notifier

logger = logging.getLogger(__name__)

HEARTBEAT_URL = os.getenv("HEARTBEAT_URL")

TARGET_SYMBOLS = {
    "Nifty 50": {"allocation_pct": 1.0} # Budget constraint is now hardcoded in strategy
}

LOT_SIZES = {
    "Nifty 50": 25
}

def _run_daily_wheel():
    logger.info("Starting daily wheel execution.")
    wheel = WheelStateMachine()
    notifier = Notifier()

    for symbol, symbol_config in TARGET_SYMBOLS.items():
        try:
            logger.info(f"Processing symbol: {symbol} with config: {symbol_config}")
            wheel.execute_daily_cycle(symbol=symbol, symbol_config=symbol_config, quantity_shares=LOT_SIZES.get(symbol, 25))
        except Exception as e:
            logger.error(f"Error processing {symbol}: {e}", exc_info=True)
            notifier.send_notification(
                title="Critical Daily Wheel Error",
                message=f"CRITICAL ERROR in Wheel Bot for {symbol}: {e}",
                level="ERROR"
            )

    logger.info("Daily wheel execution completed.")

    if HEARTBEAT_URL:
        try:
            requests.get(HEARTBEAT_URL, timeout=5)
        except Exception as e:
            logger.warning(f"Failed to send heartbeat ping: {e}")

def _run_exits():
    logger.info("Starting exit evaluation.")
    wheel = WheelStateMachine()
    notifier = Notifier()

    try:
        wheel.check_exits()
    except Exception as e:
        logger.error(f"Error checking exits: {e}", exc_info=True)
        notifier.send_notification(
            title="Critical Exit Manager Error",
            message=f"CRITICAL ERROR in Exit Manager: {e}",
            level="ERROR"
        )

    logger.info("Exit evaluation completed.")

def start_scheduler():
    tz = pytz.timezone('Asia/Kolkata')
    scheduler = BackgroundScheduler(timezone=tz)

    # Entry Trigger: Friday 15:15
    entry_trigger = CronTrigger(
        day_of_week='fri',
        hour=15,
        minute=15,
        timezone=tz
    )

    scheduler.add_job(
        _run_daily_wheel,
        trigger=entry_trigger
    )

    # Exit Trigger: Hourly during market hours (9:00 - 15:00) Monday - Friday
    exit_trigger = CronTrigger(
        day_of_week='mon-fri',
        hour='9-15',
        minute=0,
        timezone=tz
    )

    scheduler.add_job(
        _run_exits,
        trigger=exit_trigger
    )

    logger.info("Scheduler initialized. Bot is standing by for execution and exits.")
    scheduler.start()

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received. Shutting down scheduler.")
        scheduler.shutdown()

import logging
import time
import pytz
import os
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from strategies.wheel_strategy import WheelStateMachine
from core.notifier import Notifier
from ml.vix_pipeline import run_weekend_training

logger = logging.getLogger(__name__)

HEARTBEAT_URL = os.getenv("HEARTBEAT_URL")

TARGET_SYMBOLS = {
    "NSE_INDEX|Nifty 50": {"allocation_pct": 1.0} # Budget constraint is now hardcoded in strategy
}

LOT_SIZES = {
    "NSE_INDEX|Nifty 50": 25
}

def _run_daily_wheel(is_live: bool = False):
    logger.info(f"Starting daily wheel execution. (Live Mode: {is_live})")
    wheel = WheelStateMachine()
    notifier = Notifier()

    for symbol, symbol_config in TARGET_SYMBOLS.items():
        try:
            logger.info(f"Processing symbol: {symbol} with config: {symbol_config}")
            wheel.execute_daily_cycle(symbol=symbol, symbol_config=symbol_config, quantity_shares=LOT_SIZES.get(symbol, 25), is_live=is_live)
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

def _scheduled_ml_retraining():
    logger.info("Initiating Weekend ML Compute Window: Retraining VIX Predictive Model.")
    try:
        run_weekend_training()
        logger.info("Weekend ML Compute Window completed successfully.")
    except Exception as e:
        logger.error(f"Failed during Weekend ML Retraining: {e}", exc_info=True)

def start_scheduler(is_live: bool = False):
    tz = pytz.timezone('Asia/Kolkata')
    scheduler = BackgroundScheduler(timezone=tz)

    trigger = CronTrigger(
        day_of_week='fri',
        hour=15,
        minute=15,
        timezone=tz
    )

    scheduler.add_job(
        _run_daily_wheel,
        trigger=trigger,
        args=[is_live]
    )

    ml_trigger = CronTrigger(
        day_of_week='sat',
        hour=2,
        minute=0,
        timezone=tz
    )

    scheduler.add_job(
        _scheduled_ml_retraining,
        trigger=ml_trigger,
        misfire_grace_time=3600
    )

    logger.info(f"Scheduler initialized. Bot is standing by for the 15:15 IST execution. (Live Mode: {is_live})")
    scheduler.start()

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received. Shutting down scheduler.")
        scheduler.shutdown()

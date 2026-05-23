import logging
import time
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from strategies.wheel_strategy import WheelStateMachine
from core.notifier import Notifier

logger = logging.getLogger(__name__)

TARGET_SYMBOLS = {
    "RELIANCE": {"allocation_pct": 0.15},
    "HDFCBANK": {"allocation_pct": 0.15},
    "INFY": {"allocation_pct": 0.10}
}

def _run_daily_wheel(is_live: bool = False):
    logger.info(f"Starting daily wheel execution. (Live Mode: {is_live})")
    wheel = WheelStateMachine()
    notifier = Notifier()

    for symbol, symbol_config in TARGET_SYMBOLS.items():
        try:
            logger.info(f"Processing symbol: {symbol} with config: {symbol_config}")
            wheel.execute_daily_cycle(symbol=symbol, symbol_config=symbol_config, is_live=is_live)
        except Exception as e:
            logger.error(f"Error processing {symbol}: {e}", exc_info=True)
            notifier.send_notification(
                title="Critical Daily Wheel Error",
                message=f"CRITICAL ERROR in Wheel Bot for {symbol}: {e}",
                level="ERROR"
            )

    logger.info("Daily wheel execution completed.")

def start_scheduler(is_live: bool = False):
    tz = pytz.timezone('Asia/Kolkata')
    scheduler = BackgroundScheduler(timezone=tz)

    trigger = CronTrigger(
        day_of_week='mon-fri',
        hour=15,
        minute=15,
        timezone=tz
    )

    scheduler.add_job(
        _run_daily_wheel,
        trigger=trigger,
        args=[is_live]
    )

    logger.info(f"Scheduler initialized. Bot is standing by for the 15:15 IST execution. (Live Mode: {is_live})")
    scheduler.start()

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received. Shutting down scheduler.")
        scheduler.shutdown()

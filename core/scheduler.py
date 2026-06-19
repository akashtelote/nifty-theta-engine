import logging
import time
import pytz
import os
import requests
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from strategies.wheel_strategy import WheelStateMachine
from core.notifier import Notifier
from config.settings import LOT_SIZES, settings

logger = logging.getLogger(__name__)

HEARTBEAT_URL = os.getenv("HEARTBEAT_URL")

TARGET_SYMBOLS = {
    "Nifty 50": {"allocation_pct": 1.0}
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

def _check_missed_entry():
    tz = pytz.timezone('Asia/Kolkata')
    now = datetime.now(tz)
    if now.weekday() != 4:
        return
    if now.hour < 15 or (now.hour == 15 and now.minute < 15):
        return
    logger.info("Startup detected on Friday after 15:15 IST. Checking for missed weekly entry...")
    wheel = WheelStateMachine()
    for symbol, data in wheel.state.items():
        if data.get("current_stage") in ("IDLE", "CLOSED"):
            logger.info(f"Symbol {symbol} is IDLE/CLOSED on Friday — running missed entry.")
            _run_daily_wheel()
            return
    logger.info("No missed entries detected — all symbols have active positions.")

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

    # Reconcile broker positions against DB state
    try:
        wheel = WheelStateMachine()
        wheel.reconcile_positions()
    except Exception as e:
        logger.error(f"Position reconciliation failed: {e}", exc_info=True)

    _check_missed_entry()

    # Start WebSocket monitor for real-time exit checks (live mode only)
    ws_monitor = None
    if not settings.PAPER_TRADE and not settings.MOCK_MARKET:
        try:
            from core.ws_monitor import WebSocketMonitor
            from core.auth import get_centralized_token

            token = get_centralized_token()
            if token:
                def _on_ltp_update(instrument_key: str, ltp: float):
                    logger.debug(f"Real-time LTP: {instrument_key} = {ltp}")

                ws_monitor = WebSocketMonitor(access_token=token, on_exit_trigger=_on_ltp_update)
                ws_monitor.start()
                logger.info("Real-time WebSocket monitor active.")
            else:
                logger.warning("No token available for WebSocket monitor. Falling back to hourly polling.")
        except Exception as e:
            logger.warning(f"Could not start WebSocket monitor: {e}. Falling back to hourly polling.")

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received. Shutting down scheduler.")
        if ws_monitor:
            ws_monitor.stop()
        scheduler.shutdown()

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

_ws_wheel: WheelStateMachine | None = None
_ws_monitor = None
_ws_fallback_alerted = False


def _notify_ws_fallback(reason: str, notifier: Notifier | None = None) -> None:
    """Discord WARNING on WS fallback; one alert per failure episode."""
    global _ws_fallback_alerted
    logger.warning(reason)
    if _ws_fallback_alerted:
        return
    _ws_fallback_alerted = True
    n = notifier or Notifier()
    n.send_notification(
        title="WebSocket Monitor Offline",
        message=f"{reason} Falling back to hourly exit polling.",
        level="WARNING",
    )


def _on_ws_runtime_error(error) -> None:
    """Callback when the live streamer errors — alert once, keep hourly poll."""
    _notify_ws_fallback(f"WebSocket monitor error: {error}.")


def _start_ws_monitor() -> bool:
    """Start real-time exit monitor when market data is available.

    Runs in live and paper modes. Skipped for MOCK_MARKET (no real quotes).
    Paper orders remain PAPER_* via the client; this only enables tick-driven exits.
    Returns True if the monitor started successfully.
    """
    global _ws_wheel, _ws_monitor, _ws_fallback_alerted

    if settings.MOCK_MARKET:
        logger.info("MOCK_MARKET enabled — skipping WebSocket monitor (hourly exits only).")
        return False

    try:
        from core.ws_monitor import WebSocketMonitor
        from core.auth import get_centralized_token

        token = get_centralized_token()
        if not token:
            _notify_ws_fallback("No token available for WebSocket monitor.")
            return False

        _ws_wheel = WheelStateMachine()
        _ws_wheel.refresh_exit_thresholds()

        _ws_monitor = WebSocketMonitor(
            access_token=token,
            on_tick=_ws_wheel.on_realtime_tick,
            on_error=_on_ws_runtime_error,
        )
        _ws_monitor.start()
        _ws_monitor.update_subscriptions(_ws_wheel.active_instrument_keys())
        _ws_fallback_alerted = False
        logger.info(
            "Real-time WebSocket monitor active with exit thresholds "
            f"(paper_trade={settings.PAPER_TRADE})."
        )
        return True
    except Exception as e:
        _notify_ws_fallback(f"Could not start WebSocket monitor: {e}.")
        return False


def _refresh_realtime_state():
    """Refresh the WS monitor's thresholds and subscriptions after position changes."""
    if _ws_wheel is None or _ws_monitor is None:
        return
    try:
        _ws_wheel.state = _ws_wheel._load_state()
        _ws_wheel.refresh_exit_thresholds()
        _ws_monitor.update_subscriptions(_ws_wheel.active_instrument_keys())
    except Exception as e:
        logger.error(f"Failed to refresh real-time state: {e}", exc_info=True)


def _run_daily_wheel(entry_session: str = "friday"):
    logger.info(f"Starting daily wheel execution (entry_session={entry_session}).")
    wheel = WheelStateMachine()
    notifier = Notifier()

    for symbol, base_config in TARGET_SYMBOLS.items():
        symbol_config = {**base_config, "entry_session": entry_session}
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
    _refresh_realtime_state()

    if HEARTBEAT_URL:
        try:
            requests.get(HEARTBEAT_URL, timeout=5)
        except Exception as e:
            logger.warning(f"Failed to send heartbeat ping: {e}")


def _run_midweek_wheel():
    """Optional mid-week entry path (PROF-011); no-op unless ALLOW_MIDWEEK_ENTRY."""
    if not settings.ALLOW_MIDWEEK_ENTRY:
        logger.debug("ALLOW_MIDWEEK_ENTRY=False — skipping mid-week entry job.")
        return
    _run_daily_wheel(entry_session="midweek")

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

    try:
        wheel.try_same_week_reentry()
    except Exception as e:
        logger.error(f"Same-week re-entry failed: {e}", exc_info=True)

    logger.info("Exit evaluation completed.")
    _refresh_realtime_state()

def _check_missed_entry():
    """Catch missed Friday (and optional mid-week) entries after restart; never double-enter."""
    tz = pytz.timezone('Asia/Kolkata')
    now = datetime.now(tz)
    entry_hour = 15
    entry_minute = 15

    is_friday = now.weekday() == 4
    midweek_map = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4}
    midweek_days = {
        midweek_map[d.strip().lower()]
        for d in settings.MIDWEEK_ENTRY_DAYS.split(",")
        if d.strip().lower() in midweek_map
    }
    is_midweek_slot = (
        settings.ALLOW_MIDWEEK_ENTRY
        and now.weekday() in midweek_days
        and now.weekday() != 4
    )

    if not is_friday and not is_midweek_slot:
        return
    if now.hour < entry_hour or (now.hour == entry_hour and now.minute < entry_minute):
        return

    session = "friday" if is_friday else "midweek"
    logger.info(
        f"Startup detected after {entry_hour}:{entry_minute:02d} IST on {session} — checking missed entry..."
    )
    wheel = WheelStateMachine()
    for symbol, data in wheel.state.items():
        if data.get("current_stage") in ("IDLE", "CLOSED"):
            logger.info(f"Symbol {symbol} is IDLE/CLOSED — running missed {session} entry.")
            _run_daily_wheel(entry_session=session)
            return
    logger.info("No missed entries detected — all symbols have active positions.")

def start_scheduler():
    global _ws_wheel, _ws_monitor

    tz = pytz.timezone('Asia/Kolkata')
    scheduler = BackgroundScheduler(timezone=tz)

    entry_trigger = CronTrigger(
        day_of_week='fri',
        hour=15,
        minute=15,
        timezone=tz
    )

    scheduler.add_job(
        _run_daily_wheel,
        trigger=entry_trigger,
        kwargs={"entry_session": "friday"},
        id="friday_entry",
    )

    if settings.ALLOW_MIDWEEK_ENTRY:
        midweek_trigger = CronTrigger(
            day_of_week=settings.MIDWEEK_ENTRY_DAYS,
            hour=settings.MIDWEEK_ENTRY_HOUR,
            minute=settings.MIDWEEK_ENTRY_MINUTE,
            timezone=tz,
        )
        scheduler.add_job(
            _run_midweek_wheel,
            trigger=midweek_trigger,
            id="midweek_entry",
        )
        logger.info(
            f"Mid-week entry enabled: {settings.MIDWEEK_ENTRY_DAYS} "
            f"{settings.MIDWEEK_ENTRY_HOUR}:{settings.MIDWEEK_ENTRY_MINUTE:02d} IST"
        )

    exit_trigger = CronTrigger(
        day_of_week='mon-fri',
        hour='9-15',
        minute=0,
        timezone=tz
    )

    scheduler.add_job(
        _run_exits,
        trigger=exit_trigger,
        id="hourly_exits",
    )

    logger.info("Scheduler initialized. Bot is standing by for execution and exits.")
    scheduler.start()

    # Reconcile broker positions against DB state
    try:
        wheel = WheelStateMachine()
        wheel.reconcile_positions()
    except Exception as e:
        logger.error(f"Position reconciliation failed: {e}", exc_info=True)

    # Close any positions that expired while the bot was offline
    try:
        wheel = WheelStateMachine()
        wheel.check_exits()
        logger.info("Startup expiry sweep completed.")
    except Exception as e:
        logger.error(f"Startup expiry sweep failed: {e}", exc_info=True)

    _check_missed_entry()

    # Real-time exits for live and paper (skip MOCK_MARKET); hourly poll remains backstop
    _start_ws_monitor()

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received. Shutting down scheduler.")
        if _ws_monitor:
            _ws_monitor.stop()
        scheduler.shutdown()

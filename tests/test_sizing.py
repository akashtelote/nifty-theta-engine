"""Risk-based sizing (core/sizing.py) and its wiring into the paper path."""
import pytest

from core.sizing import risk_lots

W, LOT = 100.0, 65  # 1 lot max loss = (100 - credit) * 65


def lots(credit=15.0, equity=200_000.0, open_risk=0.0, risk=0.03, port=0.08):
    return risk_lots(W, credit, LOT, equity, open_risk, risk, port)


def test_one_lot_fits_at_3pct():
    # max loss/lot = 85*65 = 5525; cap = 6000
    assert lots()[0] == 1


def test_two_percent_skips_with_reason():
    n, why = lots(risk=0.02)  # cap 4000 < 5525
    assert n == 0 and "per-trade" in why


def test_boundary_exact_fit():
    # equity * 2% == max loss per lot exactly -> 1 lot
    assert risk_lots(W, 15.0, LOT, 5525 / 0.02, 0.0, 0.02, 0.08)[0] == 1
    assert risk_lots(W, 15.0, LOT, 5525 / 0.02 - 1, 0.0, 0.02, 0.08)[0] == 0


def test_scales_with_equity_and_never_exceeds_cap():
    n, _ = lots(equity=2_000_000.0, risk=0.02)  # cap 40000 -> 7 lots
    assert n == 7 and n * 5525 <= 40_000


def test_portfolio_cap_binds():
    n, why = lots(equity=2_000_000.0, risk=0.02, open_risk=150_000.0)  # portfolio 160k
    assert n == 1  # (160k-150k)/5525 = 1
    n, why = lots(equity=2_000_000.0, risk=0.02, open_risk=159_000.0)
    assert n == 0 and "portfolio" in why


def test_zero_or_negative_equity_and_bad_width():
    assert lots(equity=0)[0] == 0 and lots(equity=-5)[0] == 0
    assert risk_lots(0, 0, LOT, 1e6, 0, 0.03, 0.08)[0] == 0


def test_negative_credit_does_not_shrink_loss():
    assert lots(credit=-50.0) == lots(credit=0.0)


def test_equity_decay_shrinks_size():
    big = lots(equity=1_000_000.0, risk=0.02)[0]
    after_drawdown = lots(equity=600_000.0, risk=0.02)[0]
    assert after_drawdown < big


# ---- wiring into WheelStateMachine.execute_daily_cycle (paper mode) ----
from datetime import date, timedelta
from unittest.mock import patch

import polars as pl


def _chain():
    expiry = (date.today() + timedelta(days=20)).isoformat()
    return pl.DataFrame([
        {"instrument_key": "NSE_FO|NIFTY21700PE", "type": "PE", "strike": 21700.0,
         "expiry": expiry, "bid": 50.0, "ask": 51.0, "last_price": 50.5},
        {"instrument_key": "NSE_FO|NIFTY21600PE", "type": "PE", "strike": 21600.0,
         "expiry": expiry, "bid": 30.0, "ask": 31.0, "last_price": 30.5},
    ])


def _enter(wheel, mock_client, margin, pnl=0.0):
    mock_client.get_available_margin.return_value = margin
    mock_client.get_india_vix.return_value = 14.0
    mock_client.get_market_quote_ltp.return_value = 22000.0
    mock_client.get_option_chain.return_value = _chain()
    wheel.ensure_symbol_state("Nifty 50")
    wheel.state["Nifty 50"]["lifetime_realized_pnl"] = pnl
    with patch("time.sleep", return_value=None):
        wheel.execute_daily_cycle("Nifty 50", {"entry_session": "friday"})


def test_paper_enters_when_one_lot_fits(wheel, mock_client):
    _enter(wheel, mock_client, 200_000.0)
    assert mock_client.place_order_by_key.called


def test_paper_skips_when_cap_breached(wheel, mock_client):
    _enter(wheel, mock_client, 50_000.0)
    mock_client.place_order_by_key.assert_not_called()


def test_paper_equity_decays_with_realised_losses(wheel, mock_client):
    _enter(wheel, mock_client, 200_000.0, pnl=-120_000.0)  # equity 80k -> cap 2.4k
    mock_client.place_order_by_key.assert_not_called()


def test_open_max_loss(wheel):
    wheel.state["Nifty 50"] = {
        "current_stage": "STAGE_1_CSP", "net_credit_received": 1000.0,
        "active_position": {"strike": 22000.0, "quantity": 65},
        "hedge_position": {"strike": 21900.0, "quantity": 65},
    }
    assert wheel._open_max_loss() == pytest.approx(100 * 65 - 1000)

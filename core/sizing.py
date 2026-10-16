"""Risk-based position sizing shared by the live/paper bot and the backtest."""
import math


def risk_lots(
    width: float,
    credit: float,
    lot_size: int,
    equity: float,
    open_risk: float,
    risk_pct: float,
    portfolio_pct: float,
) -> tuple[int, str]:
    """Lots such that max loss (width - credit) x lot x lots obeys both caps.

    Returns (lots, reason). lots == 0 means skip; reason says which cap bound
    (empty when lots > 0). Credit is floored at 0 so a bad quote never shrinks the
    assumed max loss below the spread width.
    """
    max_loss_per_lot = (width - max(credit, 0.0)) * lot_size
    if max_loss_per_lot <= 0 or equity <= 0:
        return 0, f"invalid inputs (width={width}, credit={credit}, equity={equity:.0f})"
    per_trade = math.floor(equity * risk_pct / max_loss_per_lot)
    portfolio = math.floor((equity * portfolio_pct - open_risk) / max_loss_per_lot)
    lots = min(per_trade, portfolio)
    if lots >= 1:
        return lots, ""
    which = "per-trade" if per_trade < 1 else "portfolio"
    return 0, (
        f"1 lot max loss {max_loss_per_lot:.0f} breaches {which} risk cap "
        f"(equity {equity:.0f}: trade {equity * risk_pct:.0f}, "
        f"portfolio {equity * portfolio_pct:.0f} less open {open_risk:.0f})"
    )

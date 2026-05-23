import datetime
import numpy as np
import polars as pl
import yfinance as yf


def fetch_historical_data(ticker: str, start_date: str, end_date: str) -> pl.DataFrame:
    """
    Fetches historical daily data for the provided ticker and the India VIX.

    Args:
        ticker (str): The asset ticker formatted for yfinance (e.g., 'RELIANCE.NS').
        start_date (str): Start date in 'YYYY-MM-DD' format.
        end_date (str): End date in 'YYYY-MM-DD' format.

    Returns:
        pl.DataFrame: A Polars DataFrame containing 'Date', 'Spot_Price', and 'VIX'.
    """
    # Fetch asset data
    asset_df = yf.download(ticker, start=start_date, end=end_date, progress=False)
    # Fetch VIX data
    vix_df = yf.download("^INDIAVIX", start=start_date, end=end_date, progress=False)

    # Extract Close prices and convert the pandas index (Date) to a column
    asset_close = asset_df[['Close']].reset_index()
    vix_close = vix_df[['Close']].reset_index()

    # Rename columns for clarity before converting to Polars
    # yfinance sometimes returns a multi-index column if multiple tickers are passed,
    # but we are passing a single ticker so it should be a single level 'Close'
    asset_close.columns = ['Date', 'Spot_Price']
    vix_close.columns = ['Date', 'VIX']

    # Convert to Polars DataFrames
    pl_asset = pl.from_pandas(asset_close)
    pl_vix = pl.from_pandas(vix_close)

    # Cast Date to pure Polars Date (YYYY-MM-DD, dropping time/timezone)
    # yfinance dates are usually timezone-naive or tz-aware datetime.
    # By casting to pl.Date, we keep just the calendar date.

    # Check if the Date column is not already a Date type and cast it.
    # pl_asset.schema['Date'] gives the dtype of the Date column.

    # First, handle potential Datetime type with timezone by converting to tz-naive
    # and then to Date. Or, if we just cast to pl.Date directly, Polars might handle it,
    # but sometimes tz-aware Datetime needs specific handling. Let's cast directly and see.
    # Actually, yfinance dates are usually tz-aware, we can convert to string first or cast.
    # Let's use dt.date() if it's datetime.

    if pl_asset.schema['Date'] != pl.Date:
        # Cast to Date type. If it's Datetime with tz, we might need to convert it.
        # .cast(pl.Date) generally drops the time and timezone.
        try:
             pl_asset = pl_asset.with_columns(pl.col("Date").dt.date())
        except Exception:
             pl_asset = pl_asset.with_columns(pl.col("Date").cast(pl.Date))

    if pl_vix.schema['Date'] != pl.Date:
        try:
             pl_vix = pl_vix.with_columns(pl.col("Date").dt.date())
        except Exception:
             pl_vix = pl_vix.with_columns(pl.col("Date").cast(pl.Date))

    # Perform a left join using the asset DataFrame as the base
    merged_df = pl_asset.join(pl_vix, on="Date", how="left")

    # Forward-fill both VIX and Spot_Price columns to safely handle missing data
    merged_df = merged_df.with_columns([
        pl.col("Spot_Price").fill_null(strategy="forward"),
        pl.col("VIX").fill_null(strategy="forward")
    ])

    # Select the final columns to ensure order and exact presence
    final_df = merged_df.select(["Date", "Spot_Price", "VIX"])

    return final_df

def estimate_premium(spot: float, strike: float, vix: float, dte: int = 30) -> float:
    """
    Estimates the premium of an option using a simplified synthetic rule.

    Formula: Premium = (Spot * (VIX / 100)) * 0.10 * (strike / spot)
    """
    return (spot * (vix / 100.0)) * 0.10 * (strike / spot)

def run_backtest(df: pl.DataFrame, initial_capital: float = 500000.0) -> dict:
    """
    Simulates the Wheel Strategy backtest using a predefined DataFrame.
    """
    days_in_trade = 0
    in_trade = False
    short_strike = 0.0
    long_strike = 0.0
    net_credit = 0.0
    realized_pnl = 0.0
    total_trades = 0
    winning_trades = 0
    trade_history = []
    entry_date = None

    for row in df.iter_rows(named=True):
        # In newer polars versions iter_rows(named=True) can return dictionaries or namedtuples
        spot = row.get('Spot_Price') if isinstance(row, dict) else row.Spot_Price
        vix = row.get('VIX') if isinstance(row, dict) else row.VIX
        date = row.get('Date') if isinstance(row, dict) else row.Date

        # Safety check: if spot or VIX is missing, skip row
        if spot is None or vix is None or np.isnan(spot) or np.isnan(vix):
            continue

        if not in_trade:
            # Entry Logic
            if vix < 13:
                otm = 0.06
            elif 13 <= vix <= 18:
                otm = 0.10
            else:
                otm = 0.15

            short_strike = spot * (1 - otm)
            long_strike = short_strike * 0.98
            net_credit = estimate_premium(spot, short_strike, vix)

            realized_pnl += net_credit
            in_trade = True
            days_in_trade = 0
            total_trades += 1
            entry_date = date
            trade_history.append({
                "entry_date": entry_date,
                "short_strike": short_strike,
                "long_strike": long_strike,
                "net_credit": net_credit
            })

        else:
            # Exit Logic
            days_in_trade += 1
            if days_in_trade == 30:
                if spot > short_strike:
                    # Trade won (expires worthless). Retain premium.
                    winning_trades += 1
                else:
                    # Trade lost. Calculate loss and deduct from PnL.
                    loss = (short_strike - long_strike) - net_credit
                    realized_pnl -= loss

                # Reset trade status
                in_trade = False
                days_in_trade = 0
                short_strike = 0.0
                long_strike = 0.0
                net_credit = 0.0

    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0

    return {
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "win_rate": win_rate,
        "final_pnl": realized_pnl
    }

if __name__ == "__main__":
    print("Fetching historical data for RELIANCE.NS from 2021-01-01 to 2026-01-01...")
    df = fetch_historical_data("RELIANCE.NS", "2021-01-01", "2026-01-01")

    print("Running backtest simulation...")
    results = run_backtest(df)

    print("\n--- Backtest Results ---")
    print(f"Total Trades: {results['total_trades']}")
    print(f"Win Rate:     {results['win_rate']:.2f}%")
    print(f"Final PnL:    {results['final_pnl']:.2f}")

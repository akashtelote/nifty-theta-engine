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

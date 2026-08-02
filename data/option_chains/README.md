# Optional historical option chains (PROF-015)

Place daily snapshots here as `.parquet` or `.csv`.

Required columns: `date`, `expiry`, `type`, `strike`, `bid`, `ask`  
Optional: `mid`, `spot`, `vix`

When files exist, `backtest.load_option_chains()` can use mid marks.
Without files, backtests use VIX-calibrated Black–Scholes on Nifty/VIX paths.

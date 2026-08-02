import os
import psycopg2
import polars as pl
import streamlit as st

st.set_page_config(page_title="Wheel Strategy Dashboard", layout="wide")

st.title("Wheel Strategy Analytics Dashboard")

@st.cache_data(ttl=60)
def load_data() -> pl.DataFrame:
    try:
        db_url = os.getenv("DATABASE_URL", "postgresql://wheelbot:securepassword@localhost:5432/wheeldb")
        conn = psycopg2.connect(db_url)
        query = "SELECT * FROM index_spread_state"
        df = pl.read_database(query, connection=conn)
        conn.close()
        return df
    except psycopg2.OperationalError as e:
        st.error(f"Error loading database: {e}")
        return pl.DataFrame(schema={
            "symbol": pl.Utf8,
            "current_stage": pl.Utf8,
            "short_instrument_key": pl.Utf8,
            "short_strike": pl.Float64,
            "short_entry_price": pl.Float64,
            "short_order_id": pl.Utf8,
            "long_instrument_key": pl.Utf8,
            "long_strike": pl.Float64,
            "long_entry_price": pl.Float64,
            "long_order_id": pl.Utf8,
            "quantity": pl.Int64,
            "net_credit_received": pl.Float64,
            "trade_date": pl.Utf8,
            "expiry_date": pl.Utf8,
            "realized_pnl": pl.Float64
        })
    except Exception as e:
        st.error(f"An unexpected error occurred: {e}")
        return pl.DataFrame()


def _fetch_cost_to_close(symbol: str, short_key: str, long_key: str, expiry: str | None) -> float | None:
    """Best-effort live cost-to-close; returns None if quotes unavailable."""
    try:
        from core.client import UpstoxClient
        client = UpstoxClient()
        chain = client.get_option_chain(symbol, expiry_date=expiry) if expiry else client.get_option_chain(symbol)
        if chain is None or chain.is_empty():
            return None
        short_df = chain.filter(pl.col("instrument_key") == short_key)
        long_df = chain.filter(pl.col("instrument_key") == long_key)
        if short_df.is_empty() or long_df.is_empty():
            return None
        ask = short_df.row(0, named=True).get("ask")
        bid = long_df.row(0, named=True).get("bid")
        if ask is None or bid is None:
            return None
        return float(ask) - float(bid)
    except Exception:
        return None


@st.cache_data(ttl=60)
def load_trade_history() -> pl.DataFrame:
    try:
        db_url = os.getenv("DATABASE_URL", "postgresql://wheelbot:securepassword@localhost:5432/wheeldb")
        conn = psycopg2.connect(db_url)
        history_df = pl.read_database("SELECT * FROM trade_history ORDER BY closed_at DESC", connection=conn)
        conn.close()
        return history_df
    except Exception:
        return pl.DataFrame()


# Load data
df = load_data()

if df.is_empty():
    st.warning("No data found in the database. Please ensure the strategy engine has run.")
    st.stop()

expected_columns = [
    "symbol", "current_stage", "short_instrument_key", "short_strike", "short_entry_price",
    "short_order_id", "long_instrument_key", "long_strike", "long_entry_price", "long_order_id",
    "quantity", "net_credit_received", "trade_date", "expiry_date", "realized_pnl",
]
for col in expected_columns:
    if col not in df.columns:
        df = df.with_columns(pl.lit(None).alias(col))

# --- Key Metrics Row ---
st.header("Global Summary Metrics")

active_positions = df.filter(pl.col("current_stage") != "IDLE")
total_active = active_positions.height
total_pnl = df["realized_pnl"].fill_null(0.0).sum()

idle_count = df.filter(pl.col("current_stage") == "IDLE").height
csp_count = df.filter(pl.col("current_stage") == "STAGE_1_CSP").height
cc_count = df.filter(pl.col("current_stage") == "STAGE_2_CC").height

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Active Positions", total_active)
col2.metric("Total Realized PnL", f"₹{total_pnl:,.2f}" if total_pnl is not None else "₹0.00")
col3.metric("IDLE States", idle_count)
col4.metric("STAGE 1 (CSP)", csp_count)
col5.metric("STAGE 2 (CC)", cc_count)

# --- Active Positions + unrealized MTM (PROF-013) ---
st.header("Active Positions")
if active_positions.is_empty():
    st.info("No active positions currently.")
else:
    active_display = active_positions.select([
        "symbol", "current_stage", "short_strike", "long_strike",
        "net_credit_received", "quantity", "expiry_date", "trade_date",
        "short_instrument_key", "long_instrument_key", "short_entry_price", "long_entry_price",
    ])
    mtm_rows = []
    for row in active_display.iter_rows(named=True):
        unrealized = None
        cost_to_close = None
        if row.get("current_stage") == "STAGE_1_CSP":
            short_key = row.get("short_instrument_key")
            long_key = row.get("long_instrument_key")
            qty = row.get("quantity") or 0
            short_entry = row.get("short_entry_price") or 0.0
            long_entry = row.get("long_entry_price") or 0.0
            initial_credit = short_entry - long_entry
            if short_key and long_key:
                cost_to_close = _fetch_cost_to_close(
                    row["symbol"], short_key, long_key, row.get("expiry_date")
                )
                if cost_to_close is not None and qty:
                    unrealized = (initial_credit - cost_to_close) * qty
        mtm_rows.append({
            "symbol": row["symbol"],
            "current_stage": row["current_stage"],
            "short_strike": row["short_strike"],
            "long_strike": row["long_strike"],
            "net_credit_received": row["net_credit_received"],
            "quantity": row["quantity"],
            "expiry_date": row["expiry_date"],
            "trade_date": row["trade_date"],
            "cost_to_close": cost_to_close if cost_to_close is not None else "n/a",
            "unrealized_pnl": f"{unrealized:.2f}" if unrealized is not None else "n/a",
        })
    st.dataframe(pl.DataFrame(mtm_rows).to_pandas(), use_container_width=True, hide_index=True)
    st.caption("Unrealized P&L / cost-to-close use live option marks when available; otherwise n/a.")

# --- Closed-trade telemetry (PROF-014) ---
st.header("Closed-Trade Telemetry")
historical_df = load_trade_history()

if historical_df.is_empty():
    st.info("No closed trades in `trade_history` yet — empty state.")
else:
    pnl_col = "realized_pnl" if "realized_pnl" in historical_df.columns else None
    credit_col = "net_credit_received" if "net_credit_received" in historical_df.columns else None
    reason_col = "exit_reason" if "exit_reason" in historical_df.columns else None

    n = historical_df.height
    pnls = historical_df[pnl_col].fill_null(0.0) if pnl_col else pl.Series([0.0] * n)
    wins = int((pnls > 0).sum()) if n else 0
    win_rate = (wins / n * 100.0) if n else 0.0
    avg_credit = float(historical_df[credit_col].fill_null(0.0).mean()) if credit_col else 0.0
    total_realized = float(pnls.sum()) if n else 0.0

    t1, t2, t3, t4 = st.columns(4)
    t1.metric("Closed Trades", n)
    t2.metric("Win Rate", f"{win_rate:.1f}%")
    t3.metric("Avg Credit", f"₹{avg_credit:,.2f}")
    t4.metric("Realized P&L", f"₹{total_realized:,.2f}")

    if reason_col:
        st.subheader("Exit-Reason Mix")
        mix = (
            historical_df.group_by(reason_col)
            .agg(pl.len().alias("count"))
            .sort("count", descending=True)
        )
        st.dataframe(mix.to_pandas(), use_container_width=True, hide_index=True)
        st.bar_chart(mix.to_pandas().set_index(reason_col)["count"])

# --- Visual Breakdown ---
st.header("Visual Breakdown")

col_v1, col_v2 = st.columns(2)

with col_v1:
    st.subheader("Realized PnL by Symbol")
    pnl_by_symbol = df.group_by("symbol").agg(pl.col("realized_pnl").fill_null(0.0).sum())
    pnl_by_symbol = pnl_by_symbol.sort("realized_pnl", descending=True)
    if not pnl_by_symbol.is_empty():
        st.bar_chart(pnl_by_symbol.to_pandas().set_index("symbol")["realized_pnl"])
    else:
        st.info("No PnL data available to display.")

with col_v2:
    st.subheader("Stage Distribution")
    stage_counts = df.group_by("current_stage").agg(pl.len().alias("count"))
    if not stage_counts.is_empty():
        st.bar_chart(stage_counts.to_pandas().set_index("current_stage")["count"])
    else:
        st.info("No stage distribution data available.")

# --- Historical Logs Table ---
st.header("Historical Trade Ledger")

if historical_df.is_empty():
    st.info("No historical trades found.")
else:
    st.dataframe(historical_df.to_pandas(), use_container_width=True, hide_index=True)

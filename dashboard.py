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
        # Using string representation of connection string since read_database might expect an engine/connection string
        # actually, polars read_database supports connection objects from dbapi2 compliant libraries
        query = "SELECT * FROM wheel_state"
        df = pl.read_database(query, connection=conn)
        conn.close()
        return df
    except psycopg2.OperationalError as e:
        st.error(f"Error loading database: {e}")
        # Return empty DataFrame with expected schema
        return pl.DataFrame(schema={
            "symbol": pl.Utf8,
            "current_stage": pl.Utf8,
            "instrument_key": pl.Utf8,
            "strike_price": pl.Float64,
            "expiry": pl.Utf8,
            "trade_date": pl.Utf8,
            "entry_price": pl.Float64,
            "order_id": pl.Utf8,
            "assigned_shares": pl.Int64,
            "average_cost_basis": pl.Float64,
            "realized_pnl": pl.Float64
        })
    except Exception as e:
        st.error(f"An unexpected error occurred: {e}")
        return pl.DataFrame()

# Load data
df = load_data()

if df.is_empty():
    st.warning("No data found in the database. Please ensure the strategy engine has run.")
    st.stop()

# Ensure expected columns exist (in case of partial schemas)
expected_columns = ["symbol", "current_stage", "instrument_key", "strike_price", "expiry", "trade_date", "entry_price", "order_id", "assigned_shares", "average_cost_basis", "realized_pnl"]
for col in expected_columns:
    if col not in df.columns:
        # Add missing column with null values
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

# --- Active Positions Table ---
st.header("Active Positions")
if active_positions.is_empty():
    st.info("No active positions currently.")
else:
    active_display = active_positions.select([
        "symbol", "current_stage", "instrument_key", "strike_price",
        "expiry", "entry_price", "trade_date"
    ])
    st.dataframe(active_display.to_pandas(), use_container_width=True, hide_index=True)

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
historical_df = df.filter((pl.col("current_stage") == "IDLE") & (pl.col("realized_pnl").fill_null(0.0) != 0))

if historical_df.is_empty():
    st.info("No historical trades with realized PnL found.")
else:
    st.dataframe(historical_df.to_pandas(), use_container_width=True, hide_index=True)

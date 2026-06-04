DROP TABLE IF EXISTS wheel_state;

CREATE TABLE index_spread_state (
    symbol TEXT PRIMARY KEY,
    current_stage TEXT,
    short_instrument_key TEXT,
    short_strike DOUBLE PRECISION,
    short_entry_price DOUBLE PRECISION,
    short_order_id TEXT,
    long_instrument_key TEXT,
    long_strike DOUBLE PRECISION,
    long_entry_price DOUBLE PRECISION,
    long_order_id TEXT,
    quantity INTEGER,
    net_credit_received DOUBLE PRECISION,
    trade_date TEXT,
    expiry_date TEXT,
    realized_pnl DOUBLE PRECISION
);

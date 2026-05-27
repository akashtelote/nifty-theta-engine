import sqlite3
import psycopg2
import os
import sys

def migrate_data():
    sqlite_db_file = "data/wheel_state.db"
    postgres_url = os.getenv("DATABASE_URL", "postgresql://wheelbot:securepassword@localhost:5432/wheeldb")

    if not os.path.exists(sqlite_db_file):
        print(f"SQLite database file not found at {sqlite_db_file}. Nothing to migrate.")
        return

    print(f"Connecting to SQLite database at {sqlite_db_file}...")
    try:
        sqlite_conn = sqlite3.connect(sqlite_db_file)
        sqlite_cursor = sqlite_conn.cursor()

        sqlite_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='wheel_state'")
        if not sqlite_cursor.fetchone():
            print("Table 'wheel_state' does not exist in SQLite database. Nothing to migrate.")
            sqlite_conn.close()
            return

        sqlite_cursor.execute('''
            SELECT symbol, current_stage, instrument_key, strike_price, expiry, trade_date,
                   entry_price, order_id, assigned_shares, average_cost_basis, realized_pnl,
                   hedge_instrument_key, hedge_strike_price, hedge_entry_price, hedge_order_id
            FROM wheel_state
        ''')
        rows = sqlite_cursor.fetchall()
        print(f"Found {len(rows)} rows to migrate.")
    except sqlite3.Error as e:
        print(f"Error reading from SQLite: {e}")
        sys.exit(1)

    if not rows:
        print("No data found to migrate.")
        sqlite_conn.close()
        return

    print(f"Connecting to PostgreSQL database...")
    try:
        pg_conn = psycopg2.connect(postgres_url)
        pg_cursor = pg_conn.cursor()

        # Ensure table exists first
        pg_cursor.execute('''
            CREATE TABLE IF NOT EXISTS wheel_state (
                symbol TEXT PRIMARY KEY,
                current_stage TEXT,
                instrument_key TEXT,
                strike_price DOUBLE PRECISION,
                expiry TEXT,
                trade_date TEXT,
                entry_price DOUBLE PRECISION,
                order_id TEXT,
                assigned_shares INTEGER,
                average_cost_basis DOUBLE PRECISION,
                realized_pnl DOUBLE PRECISION,
                hedge_instrument_key TEXT,
                hedge_strike_price DOUBLE PRECISION,
                hedge_entry_price DOUBLE PRECISION,
                hedge_order_id TEXT
            )
        ''')

        inserted_count = 0
        for row in rows:
            pg_cursor.execute('''
                INSERT INTO wheel_state
                (symbol, current_stage, instrument_key, strike_price, expiry, trade_date,
                 entry_price, order_id, assigned_shares, average_cost_basis, realized_pnl,
                 hedge_instrument_key, hedge_strike_price, hedge_entry_price, hedge_order_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (symbol) DO UPDATE SET
                    current_stage = EXCLUDED.current_stage,
                    instrument_key = EXCLUDED.instrument_key,
                    strike_price = EXCLUDED.strike_price,
                    expiry = EXCLUDED.expiry,
                    trade_date = EXCLUDED.trade_date,
                    entry_price = EXCLUDED.entry_price,
                    order_id = EXCLUDED.order_id,
                    assigned_shares = EXCLUDED.assigned_shares,
                    average_cost_basis = EXCLUDED.average_cost_basis,
                    realized_pnl = EXCLUDED.realized_pnl,
                    hedge_instrument_key = EXCLUDED.hedge_instrument_key,
                    hedge_strike_price = EXCLUDED.hedge_strike_price,
                    hedge_entry_price = EXCLUDED.hedge_entry_price,
                    hedge_order_id = EXCLUDED.hedge_order_id
            ''', row)
            inserted_count += 1

        pg_conn.commit()
        print(f"Successfully migrated {inserted_count} rows to PostgreSQL.")

    except psycopg2.Error as e:
        print(f"Error writing to PostgreSQL: {e}")
        if pg_conn:
            pg_conn.rollback()
        sys.exit(1)
    finally:
        if sqlite_conn:
            sqlite_conn.close()
        if pg_conn:
            pg_conn.close()

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    migrate_data()

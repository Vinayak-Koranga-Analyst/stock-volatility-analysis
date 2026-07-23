"""
Compute per-ticker return and volatility metrics from stock_prices and write
them to a stock_metrics table in the same DuckDB file.

Metrics per (ticker, date):
    daily_return    - simple day-over-day return on close
    volatility_30d  - 30-day rolling std of daily returns, annualized (x sqrt(252))
    volatility_90d  - 90-day rolling std of daily returns, annualized (x sqrt(252))
    ma_50           - 50-day simple moving average of close
    ma_200          - 200-day simple moving average of close

Each rolling metric is NULL until a full window of history is available
(e.g. ma_200 is NULL for a ticker's first 199 rows).

Usage:
    python analysis.py [--db data/stocks.duckdb]
"""

import argparse
import logging
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(__file__).parent / "data" / "stocks.duckdb"
SOURCE_TABLE = "stock_prices"
TARGET_TABLE = "stock_metrics"
TRADING_DAYS_PER_YEAR = 252


def load_prices(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    df = con.execute(f"SELECT date, ticker, close FROM {SOURCE_TABLE} ORDER BY ticker, date").fetchdf()
    df["date"] = pd.to_datetime(df["date"])
    return df


def compute_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Per ticker: daily return, annualized 30d/90d rolling volatility, and
    50d/200d simple moving averages. Requires a full window before a metric
    is populated, so early rows of each ticker's history carry NULLs."""
    groups = []
    for ticker, g in df.groupby("ticker", sort=False):
        g = g.sort_values("date").copy()
        g["daily_return"] = g["close"].pct_change()
        g["volatility_30d"] = g["daily_return"].rolling(30, min_periods=30).std() * np.sqrt(TRADING_DAYS_PER_YEAR)
        g["volatility_90d"] = g["daily_return"].rolling(90, min_periods=90).std() * np.sqrt(TRADING_DAYS_PER_YEAR)
        g["ma_50"] = g["close"].rolling(50, min_periods=50).mean()
        g["ma_200"] = g["close"].rolling(200, min_periods=200).mean()
        groups.append(g)

    result = pd.concat(groups, ignore_index=True)
    result["date"] = result["date"].dt.date
    return result[["date", "ticker", "daily_return", "volatility_30d", "volatility_90d", "ma_50", "ma_200"]]


def write_metrics(df: pd.DataFrame, con: duckdb.DuckDBPyConnection) -> None:
    con.execute(f"""
        CREATE OR REPLACE TABLE {TARGET_TABLE} (
            date            DATE    NOT NULL,
            ticker          VARCHAR NOT NULL,
            daily_return    DOUBLE,
            volatility_30d  DOUBLE,
            volatility_90d  DOUBLE,
            ma_50           DOUBLE,
            ma_200          DOUBLE,
            PRIMARY KEY (date, ticker)
        )
    """)
    con.register("df_metrics", df)
    con.execute(f"INSERT INTO {TARGET_TABLE} SELECT * FROM df_metrics")
    log.info("Wrote %d rows to '%s'", len(df), TARGET_TABLE)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Path to the DuckDB database file")
    args = parser.parse_args()

    con = duckdb.connect(args.db)
    try:
        prices = load_prices(con)
        log.info("Loaded %d price rows for %d tickers", len(prices), prices["ticker"].nunique())
        metrics = compute_metrics(prices)
        write_metrics(metrics, con)
    finally:
        con.close()


if __name__ == "__main__":
    main()

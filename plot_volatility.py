"""
Plot the top tickers by most recent 30-day annualized volatility, from the
stock_metrics table.

Usage:
    python plot_volatility.py [--db data/stocks.duckdb] [--top 10] [--out plots/volatility.png]
"""

import argparse
import logging
from pathlib import Path

import duckdb
import matplotlib.pyplot as plt
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(__file__).parent / "data" / "stocks.duckdb"
DEFAULT_OUT_PATH = Path(__file__).parent / "plots" / "volatility.png"
DEFAULT_TOP_N = 10


def top_volatility(con: duckdb.DuckDBPyConnection, top_n: int):
    return con.execute(f"""
        SELECT ticker, date, volatility_30d
        FROM stock_metrics
        WHERE date = (SELECT MAX(date) FROM stock_metrics)
          AND volatility_30d IS NOT NULL
        ORDER BY volatility_30d DESC
        LIMIT {top_n}
    """).fetchdf()


def plot(df, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    as_of = pd.Timestamp(df["date"].iloc[0]).date()

    fig, ax = plt.subplots(figsize=(9, 6))
    bars = ax.bar(df["ticker"], df["volatility_30d"] * 100, color="#4C72B0")
    ax.bar_label(bars, fmt="%.1f%%", padding=3)

    ax.set_title(f"Top {len(df)} tickers by 30-day annualized volatility (as of {as_of})")
    ax.set_ylabel("Annualized volatility (%)")
    ax.set_xlabel("Ticker")
    ax.set_ylim(0, df["volatility_30d"].max() * 100 * 1.15)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    log.info("Saved plot to %s", out_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Path to the DuckDB database file")
    parser.add_argument("--top", type=int, default=DEFAULT_TOP_N, help="Number of tickers to plot")
    parser.add_argument("--out", default=str(DEFAULT_OUT_PATH), help="Output image path")
    args = parser.parse_args()

    con = duckdb.connect(args.db)
    try:
        df = top_volatility(con, args.top)
    finally:
        con.close()

    if df.empty:
        log.error("No volatility data found in stock_metrics; aborting")
        return

    plot(df, Path(args.out))


if __name__ == "__main__":
    main()

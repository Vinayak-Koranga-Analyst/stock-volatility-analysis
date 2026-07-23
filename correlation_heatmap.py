"""
Plot a correlation heatmap of daily returns across three sector groups:
Energy, Financials, and Technology.

Representative tickers per group are the top N (default 8, or fewer if a
group has fewer members) by average daily trading volume. Raw ICB sectors
map to groups as follows:

    Energy       - Oil & gas producers
    Financials   - Financial Services, Banks, Life insurance, Insurance,
                   Non-life Insurance, Real Estate Investment Trusts,
                   Investment Trusts, Real estate, Banking Services,
                   Collective investments
    Technology   - Technology (the 5 manually tagged US stocks),
                   Software & Computer Services, Electronic equipment & parts

Note: the FTSE 100 has only 2 constituents classified as pure "Oil & gas
producers" (BP.L, SHEL.L), so the Energy group is limited to those 2 -
narrower ICB sectors don't leave enough headroom for 5-8 without pulling in
Utilities, which is a distinct sector.

Usage:
    python correlation_heatmap.py [--db data/stocks.duckdb] [--top 8] [--out plots/correlation_heatmap.png]
"""

import argparse
import logging
from pathlib import Path

import duckdb
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(__file__).parent / "data" / "stocks.duckdb"
DEFAULT_OUT_PATH = Path(__file__).parent / "plots" / "correlation_heatmap.png"
DEFAULT_TOP_N = 8

SECTOR_GROUPS = {
    "Energy": {
        "Oil & gas producers",
    },
    "Financials": {
        "Financial Services", "Banks", "Life insurance", "Insurance",
        "Non-life Insurance", "Real Estate Investment Trusts",
        "Investment Trusts", "Real estate", "Banking Services",
        "Collective investments",
    },
    "Technology": {
        "Technology", "Software & Computer Services", "Electronic equipment & parts",
    },
}
SECTOR_TO_GROUP = {sector: group for group, sectors in SECTOR_GROUPS.items() for sector in sectors}
GROUP_ORDER = ["Energy", "Financials", "Technology"]
GROUP_COLORS = {"Energy": "#DD8452", "Financials": "#55A868", "Technology": "#4C72B0"}


def pick_representative_tickers(con: duckdb.DuckDBPyConnection, top_n: int) -> pd.DataFrame:
    """For each of the 3 groups, return the top N tickers by average daily
    volume, tagged with their group."""
    ranked = con.execute("""
        SELECT ts.ticker, ts.sector, AVG(sp.volume) AS avg_volume
        FROM ticker_sectors ts
        JOIN stock_prices sp ON sp.ticker = ts.ticker
        GROUP BY ts.ticker, ts.sector
    """).fetchdf()
    ranked["group"] = ranked["sector"].map(SECTOR_TO_GROUP)
    ranked = ranked.dropna(subset=["group"])

    picks = (
        ranked.sort_values("avg_volume", ascending=False)
        .groupby("group", sort=False)
        .head(top_n)
    )
    for group in GROUP_ORDER:
        n = (picks["group"] == group).sum()
        log.info("%s: %d representative ticker(s)", group, n)

    picks["group"] = pd.Categorical(picks["group"], categories=GROUP_ORDER, ordered=True)
    return picks.sort_values(["group", "avg_volume"], ascending=[True, False]).reset_index(drop=True)


def load_returns(con: duckdb.DuckDBPyConnection, tickers: list) -> pd.DataFrame:
    placeholders = ", ".join("?" * len(tickers))
    df = con.execute(f"""
        SELECT date, ticker, daily_return
        FROM stock_metrics
        WHERE ticker IN ({placeholders}) AND daily_return IS NOT NULL
    """, tickers).fetchdf()
    return df.pivot(index="date", columns="ticker", values="daily_return")


def plot_heatmap(corr: pd.DataFrame, picks: pd.DataFrame, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tickers = picks["ticker"].tolist()
    corr = corr.loc[tickers, tickers]

    fig, ax = plt.subplots(figsize=(0.55 * len(tickers) + 3, 0.55 * len(tickers) + 3))
    im = ax.imshow(corr.values, cmap="coolwarm", vmin=-1, vmax=1)

    ax.set_xticks(range(len(tickers)))
    ax.set_yticks(range(len(tickers)))
    ax.set_xticklabels(tickers, rotation=90)
    ax.set_yticklabels(tickers)

    for tick, ticker in zip(ax.get_xticklabels(), tickers):
        tick.set_color(GROUP_COLORS[picks.loc[picks["ticker"] == ticker, "group"].iloc[0]])
    for tick, ticker in zip(ax.get_yticklabels(), tickers):
        tick.set_color(GROUP_COLORS[picks.loc[picks["ticker"] == ticker, "group"].iloc[0]])

    for i in range(len(tickers)):
        for j in range(len(tickers)):
            ax.text(j, i, f"{corr.values[i, j]:.2f}", ha="center", va="center", fontsize=7)

    # Divider lines between sector groups
    boundaries = np.cumsum([(picks["group"] == g).sum() for g in GROUP_ORDER])[:-1]
    for b in boundaries:
        ax.axhline(b - 0.5, color="black", linewidth=1.2)
        ax.axvline(b - 0.5, color="black", linewidth=1.2)

    fig.colorbar(im, ax=ax, label="Correlation of daily returns", fraction=0.046, pad=0.04)
    ax.set_title("Daily return correlation: Energy vs Financials vs Technology")
    handles = [plt.Line2D([0], [0], color=GROUP_COLORS[g], lw=4) for g in GROUP_ORDER]
    ax.legend(handles, GROUP_ORDER, loc="upper left", bbox_to_anchor=(1.15, 1.0), frameon=False)

    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    log.info("Saved heatmap to %s", out_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Path to the DuckDB database file")
    parser.add_argument("--top", type=int, default=DEFAULT_TOP_N, help="Max representative tickers per group")
    parser.add_argument("--out", default=str(DEFAULT_OUT_PATH), help="Output image path")
    args = parser.parse_args()

    con = duckdb.connect(args.db)
    try:
        picks = pick_representative_tickers(con, args.top)
        returns = load_returns(con, picks["ticker"].tolist())
    finally:
        con.close()

    corr = returns.corr()
    plot_heatmap(corr, picks, Path(args.out))


if __name__ == "__main__":
    main()

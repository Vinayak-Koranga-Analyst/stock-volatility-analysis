"""
Pull 2 years of daily OHLCV price history for the FTSE 100 constituents plus a
fixed set of US tech stocks, and load it into a DuckDB database. Also scrapes
each FTSE 100 ticker's ICB sector (and tags the US tech stocks "Technology")
into a ticker_sectors table.

Usage:
    python fetch_data.py [--period 2y] [--db data/stocks.duckdb]
"""

import argparse
import logging
import sys
from pathlib import Path

import duckdb
import pandas as pd
import yfinance as yf

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(__file__).parent / "data" / "stocks.duckdb"
DEFAULT_PERIOD = "2y"
TABLE_NAME = "stock_prices"
SECTOR_TABLE_NAME = "ticker_sectors"

US_TECH_TICKERS = {
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "NVDA": "Nvidia",
    "AMZN": "Amazon",
    "GOOGL": "Alphabet (Google)",
}

# Snapshot fallback used only if the live Wikipedia scrape fails (e.g. no network).
# Raw LSE EPIC codes, not yet converted to Yahoo Finance format.
FTSE100_FALLBACK = [
    "III", "ABDN", "ADM", "AAF", "ALW", "AAL", "ANTO", "ABF", "AZN", "AUTO",
    "AV", "BAB", "BA", "BARC", "BTRW", "BEZ", "BP", "BATS", "BLND", "BT.A",
    "BNZL", "BRBY", "CNA", "CCEP", "CCH", "CPG", "CCC", "CTEC", "CRDA", "DCC",
    "DGE", "DPLM", "EDV", "ENT", "EXPN", "FCIT", "FRES", "GAW", "GLEN", "GSK",
    "HLN", "HLMA", "HSX", "HWDN", "HSBA", "ICG", "IGG", "IHG", "IMI", "IMB",
    "INF", "IAG", "ITRK", "INVP", "JD", "BGEO", "KGF", "LAND", "LGEN", "LLOY",
    "LMP", "LSEG", "MNG", "MKS", "MRO", "MTLN", "NG", "NWG", "NXT", "PSON",
    "PSH", "PSN", "PCT", "PRU", "RKT", "REL", "RTO", "RIO", "RR", "SGE",
    "SBRY", "SDR", "SMT", "SGRO", "SVT", "SHEL", "SMIN", "SN", "SPX", "SSE",
    "STAN", "SDLF", "STJ", "TSCO", "BBOX", "ULVR", "UU", "VOD", "WEIR", "WTB",
]

WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/FTSE_100_Index"

# The Wikipedia table's sector column isn't consistently cased across rows
# (e.g. "Financial services" vs "Financial Services"); collapse known
# casing variants of the same ICB sector onto one canonical label.
SECTOR_NORMALIZATION = {
    "financial services": "Financial Services",
    "investment trusts": "Investment Trusts",
    "real estate investment trusts": "Real Estate Investment Trusts",
    "software & computer services": "Software & Computer Services",
}


def epic_to_yahoo_ticker(epic: str) -> str:
    """Convert a raw LSE EPIC code (e.g. 'BT.A') to Yahoo Finance format ('BT-A.L')."""
    return epic.strip().replace(".", "-") + ".L"


def normalize_sector(raw: str) -> str:
    cleaned = raw.strip()
    return SECTOR_NORMALIZATION.get(cleaned.lower(), cleaned)


def fetch_ftse100_constituents() -> pd.DataFrame:
    """Scrape current FTSE 100 constituents (ticker, company, ICB sector) from
    Wikipedia. Falls back to a fixed ticker snapshot (sector 'Unknown') if the
    page can't be reached or its layout has changed."""
    try:
        tables = pd.read_html(WIKIPEDIA_URL, storage_options={"User-Agent": "Mozilla/5.0"})
        constituents = next(t for t in tables if {"Company", "Ticker"}.issubset(t.columns))
        sector_col = next(c for c in constituents.columns if c not in ("Company", "Ticker"))
        df = pd.DataFrame({
            "ticker": constituents["Ticker"].map(epic_to_yahoo_ticker),
            "company": constituents["Company"],
            "sector": constituents[sector_col].map(normalize_sector),
        })
        log.info("Fetched %d FTSE 100 constituents from Wikipedia", len(df))
        return df
    except Exception as exc:
        log.warning("Wikipedia scrape failed (%s); using fallback ticker list (sector unavailable)", exc)
        return pd.DataFrame({
            "ticker": [epic_to_yahoo_ticker(e) for e in FTSE100_FALLBACK],
            "company": FTSE100_FALLBACK,
            "sector": "Unknown",
        })


def build_universe(constituents: pd.DataFrame) -> tuple:
    """Return (ticker -> company, ticker -> sector) dicts for FTSE 100 + US tech."""
    companies = dict(zip(constituents["ticker"], constituents["company"]))
    sectors = dict(zip(constituents["ticker"], constituents["sector"]))
    companies.update(US_TECH_TICKERS)
    sectors.update({t: "Technology" for t in US_TECH_TICKERS})
    return companies, sectors


def download_prices(tickers: list, period: str) -> pd.DataFrame:
    """Download daily OHLCV history for all tickers and reshape to long format
    with columns: date, ticker, open, high, low, close, volume."""
    log.info("Downloading %s of daily history for %d tickers", period, len(tickers))
    raw = yf.download(
        tickers,
        period=period,
        interval="1d",
        group_by="ticker",
        auto_adjust=False,
        threads=True,
        progress=False,
    )

    rows = []
    skipped = []
    for ticker in tickers:
        try:
            df = raw[ticker] if len(tickers) > 1 else raw
        except KeyError:
            skipped.append(ticker)
            continue
        df = df.dropna(how="all")
        if df.empty:
            skipped.append(ticker)
            continue
        df = df.reset_index()[["Date", "Open", "High", "Low", "Close", "Volume"]]
        df.columns = ["date", "open", "high", "low", "close", "volume"]
        df["ticker"] = ticker
        rows.append(df)

    if skipped:
        log.warning("No data returned for %d tickers: %s", len(skipped), ", ".join(skipped))

    combined = pd.concat(rows, ignore_index=True)
    combined["date"] = pd.to_datetime(combined["date"]).dt.date
    combined["volume"] = combined["volume"].astype("Int64")

    null_close = combined["close"].isna()
    if null_close.any():
        n_dropped = int(null_close.sum())
        affected_tickers = combined.loc[null_close, "ticker"].nunique()
        date_range = (combined.loc[null_close, "date"].min(), combined.loc[null_close, "date"].max())
        log.warning(
            "Dropping %d row(s) with null close across %d ticker(s), dates %s to %s "
            "(likely unsettled data at fetch time)",
            n_dropped, affected_tickers, date_range[0], date_range[1],
        )
        combined = combined[~null_close]

    return combined[["date", "ticker", "open", "high", "low", "close", "volume"]]


def load_to_duckdb(df: pd.DataFrame, db_path: Path) -> None:
    """Create the schema if needed and upsert price rows keyed on (date, ticker)."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    try:
        con.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
                date    DATE   NOT NULL,
                ticker  VARCHAR NOT NULL,
                open    DOUBLE,
                high    DOUBLE,
                low     DOUBLE,
                close   DOUBLE,
                volume  BIGINT,
                PRIMARY KEY (date, ticker)
            )
        """)
        con.register("df_new", df)
        con.execute(f"""
            INSERT INTO {TABLE_NAME}
            SELECT * FROM df_new
            ON CONFLICT (date, ticker) DO UPDATE SET
                open = excluded.open,
                high = excluded.high,
                low = excluded.low,
                close = excluded.close,
                volume = excluded.volume
        """)
        count = con.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}").fetchone()[0]
        log.info("Loaded %d rows into %s (%s, table '%s')", len(df), db_path, count, TABLE_NAME)
    finally:
        con.close()


def load_sectors_to_duckdb(sectors: dict, db_path: Path) -> None:
    """Replace ticker_sectors with the current ticker -> sector mapping."""
    df = pd.DataFrame(sorted(sectors.items()), columns=["ticker", "sector"])
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    try:
        con.execute(f"""
            CREATE OR REPLACE TABLE {SECTOR_TABLE_NAME} (
                ticker VARCHAR NOT NULL PRIMARY KEY,
                sector VARCHAR NOT NULL
            )
        """)
        con.register("df_sectors", df)
        con.execute(f"INSERT INTO {SECTOR_TABLE_NAME} SELECT * FROM df_sectors")
        log.info("Loaded %d rows into '%s'", len(df), SECTOR_TABLE_NAME)
    finally:
        con.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--period", default=DEFAULT_PERIOD, help="yfinance period, e.g. 2y, 1y, 6mo")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Path to the DuckDB database file")
    args = parser.parse_args()

    constituents = fetch_ftse100_constituents()
    companies, sectors = build_universe(constituents)
    log.info("Ticker universe: %d total (FTSE 100 + US tech)", len(companies))

    prices = download_prices(list(companies.keys()), period=args.period)
    if prices.empty:
        log.error("No price data downloaded; aborting")
        sys.exit(1)

    load_to_duckdb(prices, Path(args.db))
    load_sectors_to_duckdb(sectors, Path(args.db))


if __name__ == "__main__":
    main()

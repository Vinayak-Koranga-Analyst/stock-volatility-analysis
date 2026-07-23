# stock-volatility-analysis

Pulls 2 years of daily OHLCV price history for the FTSE 100 constituents plus
Apple, Microsoft, Nvidia, Amazon, and Google, and loads it into DuckDB.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python fetch_data.py
```

This writes to `data/stocks.duckdb`, table `stock_prices`:

| column | type    |
|--------|---------|
| date   | DATE    |
| ticker | VARCHAR |
| open   | DOUBLE  |
| high   | DOUBLE  |
| low    | DOUBLE  |
| close  | DOUBLE  |
| volume | BIGINT  |

Primary key is `(date, ticker)`; re-running the script upserts rather than
duplicating rows. FTSE 100 constituents are scraped live from Wikipedia on
each run (with a fixed fallback list if that fails), so the ticker universe
always reflects current index membership.

```bash
duckdb data/stocks.duckdb -c "SELECT * FROM stock_prices LIMIT 5;"
```

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
python analysis.py
python plot_volatility.py
```

`fetch_data.py` writes to `data/stocks.duckdb`, table `stock_prices`:

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
always reflects current index membership. Rows with a null close (unsettled
data at fetch time) are dropped before loading.

`analysis.py` reads `stock_prices` and writes table `stock_metrics`, one row
per ticker per date:

| column          | type    |
|-----------------|---------|
| date            | DATE    |
| ticker          | VARCHAR |
| daily_return    | DOUBLE  |
| volatility_30d  | DOUBLE  |
| volatility_90d  | DOUBLE  |
| ma_50           | DOUBLE  |
| ma_200          | DOUBLE  |

`volatility_30d`/`volatility_90d` are annualized (rolling std of daily
returns x sqrt(252)); `ma_50`/`ma_200` are simple moving averages of close.
All rolling metrics are `NULL` until a ticker has enough history to fill the
full window (e.g. `ma_200` needs 200 prior rows).

```bash
duckdb data/stocks.duckdb -c "SELECT * FROM stock_prices LIMIT 5;"
duckdb data/stocks.duckdb -c "SELECT * FROM stock_metrics ORDER BY volatility_30d DESC LIMIT 5;"
```

`plot_volatility.py` reads `stock_metrics` and saves a bar chart of the top
tickers (default 10) by most recent 30-day annualized volatility to
`plots/volatility.png`. Use `--top` and `--out` to change the count or
output path.

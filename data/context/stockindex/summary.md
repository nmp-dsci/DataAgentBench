# stockindex — orientation summary

## 1. Shape
- Two stores, two tables, no shared database — must be joined logically, not via foreign key.
- `stockindex_index_info` (store `indexinfo_database`): 14 rows. Columns: `Exchange` (full exchange name, e.g. "Tokyo Stock Exchange"), `Currency` (trading currency, e.g. "JPY"). One row per exchange.
- `stockindex_index_trade` (store `indextrade_database`): 104,224 rows. Columns: `Index` (abbreviated index symbol, e.g. "N225", "HSI"), `Date` (text), `Open`, `High`, `Low`, `Close`, `Adj Close`, `CloseUSD` (all double precision). This is the large, most-queried table — 13 distinct `Index` values, row counts per index range from 13,947 (NYA) down to smaller counts for others (e.g. 5,760 for "399001.SZ").
- No explicit join key column exists between the two tables (see §2).

## 2. Keys and joins
- No measured join is listed in joins.md — the table is present but empty (no rows), meaning no automated overlap was computed between `stockindex_index_info.Exchange` and `stockindex_index_trade.Index`.
- Per hints.txt, the join between the two tables must be done by matching full exchange name (`stockindex_index_info.Exchange`) to abbreviated index symbol (`stockindex_index_trade.Index`) using a manual/known mapping (e.g. "Tokyo Stock Exchange" ↔ "N225"; "Hong Kong Stock Exchange" ↔ "HSI"). This is not a literal string match — it requires a lookup table of exchange-to-index correspondences that is not stored in either table.
- `stockindex_index_info` has 14 rows but `stockindex_index_trade.Index` has only 13 distinct values — counts do not match 1:1, so not every exchange in `index_info` necessarily has a corresponding index in `index_trade` (or vice versa); this is unverified from the data alone.

## 3. Literal values
- `stockindex_index_info.Exchange` — 14 distinct values, each appearing once (top values include "Toronto Stock Exchange", "Tokyo Stock Exchange", "Korea Exchange", "Euronext", "Shenzhen Stock Exchange", "Johannesburg Stock Exchange", "Taiwan Stock Exchange", "National Stock Exchange of India", "Hong Kong Stock Exchange", "NASDAQ").
- `stockindex_index_info.Currency` — 11 distinct values: "CNY", "EUR", "USD" each appear twice; "CHF", "CAD", "INR", "KRW", "HKD", "JPY", "ZAR" each appear once.
- `stockindex_index_trade.Index` — 13 distinct symbols, with row counts: "NYA" (13,947), "N225" (13,874), "IXIC" (12,690), "GSPTSE" (10,526), "HSI" (8,492), "GDAXI" (8,438), "SSMI" (7,671), "TWII" (5,869), "000001.SS" (5,791), "399001.SZ" (5,760), and others not listed in top-10.
- `stockindex_index_trade.Date` is character varying (text), not a date type — 37,311 distinct values across 104,224 rows. Sample rows show **at least three different date formats co-existing in the same column**: "31 Dec 1986, 00:00", "January 02, 1987 at 12:00 AM", "1987-01-05 00:00:00", "06 Jan 1987, 00:00". Any date parsing/filtering must handle mixed formats or cast per-format.

## 4. Text columns that need reading
- No free-text description, title, README, or JSON columns exist in either table. Both tables are fully structured (varchar/numeric) with no JSONB columns.

## 5. Conventions in the description/hints (quoted exactly)
- "The Exchange field in indexinfo_database contains full exchange names ... The Index field in indextrade_database contains abbreviated index symbols ... To join these datasets, you need to match exchange names with their corresponding major index symbols."
- "The region (e.g., Asia, Europe, North America) of each stock exchange is not explicitly provided. You must infer the region using geographic knowledge."
- "'Up days' refer to trading days where the closing price is higher than the opening price. 'Down days' refer to trading days where the closing price is lower than the opening price."
- "The term 'average intraday volatility' refers to the average relative fluctuation of a stock index within each trading day. It is typically computed as (High - Low) / Open for each day, then averaged across a given time period."

# stockmarket — orientation summary

## Shape
- Two logical stores: `stockinfo_database` (metadata) and `stocktrade_database` (daily price history).
- `stockmarket_stockinfo` — 2,752 rows, one row per ticker (`Symbol` has 2,752 distinct values = unique). Metadata only: exchange, category, ETF flag, financial status, company description.
- `stocktrade_database` is 2,715 separate per-ticker tables (e.g. `stockmarket_cvx` 14,663 rows, `stockmarket_cmi` 11,885 rows) all sharing the same 7 columns (`Date, Open, High, Low, Close, Adj Close, Volume`). One family (2,715 tables, incl. `stockmarket_cvx`) has `Volume` as `bigint`; a smaller family of 38 tables (incl. `stockmarket_cmi`) has `Volume` as `double precision`.
- `stockmarket_stocktrade_all` — 6,236,194 rows — is the union view over all per-ticker trade tables, adding a `_table` column (ticker name, lowercase, no `stockmarket_` prefix, e.g. `aaau`). This is the table to use for any cross-ticker trade query; the largest table and the one most needing joins.
- Individual per-ticker tables (`stockmarket_cvx`, `stockmarket_cmi`, etc.) are only useful for single-ticker analysis; they carry no ticker column of their own.

## Keys and joins
- `stockmarket_stocktrade_all."_table"` ↔ `stockmarket_stockinfo."Symbol"`: no measured overlap row exists in joins.md for this pair — schema.md documents `_table` as "the member name without the `stockmarket_` prefix, e.g. the ticker" and samples show it lowercase (e.g. `aaau`), while `Symbol` samples show uppercase (e.g. `AAAU`). Case-fold (`lower()`) is required before joining; not measured/confirmed beyond the schema note and samples.
- `stockmarket_stocktrade_all."Date"` ↔ `stockmarket_cvx."Date"`: 10,887 distinct values in A, raw share 1.0, normalised share 1.0, digits-only share 1.0 — clean join, no normalisation needed.
- `stockmarket_stocktrade_all."Date"` ↔ `stockmarket_cmi."Date"`: 11,196 distinct in A, raw share 0.9528, normalised 0.9887, digits-only 0.9917 — normalisation (trim/case-fold) improves the match modestly but doesn't fully close the gap.
- `stockmarket_cvx."Date"` ↔ `stockmarket_cmi."Date"`: 14,663 distinct in A, raw/normalised/digits-only share all 0.8105 — different date coverage between tickers, not a data-cleaning issue.
- Price/volume columns (`High`, `Low`, `Close`, `Open`, `Volume`, `Adj Close`) across `stockmarket_stocktrade_all`, `stockmarket_cvx`, `stockmarket_cmi` show low overlap shares (0.0001–0.26 range) — these are not usable join keys, only `Date` (and presumably `_table`/`Symbol`) are.

## Literal values
- `stockmarket_stockinfo."Nasdaq Traded"`: single value `Y` (2,752/2,752).
- `stockmarket_stockinfo."Listing Exchange"`: `P` (1,444), `Q` (710), `Z` (336), `N` (234), `A` (28). Per hints.txt: A=NYSE MKT, N=NYSE, P=NYSE ARCA, Z=BATS, V=IEXG, Q=NASDAQ Global Select Market.
- `stockmarket_stockinfo."Market Category"`: `Not applicable or not NASDAQ-listed` (2,042), `G` (451), `Q` (173), `S` (86). Per hints.txt: Q=NASDAQ Global Select Market, G=NASDAQ Global Market, S=NASDAQ Capital Market.
- `stockmarket_stockinfo."ETF"`: `Y` (2,165), `N` (587).
- `stockmarket_stockinfo."Test Issue"`: single value `N` (2,752/2,752).
- `stockmarket_stockinfo."Financial Status"`: null_rate 0.742 (2,043 of 2,752 rows null); non-null top values `N` (685), `D` (24), `H` (1). Per hints.txt: D=Deficient, E=Delinquent, Q=Bankrupt, N=Normal, G=Deficient+bankrupt, H=Deficient+delinquent, J=Delinquent+bankrupt, K=Deficient+delinquent+bankrupt. Hints.txt: "A company is considered financially troubled if it is deficient, delinquent, or both."
- `stockmarket_stockinfo."NextShares"`: `N` (2,751), `Y` (1).
- `stockmarket_stockinfo."Round Lot Size"`: single value `100.0` for all 2,752 rows.
- Date columns: `Date` in all trade tables (`stockmarket_stocktrade_all`, `stockmarket_cvx`, `stockmarket_cmi`) is stored as `character varying`, sample format `YYYY-MM-DD` (e.g. `2018-08-15`, `1962-01-02`). No timezone indicated.

## Text columns that need reading
- `stockmarket_stockinfo."Company Description"`: free text, 2,752 distinct values (one per row per description.txt: "Company Description (str): Company name and description"); contains company/fund name plus a prose description (e.g. "Perth Mint Physical Gold ETF offers investors an opportunity to buy shares backed by physical gold…"). Answers about company identity, sector, or business activity likely require parsing this field rather than a categorical column.

## Conventions in the description/hints
- description.txt: "stockinfo … contains metadata about publicly traded stocks and ETFs listed on U.S. exchanges, including ticker symbols, market categories, trading venues, and company descriptions."
- description.txt: "stocktrade_database … contains daily price data for 2,753 individual stocks and ETFs … Each table in the database is named after a stock's ticker symbol."
- hints.txt: "A company is considered financially troubled if it is deficient, delinquent, or both."
- hints.txt lists exact Listing Exchange and Financial Status code definitions as quoted above.

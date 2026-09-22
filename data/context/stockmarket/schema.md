# stockmarket — schema

Postgres schema `dataagentbench`; every table is `stockmarket_<table>`.

## store `stockinfo_database`

### `stockmarket_stockinfo` — 2,752 rows (source table `stockinfo`)

| column | type |
|---|---|
| Nasdaq Traded | character varying |
| Symbol | character varying |
| Listing Exchange | character varying |
| Market Category | character varying |
| ETF | character varying |
| Round Lot Size | double precision |
| Test Issue | character varying |
| Financial Status | character varying |
| NextShares | character varying |
| Company Description | character varying |

## store `stocktrade_database`

### family of 2,715 tables with identical columns (e.g. `stockmarket_cvx`, 14,663 rows; members: `stockmarket_aaau`, `stockmarket_aadr`, `stockmarket_aame`, `stockmarket_aaww`, `stockmarket_aaxj`, `stockmarket_abeq`, `stockmarket_abmd`, `stockmarket_acad`, …)
Query them together through `stockmarket_stocktrade_all`: the same columns plus `_table` (the member name without the `stockmarket_` prefix, e.g. the ticker).

| column | type |
|---|---|
| Date | character varying |
| Open | double precision |
| High | double precision |
| Low | double precision |
| Close | double precision |
| Adj Close | double precision |
| Volume | bigint |

### family of 38 tables with identical columns (e.g. `stockmarket_cmi`, 11,885 rows; members: `stockmarket_adp`, `stockmarket_bpopn`, `stockmarket_cae`, `stockmarket_cma`, `stockmarket_cmi`, `stockmarket_edow`, `stockmarket_einc`, `stockmarket_ev`, …)
Query them together through `stockmarket_stocktrade_all`: the same columns plus `_table` (the member name without the `stockmarket_` prefix, e.g. the ticker).

| column | type |
|---|---|
| Date | character varying |
| Open | double precision |
| High | double precision |
| Low | double precision |
| Close | double precision |
| Adj Close | double precision |
| Volume | double precision |

### `stockmarket_stocktrade_all` — 6,236,194 rows (source table `*(2715 tables)`)

| column | type |
|---|---|
| _table | text |
| Date | character varying |
| Open | double precision |
| High | double precision |
| Low | double precision |
| Close | double precision |
| Adj Close | double precision |
| Volume | bigint |


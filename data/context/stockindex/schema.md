# stockindex — schema

Postgres schema `dataagentbench`; every table is `stockindex_<table>`.

## store `indexinfo_database`

### `stockindex_index_info` — 14 rows (source table `index_info`)

| column | type |
|---|---|
| Exchange | character varying |
| Currency | character varying |

## store `indextrade_database`

### `stockindex_index_trade` — 104,224 rows (source table `index_trade`)

| column | type |
|---|---|
| Index | character varying |
| Date | character varying |
| Open | double precision |
| High | double precision |
| Low | double precision |
| Close | double precision |
| Adj Close | double precision |
| CloseUSD | double precision |


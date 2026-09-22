# music_brainz_20k — schema

Postgres schema `dataagentbench`; every table is `music_brainz_20k_<table>`.

## store `sales_database`

### `music_brainz_20k_sales` — 58,049 rows (source table `sales`)

| column | type |
|---|---|
| sale_id | integer |
| track_id | integer |
| country | character varying |
| store | character varying |
| units_sold | integer |
| revenue_usd | double precision |

## store `tracks_database`

### `music_brainz_20k_tracks` — 19,375 rows (source table `tracks`)

| column | type |
|---|---|
| track_id | bigint |
| source_id | bigint |
| source_track_id | character varying |
| title | character varying |
| artist | character varying |
| album | character varying |
| year | character varying |
| length | character varying |
| language | character varying |


# googlelocal — schema

Postgres schema `dataagentbench`; every table is `googlelocal_<table>`.

## store `business_database`

### `googlelocal_business_description` — 79 rows (source table `business_description`)

| column | type |
|---|---|
| name | text |
| gmap_id | text |
| description | text |
| num_of_reviews | bigint |
| hours | text |
| MISC | text |
| state | text |

## store `review_database`

### `googlelocal_review` — 2,000 rows (source table `review`)

| column | type |
|---|---|
| name | character varying |
| time | character varying |
| rating | bigint |
| text | character varying |
| gmap_id | character varying |


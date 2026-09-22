# yelp — schema

Postgres schema `dataagentbench`; every table is `yelp_<table>`.

## store `businessinfo_database`

### `yelp_business` — 100 rows (source table `business`)

| column | type |
|---|---|
| _id | text |
| business_id | text |
| name | text |
| review_count | bigint |
| is_open | bigint |
| attributes | jsonb |
| hours | jsonb |
| description | text |
| doc | jsonb |

### `yelp_checkin` — 90 rows (source table `checkin`)

| column | type |
|---|---|
| _id | text |
| business_id | text |
| date | text |
| doc | jsonb |

## store `user_database`

### `yelp_review` — 2,000 rows (source table `review`)

| column | type |
|---|---|
| review_id | character varying |
| user_id | character varying |
| business_ref | character varying |
| rating | bigint |
| useful | bigint |
| funny | bigint |
| cool | bigint |
| text | character varying |
| date | character varying |

### `yelp_tip` — 784 rows (source table `tip`)

| column | type |
|---|---|
| user_id | character varying |
| business_ref | character varying |
| text | character varying |
| date | character varying |
| compliment_count | bigint |

### `yelp_user` — 1,999 rows (source table `user`)

| column | type |
|---|---|
| user_id | character varying |
| name | character varying |
| review_count | bigint |
| yelping_since | character varying |
| useful | bigint |
| funny | bigint |
| cool | bigint |
| elite | character varying |


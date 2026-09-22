# bookreview — schema

Postgres schema `dataagentbench`; every table is `bookreview_<table>`.

## store `books_database`

### `bookreview_books_info` — 200 rows (source table `books_info`)

| column | type |
|---|---|
| title | text |
| subtitle | text |
| author | text |
| rating_number | bigint |
| features | text |
| description | text |
| price | double precision |
| store | text |
| categories | text |
| details | text |
| book_id | text |

## store `review_database`

### `bookreview_review` — 1,833 rows (source table `review`)

| column | type |
|---|---|
| rating | bigint |
| title | character varying |
| text | character varying |
| review_time | character varying |
| helpful_vote | bigint |
| verified_purchase | bigint |
| purchase_id | character varying |


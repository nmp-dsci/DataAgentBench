# agnews — schema

Postgres schema `dataagentbench`; every table is `agnews_<table>`.

## store `articles_database`

### `agnews_articles` — 127,600 rows (source table `articles`)

| column | type |
|---|---|
| article_id | bigint |
| title | text |
| description | text |
| doc | jsonb |

## store `metadata_database`

### `agnews_article_metadata` — 127,600 rows (source table `article_metadata`)

| column | type |
|---|---|
| article_id | bigint |
| author_id | bigint |
| region | character varying |
| publication_date | character varying |

### `agnews_authors` — 994 rows (source table `authors`)

| column | type |
|---|---|
| author_id | bigint |
| name | character varying |


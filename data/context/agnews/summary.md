# agnews — orientation summary

## Shape

- Two stores, three tables, all Postgres schema `dataagentbench`, table names `agnews_<table>`.
- `articles_database` (source: MongoDB `articles` collection):
  - `agnews_articles` — 127,600 rows. Columns: `article_id` (bigint), `title` (text), `description` (text), `doc` (jsonb). One row per article. Per description.txt, this is "the primary source for the content of each article, including its title and description."
- `metadata_database` (source: SQLite):
  - `agnews_article_metadata` — 127,600 rows. Columns: `article_id` (bigint), `author_id` (bigint), `region` (varchar), `publication_date` (varchar). One row per article, links article to author, region, and date.
  - `agnews_authors` — 994 rows. Columns: `author_id` (bigint), `name` (varchar). One row per author.
- Largest tables: `agnews_articles` and `agnews_article_metadata` (127,600 rows each, 1:1 by `article_id`). `agnews_authors` is small (994 rows) and joined in via `agnews_article_metadata`.

## Keys and joins

- `agnews_articles."article_id"` ↔ `agnews_article_metadata."article_id"` — joins.md: distinct A = 127,600; raw share 1.0, normalised share 1.0, digits-only share 1.0. No cleaning needed; direct bigint-to-bigint equi-join.
- `agnews_article_metadata."author_id"` ↔ `agnews_authors."author_id"` — joins.md: distinct A = 994; raw share 1.0, normalised share 1.0, digits-only share 1.0. No cleaning needed; direct bigint-to-bigint equi-join.

## Literal values

- `agnews_article_metadata.region` — 5 distinct values, exact spellings (profile top values): `Asia` (25,718), `North America` (25,608), `Africa` (25,501), `Europe` (25,432), `South America` (25,341). Match these strings exactly (case, spacing).
- `agnews_article_metadata.publication_date` — stored as `character varying` (text, not a date type), 6,802 distinct values. description.txt states format is "Publication date in the format YYYY-MM-DD"; sample rows confirm e.g. `2022-09-18`, `2004-03-20`. No timezone indicated anywhere in the material.
- No other categorical/code columns are profiled (`article_id`, `author_id` are plain integer identifiers with no prefix per profile min/max `0`–`127599` and `0`–`993`).

## Text columns that need reading

- `agnews_articles.title` — free text, 121,274 distinct values over 127,600 rows (some duplicates). Article headline.
- `agnews_articles.description` — free text, 126,190 distinct values. Short article summary/lede text (sample rows show Reuters/AFP-style snippets).
- `agnews_articles.doc` — jsonb column; schema.md and description.txt do not document its internal keys. Read with `->>` if querying; contents beyond `article_id`/`title`/`description` are not described in the material, so do not assume specific keys exist.

## Conventions in the description/hints

- hints.txt: "Determining an article's category requires understanding the meaning of its title and description."
- hints.txt: "All articles belong to one of four categories: World, Sports, Business, or Science/Technology." — no column stores this category; it is not present in any table per schema.md, so it must be derived from `title`/`description` text.
- description.txt: `article_metadata.article_id` is described as "Article identifier linking to the articles collection" and `article_metadata.author_id` as "Author identifier linking to the authors table" — confirms the two joins above are the intended links.

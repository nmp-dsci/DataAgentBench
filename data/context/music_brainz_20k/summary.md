# music_brainz_20k — Analyst Summary

## Shape

- Two stores, two tables total.
- `music_brainz_20k_sales` (store `sales_database`, source table `sales`) — **58,049 rows**. One row per sale transaction: `sale_id, track_id, country, store, units_sold, revenue_usd`.
- `music_brainz_20k_tracks` (store `tracks_database`, source table `tracks`) — **19,375 rows**. One row per track record: `track_id, source_id, source_track_id, title, artist, album, year, length, language`.
- `music_brainz_20k_sales` is the larger table (58,049 rows) and the two tables are joined via `track_id` — this is the only join in the dataset (see joins.md).

## Keys and joins

- **Join:** `music_brainz_20k_sales."track_id"` → `music_brainz_20k_tracks."track_id"`.
  - joins.md: distinct A = 19,375; raw share = 1.0; normalised share = 1.0; digits-only share = 1.0.
  - Both columns are numeric (`integer` in sales, `bigint` in tracks) covering 1–19,375 in both tables per profile.json min/max — no prefix-stripping or casing fix needed for this join.

## Literal values

- `music_brainz_20k_sales.country` — 5 distinct values (profile top list): `France` (11,712), `Canada` (11,684), `UK` (11,589), `Germany` (11,549), `USA` (11,515). Hints confirm the same five: "records sales in five countries: USA, UK, Canada, Germany, and France."
- `music_brainz_20k_sales.store` — 5 distinct values: `Google Play` (11,748), `iTunes` (11,635), `Apple Music` (11,622), `Spotify` (11,549), `Amazon Music` (11,495). Hints confirm: "five platforms or stores: iTunes, Spotify, Apple Music, Amazon Music, and Google Play."
- `music_brainz_20k_tracks.source_id` — bigint, 5 distinct values, range 1–5 (min/max in profile.json). No label mapping to source names is present in the schema or samples — only the numeric id.
- `music_brainz_20k_tracks.year` — stored as `character varying` (text, not a date type), 37.98% null. Sample rows show inconsistent formats: `"75"`, `NULL`, `"95"`, `"2005"`, `"2010"` — i.e. some 2-digit, some 4-digit strings.
- `music_brainz_20k_tracks.length` — stored as `character varying`, 5.43% null. Sample rows show mixed formats: `"219"` (raw seconds, presumably), `"1m 58sec"`, `"unk."`, `"321266"`. Not a uniform unit or format.
- No date/timestamp columns exist in either table (no `created_at`, `date`, etc. in schema.md).

## Text columns that need reading

- `music_brainz_20k_tracks.title` — track title text, 0.35% null, 18,967 distinct values out of 19,375 rows.
- `music_brainz_20k_tracks.artist` — artist/band name, 20.94% null, 8,994 distinct values.
- `music_brainz_20k_tracks.album` — album name, 19.66% null, 11,765 distinct values.
- `music_brainz_20k_tracks.language` — language string, 23.13% null, 667 distinct values; sample values include full names (`French`, `English`) and abbreviations (`Por.`), so spellings are not standardized.
- No JSON/JSONB columns exist in either table per schema.md.

## Conventions in the description/hints

- description.txt: "tracks ... This table contains all the tracks, including potential duplicates generated from different sources. Each row represents a single track record with a unique track_id."
- description.txt: "sales ... Each row represents a single sale record for a specific track_id."
- hints.txt: "The `tracks` table may contain duplicate entries. Different `track_id`s can represent the same real-world track. To answer queries correctly, you need to perform **entity resolution** by comparing track attributes such as `title`, `artist`, `album`, `year`, etc. Note that duplicates may not match exactly (e.g., different year formats or minor attribute variations), so you must reason about the meaning of these attributes rather than relying on exact string equality for entity resolution."
- hints.txt: "The `sales` table records sales in five countries: USA, UK, Canada, Germany, and France."
- hints.txt: "Sales occur across five platforms or stores: iTunes, Spotify, Apple Music, Amazon Music, and Google Play."

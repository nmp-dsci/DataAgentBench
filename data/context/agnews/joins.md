# agnews — measured join overlaps

Share of distinct values of column A found in column B: raw, after `trim`/`#`-strip/lower-case, and on the digits alone (for keys that differ only by a textual prefix). Measured on the live tables (sampled above 200k rows). A share near 1.0 is a usable join key; a normalised share much higher than raw means the keys need cleaning first.

| A | B | distinct A | raw share | normalised share | digits-only share |
|---|---|---|---|---|---|
| agnews_articles."article_id" | agnews_article_metadata."article_id" | 127,600 | 1.0 | 1.0 | 1.0 |
| agnews_article_metadata."author_id" | agnews_authors."author_id" | 994 | 1.0 | 1.0 | 1.0 |

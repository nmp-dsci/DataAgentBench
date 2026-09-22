# googlelocal — measured join overlaps

Share of distinct values of column A found in column B: raw, after `trim`/`#`-strip/lower-case, and on the digits alone (for keys that differ only by a textual prefix). Measured on the live tables (sampled above 200k rows). A share near 1.0 is a usable join key; a normalised share much higher than raw means the keys need cleaning first.

| A | B | distinct A | raw share | normalised share | digits-only share |
|---|---|---|---|---|---|
| googlelocal_business_description."gmap_id" | googlelocal_review."gmap_id" | 79 | 1.0 | 1.0 | 1.0 |
| googlelocal_business_description."name" | googlelocal_review."name" | 79 | 0.0127 | 0.0127 | 0.1667 |

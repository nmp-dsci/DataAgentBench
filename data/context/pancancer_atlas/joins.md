# pancancer_atlas — measured join overlaps

Share of distinct values of column A found in column B: raw, after `trim`/`#`-strip/lower-case, and on the digits alone (for keys that differ only by a textual prefix). Measured on the live tables (sampled above 200k rows). A share near 1.0 is a usable join key; a normalised share much higher than raw means the keys need cleaning first.

| A | B | distinct A | raw share | normalised share | digits-only share |
|---|---|---|---|---|---|
| pancancer_atlas_mutation_data."ParticipantBarcode" | pancancer_atlas_rnaseq_expression."ParticipantBarcode" | 8,017 | 0.5034 | 0.5092 | 0.5204 |

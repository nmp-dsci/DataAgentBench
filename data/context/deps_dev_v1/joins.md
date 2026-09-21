# deps_dev_v1 — measured join overlaps

Share of distinct values of column A found in column B: raw, after `trim`/`#`-strip/lower-case, and on the digits alone (for keys that differ only by a textual prefix). Measured on the live tables (sampled above 200k rows). A share near 1.0 is a usable join key; a normalised share much higher than raw means the keys need cleaning first.

| A | B | distinct A | raw share | normalised share | digits-only share |
|---|---|---|---|---|---|
| deps_dev_v1_packageinfo."System" | deps_dev_v1_project_packageversion."System" | 1 | 1.0 | 1.0 | 0.0 |
| deps_dev_v1_packageinfo."Name" | deps_dev_v1_project_packageversion."Name" | 9,957 | 0.8395 | 0.851 | 0.9109 |
| deps_dev_v1_packageinfo."Version" | deps_dev_v1_project_packageversion."Version" | 18,287 | 0.7975 | 0.7975 | 0.8393 |
| deps_dev_v1_packageinfo."Licenses" | deps_dev_v1_project_info."Licenses" | 47 | 0.234 | 0.2444 | 0.2 |

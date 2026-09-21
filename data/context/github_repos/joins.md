# github_repos — measured join overlaps

Share of distinct values of column A found in column B: raw, after `trim`/`#`-strip/lower-case, and on the digits alone (for keys that differ only by a textual prefix). Measured on the live tables (sampled above 200k rows). A share near 1.0 is a usable join key; a normalised share much higher than raw means the keys need cleaning first.

| A | B | distinct A | raw share | normalised share | digits-only share |
|---|---|---|---|---|---|
| github_repos_files."repo_name" | github_repos_repos."repo_name" | 24,566 | 0.496 | 0.5078 | 0.8299 |
| github_repos_commits."repo_name" | github_repos_files."repo_name" | 6 | 0.6667 | 0.5 | 0.0 |
| github_repos_commits."repo_name" | github_repos_repos."repo_name" | 6 | 0.6667 | 0.5 | 0.0 |
| github_repos_languages."repo_name" | github_repos_licenses."repo_name" | 196,061 | 0.0601 | 0.0612 | 0.4056 |
| github_repos_files."repo_name" | github_repos_licenses."repo_name" | 24,749 | 0.0528 | 0.0532 | 0.6837 |
| github_repos_files."repo_name" | github_repos_languages."repo_name" | 25,796 | 0.0522 | 0.0531 | 0.7033 |
| github_repos_licenses."repo_name" | github_repos_repos."repo_name" | 192,436 | 0.0255 | 0.0254 | 0.2841 |
| github_repos_languages."repo_name" | github_repos_repos."repo_name" | 197,300 | 0.0242 | 0.0249 | 0.2927 |
| github_repos_commits."repo_name" | github_repos_languages."repo_name" | 6 | 0.0 | 0.0 | 0.0 |
| github_repos_commits."repo_name" | github_repos_licenses."repo_name" | 6 | 0.0 | 0.0 | 0.0 |
| github_repos_contents."id" | github_repos_files."ref" | 24,286 | 0.0 | 0.0 | 0.0 |

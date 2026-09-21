## Shape

Two stores. `metadata_database` (originally SQLite) holds repo-level metadata: `github_repos_languages` (3,325,634 rows), `github_repos_licenses` (3,325,634 rows), `github_repos_repos` (400,000 rows) — all keyed on `repo_name` but, per joins.md, these three barely overlap with each other or with the artifact tables.

`artifacts_database` (originally DuckDB) holds repo artifacts: `github_repos_commits` (17,976 rows), `github_repos_contents` (24,286 rows), `github_repos_files` (524,077 rows, the largest artifact table).

`github_repos_commits` covers only 6 distinct `repo_name` values (top values: torvalds/linux 16,061; apple/swift 1,051; twbs/bootstrap 340; Microsoft/vscode 190; facebook/react 178; tensorflow/tensorflow 156) — it is effectively a Linux-kernel-dominated sample, not a general commit table.

`github_repos_files` is the most-joined artifact table (joins.md pairs it with `repos`, `languages`, `licenses`, and `commits`). `github_repos_contents` joins to nothing else measured usably (`contents.id` vs `files.ref` share = 0.0).

## Keys and joins

- `github_repos_files."repo_name"` ↔ `github_repos_repos."repo_name"`: distinct A = 24,566; raw share 0.496; normalised (trim/`#`-strip/lower-case) share 0.5078; digits-only share 0.8299. Digits-only being much higher than raw/normalised implies many keys differ by more than case/whitespace (e.g. differing owner segments), so this join recovers at most ~83% even after aggressive normalisation — treat as partial.
- `github_repos_commits."repo_name"` ↔ `github_repos_files."repo_name"`: distinct A = 6; raw share 0.6667; normalised 0.5; digits-only 0.0. Only 4 of the 6 commit repos have any raw match in `files`.
- `github_repos_commits."repo_name"` ↔ `github_repos_repos."repo_name"`: same as above (0.6667 raw, 0.5 normalised, 0.0 digits-only).
- `github_repos_languages."repo_name"` ↔ `github_repos_licenses."repo_name"`: raw share 0.0601; normalised 0.0612; digits-only 0.4056. Even normalised, only ~6% match; this is a weak join.
- `github_repos_files."repo_name"` ↔ `github_repos_licenses."repo_name"`: raw 0.0528; normalised 0.0532; digits-only 0.6837.
- `github_repos_files."repo_name"` ↔ `github_repos_languages."repo_name"`: raw 0.0522; normalised 0.0531; digits-only 0.7033.
- `github_repos_licenses."repo_name"` ↔ `github_repos_repos."repo_name"`: raw 0.0255; normalised 0.0254; digits-only 0.2841.
- `github_repos_languages."repo_name"` ↔ `github_repos_repos."repo_name"`: raw 0.0242; normalised 0.0249; digits-only 0.2927.
- `github_repos_commits."repo_name"` ↔ `github_repos_languages."repo_name"` and ↔ `github_repos_licenses."repo_name"`: 0.0 on all three measures — no usable join.
- `github_repos_contents."id"` ↔ `github_repos_files."ref"`: 0.0 on all three measures — no usable join (this is not the intended link between `contents` and `files`; no other join between them is measured in joins.md).

No join column pair reaches a raw share near 1.0 in joins.md; all measured joins are partial. Where digits-only share is much higher than raw/normalised (e.g. `files`↔`repos`, `files`↔`languages`, `files`↔`licenses`), the mismatch is driven by more than trim/case — do not assume normalisation alone will fix it.

## Literal values

- `github_repos_licenses.license`: exact lowercase identifiers. Top values (profiled): mit (104,879), apache-2.0 (29,762), gpl-3.0 (21,852), gpl-2.0 (20,487), bsd-3-clause (6,924), bsd-2-clause (3,276), unlicense (2,486), lgpl-3.0 (2,189), agpl-3.0 (2,170), cc0-1.0 (1,637). 15 distinct values total (sampled).
- `github_repos_commits.encoding`: mostly NULL (null_rate 0.9996). Top non-null values: ISO-8859-1 (6), ISO-8859-2 (1).
- `github_repos_commits.repo_name`: exactly 6 distinct owner/repo strings (listed above); this is the full set of repos in the commits table.
- `github_repos_files.mode`: bigint, values range 33188–57344 (4 distinct values, sampled); this is a POSIX file-mode integer, not a boolean or descriptive field.
- No date/timestamp column type exists in the schema; timestamp data appears only inside JSON-like text fields (see below), not as typed date columns.

## Text columns that need reading

- `github_repos_commits.author` and `.committer`: JSON-like text containing `date` (microseconds), `email`, `name`, `time_sec` (unix seconds), `tz_offset` (minutes). Per sample rows, `email` values here are hashed/obfuscated hex strings, not literal addresses.
- `github_repos_commits.parent`: JSON-like array of parent commit SHA strings (more than one entry for merge commits, per description.txt).
- `github_repos_commits.trailer`: JSON-like array of objects with `email`, `key` (e.g. "Signed-off-by"), `value`.
- `github_repos_commits.difference`: JSON-like array of objects with `new_mode`, `new_path`, `new_sha1`, `old_mode`, `old_path`, `old_sha1` — the actual file-change data for the commit.
- `github_repos_commits.message`: full free-text commit message (subject is the short line; message is the full text).
- `github_repos_contents.content`: raw file text content (null_rate 0.1576; description.txt notes large/binary files may be placeholders or truncated).
- `github_repos_contents.repo_data_description`: natural-language sentence summarizing size, binary flag, copy count, and mode, e.g. "Non-binary content file (1455 bytes) seen 8 times, using sample mode 33188." Per hints.txt: "The 'contents' table's repo_data_description field contains natural language metadata derived from file attributes (e.g., size, binary, copies, mode). Some queries may rely on these attributes for filtering or interpretation."
- `github_repos_languages.language_description`: natural-language sentence listing languages and byte counts, e.g. "The codebase includes: Ruby (22,438 bytes), Shell (465 bytes)." Per hints.txt: "The 'languages' table's language_description field may contain multiple programming languages per repository. To determine the primary or main language, compare the relative number of bytes across languages."

## Conventions in description/hints

- Repo name format, stated for every table that has it: "Name of the GitHub repository in `owner/repo` format."
- Primary language rule (hints.txt): "To determine the primary or main language, compare the relative number of bytes across languages."
- `repo_data_description` provenance (description.txt): "Natural language description summarizing the file's metadata (derived from original size, binary, copies, and mode fields)."
- Join guidance (hints.txt): "Some queries may require joining across tables using identifiers such as 'id' or 'repo_name' to correctly combine information."
- `difference_truncated` is documented in description.txt as a bool ("Indicator if the difference data is truncated"), but schema.md types it as `double precision` and profile.json shows null_rate 1.0 (always null in this dataset).

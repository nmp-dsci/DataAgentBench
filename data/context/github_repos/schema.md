# github_repos — schema

Postgres schema `dataagentbench`; every table is `github_repos_<table>`.

## store `artifacts_database`

### `github_repos_commits` — 17,976 rows (source table `commits`)

| column | type |
|---|---|
| commit | character varying |
| tree | character varying |
| parent | character varying |
| author | character varying |
| committer | character varying |
| subject | character varying |
| message | character varying |
| trailer | character varying |
| difference | character varying |
| difference_truncated | double precision |
| repo_name | character varying |
| encoding | character varying |

### `github_repos_contents` — 24,286 rows (source table `contents`)

| column | type |
|---|---|
| id | character varying |
| content | character varying |
| sample_repo_name | character varying |
| sample_ref | character varying |
| sample_path | character varying |
| sample_symlink_target | character varying |
| repo_data_description | character varying |

### `github_repos_files` — 524,077 rows (source table `files`)

| column | type |
|---|---|
| repo_name | character varying |
| ref | character varying |
| path | character varying |
| mode | bigint |
| id | character varying |
| symlink_target | character varying |

## store `metadata_database`

### `github_repos_languages` — 3,325,634 rows (source table `languages`)

| column | type |
|---|---|
| repo_name | character varying |
| language_description | character varying |

### `github_repos_licenses` — 3,325,634 rows (source table `licenses`)

| column | type |
|---|---|
| repo_name | character varying |
| license | character varying |

### `github_repos_repos` — 400,000 rows (source table `repos`)

| column | type |
|---|---|
| repo_name | character varying |
| watch_count | bigint |


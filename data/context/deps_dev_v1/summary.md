# deps_dev_v1 — summary

## 1. Shape
- Two logical stores: `package_database` (1 table) and `project_database` (2 tables). All are Postgres tables `deps_dev_v1_<table>`.
- `deps_dev_v1_packageinfo` — 661,372 rows. Package metadata: system, name, version, licenses, links, advisories, version/hash JSON, dependency flags, upstream publish time.
- `deps_dev_v1_project_packageversion` — 597,602 rows. Maps a package (System/Name/Version) to a GitHub/GitLab/Bitbucket project (`ProjectName`).
- `deps_dev_v1_project_info` — 770 rows. One row per project with a free-text description sentence, license array, description, homepage.
- `deps_dev_v1_packageinfo` and `deps_dev_v1_project_packageversion` are the largest and are the ones joined together (per hints.txt); `deps_dev_v1_project_info` is small and joined in afterward via `ProjectName`.

## 2. Keys and joins
- Per hints.txt: "match package records in \"packageinfo\" from \"package_database\" with records in \"project_packageversion\" from \"project_database\" using the shared attributes \"System\", \"Name\", and \"Version\". Then, take the \"ProjectName\" from \"project_packageversion\" and use it to find the corresponding record in \"project_info\"."
- `deps_dev_v1_packageinfo."System"` ↔ `deps_dev_v1_project_packageversion."System"`: distinct A = 1, raw share 1.0, normalised share 1.0, digits-only share 0.0 (both sides are exclusively "NPM" per profile top values). Clean 1:1 match, no normalization needed.
- `deps_dev_v1_packageinfo."Name"` ↔ `deps_dev_v1_project_packageversion."Name"`: distinct A = 9,957, raw share 0.8395, normalised (trim/case-fold) share 0.851, digits-only share 0.9109. Normalisation improves overlap only modestly; join is not fully clean even after cleaning.
- `deps_dev_v1_packageinfo."Version"` ↔ `deps_dev_v1_project_packageversion."Version"`: distinct A = 18,287, raw share 0.7975, normalised share 0.7975 (no change), digits-only share 0.8393. Version strings do not benefit from trim/case-fold normalisation; a meaningful fraction of versions never match.
- `deps_dev_v1_packageinfo."Licenses"` ↔ `deps_dev_v1_project_info."Licenses"`: distinct A = 47, raw share 0.234, normalised share 0.2444, digits-only share 0.2. Low overlap in all forms — these two Licenses columns are not a reliable join/match key, only comparable as values.
- There is no direct key column linking `deps_dev_v1_project_packageversion` to `deps_dev_v1_project_info`; the link is via `ProjectName` (project_packageversion) to the project name embedded inside `Project_Information` text (project_info) — joins.md does not measure this pairing's overlap.

## 3. Literal values
- `deps_dev_v1_packageinfo."System"`: single observed value "NPM" (201,240 of profiled rows, distinct=1).
- `deps_dev_v1_project_packageversion."System"`: single observed value "NPM" (199,609 of profiled rows, distinct=1).
- `deps_dev_v1_project_packageversion."ProjectType"`: top values "GITHUB" (198,500), "GITLAB" (1,060), "BITBUCKET" (997); distinct=3.
- `deps_dev_v1_project_packageversion."RelationProvenance"`: top values "UNVERIFIED_METADATA" (196,120), "SLSA_ATTESTATION" (18); distinct=2.
- `deps_dev_v1_project_packageversion."RelationType"`: top values "ISSUE_TRACKER_TYPE" (103,352), "SOURCE_REPO_TYPE" (95,383); distinct=2.
- `deps_dev_v1_packageinfo."Advisories"`: top values are the JSON-array literal "[]" (201,414) and a single-advisory example JSON block containing `"Source": "OSV"`; distinct=2 in profile sample.
- `deps_dev_v1_packageinfo."Registries"`: single observed value "[]" (200,382), distinct=1.
- `deps_dev_v1_packageinfo."UpstreamIdentifiers"`: single observed value "[]" (198,890), distinct=1.
- `deps_dev_v1_project_info."Licenses"`: top values include `["MIT"]` (520), `[]` (123), `["non-standard"]` (58), `["Apache-2.0"]` (32), `["ISC"]` (14), `["BSD-3-Clause"]` (10), `["GPL-3.0"]` (6), `["AGPL-3.0"]` (3), `["GPL-2.0"]` (2), `["EPL-2.0"]` (1). Values are JSON-array-formatted strings, not bare license names.
- `deps_dev_v1_packageinfo."DependenciesProcessed"` and `"DependencyError"`: bigint flags, min 0 / max 1 (boolean-as-integer per description.txt).
- `deps_dev_v1_packageinfo."UpstreamPublishedAt"`: double precision, described as "Unix timestamp (ms)" but sample/profile values (e.g. 1699345351000000.0, range min 1430493994000000.0 / max 1700494988000000.0) are 16-digit numbers — larger than milliseconds-since-epoch would produce; exact unit is not confirmed beyond description.txt's "ms" label, and the profile's stored magnitude does not match plain ms.

## 4. Text columns that need reading
- `deps_dev_v1_project_info."Project_Information"`: free-text sentence per project, e.g. "The project leaflet/leaflet on GitHub is a popular open-source library that currently has 521 open issues, 38715 stars, and 5782 forks…". Per hints.txt: "The 'Project_Information' field in 'project_info' contains the project name as well as important repository metrics such as GitHub stars count and fork count, along with other descriptive details." Stars/forks/issues counts must be extracted from this sentence — there are no separate numeric columns for them.
- `deps_dev_v1_project_info."Description"`: separate short free-text project description (e.g. "🍃 JavaScript library for mobile-friendly interactive maps 🇺🇦"), distinct from `Project_Information`.
- `deps_dev_v1_packageinfo."Licenses"`, `"Links"`, `"Advisories"`, `"VersionInfo"`, `"Hashes"`, `"Registries"`, `"UpstreamIdentifiers"`: all JSON-like array/object strings per description.txt (e.g. VersionInfo holds `{"IsRelease": ..., "Ordinal": ...}`; Links holds a list of `{"Label":..., "URL":...}`); values must be parsed out of the JSON text, not matched as flat strings.

## 5. Conventions in the description/hints
- description.txt: "package_database … is stored in SQLite database format" and "project_database … is stored in DuckDB format" (original source formats, now materialized as Postgres tables here).
- description.txt: "DependenciesProcessed (bool): Whether dependencies have been processed successfully" and "DependencyError (bool): Whether a dependency processing error occurred" — stored as bigint 0/1 in this table.
- description.txt: "UpstreamPublishedAt (float): Unix timestamp (ms) for when the upstream release was published."
- hints.txt join path (quoted above in section 2) is the only stated join procedure across all three tables.

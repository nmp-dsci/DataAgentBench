# deps_dev_v1 — schema

Postgres schema `dataagentbench`; every table is `deps_dev_v1_<table>`.

## store `package_database`

### `deps_dev_v1_packageinfo` — 661,372 rows (source table `packageinfo`)

| column | type |
|---|---|
| System | character varying |
| Name | character varying |
| Version | character varying |
| Licenses | character varying |
| Links | character varying |
| Advisories | character varying |
| VersionInfo | character varying |
| Hashes | character varying |
| DependenciesProcessed | bigint |
| DependencyError | bigint |
| UpstreamPublishedAt | double precision |
| Registries | character varying |
| SLSAProvenance | double precision |
| UpstreamIdentifiers | character varying |
| Purl | double precision |

## store `project_database`

### `deps_dev_v1_project_info` — 770 rows (source table `project_info`)

| column | type |
|---|---|
| Project_Information | character varying |
| Licenses | character varying |
| Description | character varying |
| Homepage | character varying |
| OSSFuzz | double precision |

### `deps_dev_v1_project_packageversion` — 597,602 rows (source table `project_packageversion`)

| column | type |
|---|---|
| System | character varying |
| Name | character varying |
| Version | character varying |
| ProjectType | character varying |
| ProjectName | character varying |
| RelationProvenance | character varying |
| RelationType | character varying |


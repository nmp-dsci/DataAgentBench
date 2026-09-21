# patents — schema

Postgres schema `dataagentbench`; every table is `patents_<table>`.

## store `CPCDefinition_database`

### `patents_cpc_definition` — 260,808 rows (source table `cpc_definition`)

| column | type |
|---|---|
| applicationReferences | text |
| breakdownCode | boolean |
| childGroups | text |
| children | text |
| dateRevised | double precision |
| definition | text |
| glossary | text |
| informativeReferences | text |
| ipcConcordant | text |
| level | double precision |
| limitingReferences | text |
| notAllocatable | boolean |
| parents | text |
| precedenceLimitingReferences | text |
| residualReferences | text |
| rules | text |
| scopeLimitingReferences | text |
| status | text |
| symbol | text |
| synonyms | text |
| titleFull | text |
| titlePart | text |

## store `publication_database`

### `patents_publicationinfo` — 277,813 rows (source table `publicationinfo`)

| column | type |
|---|---|
| Patents_info | character varying |
| kind_code | character varying |
| application_kind | character varying |
| pct_number | character varying |
| family_id | bigint |
| title_localized | character varying |
| abstract_localized | character varying |
| claims_localized_html | character varying |
| description_localized_html | character varying |
| publication_date | character varying |
| filing_date | character varying |
| grant_date | character varying |
| priority_date | character varying |
| priority_claim | character varying |
| inventor_harmonized | character varying |
| examiner | character varying |
| uspc | character varying |
| ipc | character varying |
| cpc | character varying |
| citation | character varying |
| parent | character varying |
| child | character varying |
| entity_status | character varying |
| art_unit | character varying |


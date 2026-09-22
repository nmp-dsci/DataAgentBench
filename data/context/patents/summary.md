## Shape
Two stores, one table each.

- **CPCDefinition_database** → `patents_cpc_definition` — 260,808 rows. One row per CPC symbol (hierarchy level, definitions, parent/child symbol lists). Key columns: `symbol` (the CPC code), `titleFull`/`titlePart` (descriptive title), `level`, `status`, `parents`/`childGroups`/`children` (JSON-like text lists of related symbols).
- **publication_database** → `patents_publicationinfo` — 277,813 rows. One row per patent publication. `Patents_info` is a free-text summary; `cpc` holds a JSON-like list of CPC classification entries per patent (code, `first`, `inventive`, `tree`); dates (`publication_date`, `filing_date`, `grant_date`, `priority_date`) are natural-language text strings, not typed dates.

No table-level join-frequency or "most joined" statistics are given beyond what the hints describe; the only cross-store relationship documented is `publicationinfo.cpc` → `cpc_definition.symbol` (see below). `patents_publicationinfo` is the larger table (277,813 rows vs 260,808) and is described as the record-per-patent table, so it is the natural anchor for patent-level questions.

## Keys and joins
- **`patents_publicationinfo.cpc` → `patents_cpc_definition.symbol`**: per hints.txt, "The `cpc` field in the `publicationinfo` table ... contains CPC classification codes. The full definitions for these CPC codes are located in the `cpc_definition` table ..., where each row includes fields such as `symbol` and `titleFull`." `cpc` is not a scalar code — it is a JSON-like text array of objects, each with keys `code`, `first`, `inventive`, `tree` (see samples: `[{"code": "H01M10/0566", "first": false, "inventive": true, "tree": []}, ...]`). To join, the individual `code` values inside that array must be extracted and matched against `cpc_definition.symbol`.
- **joins.md contains no populated rows** — no measured raw/normalised/digits-only overlap percentages are provided for any column pair in this dataset. Do not assume a specific overlap percentage; none is documented.
- No other join keys (e.g., linking `citation`, `parent`, `child` to other rows of `patents_publicationinfo`) are documented with measured overlaps; those fields are described only as free text/JSON-like lists of related application or publication numbers (see below).

## Literal values
- `patents_cpc_definition.status`: values `published` (199,355) and `frozen` (168) — exact case matters.
- `patents_cpc_definition.breakdownCode`, `notAllocatable`: booleans stored as `false`/`true` text (`false` 139,391 / `true` 59,501 for breakdownCode; `false` 200,366 / `true` 612 for notAllocatable).
- `patents_cpc_definition.level`: numeric (double precision), range 2.0–19.0, 16 distinct values.
- `patents_cpc_definition.dateRevised`: stored as double precision in `YYYYMMDD.0` numeric form (e.g., `20130101.0`), range 20130101.0–20240501.0, 54 distinct values — this is a numeric-encoded date, not a text or date type, despite description.txt calling it a natural-language string.
- `patents_publicationinfo.application_kind`: coded single letters — top values `A` (178,689), `U` (10,429), `W` (6,762), `T` (4,116), `D` (345), `C` (25), `V` (15), `F` (5), `K` (3), `Q` (3). description.txt's example ("utility patent application") is not the literal stored form — the actual values are single-letter codes.
- `patents_publicationinfo.entity_status`: values `large` (10,776), `small` (2,824), `micro` (179); null in 92.98% of rows.
- `patents_publicationinfo.kind_code`: 61 distinct codes (e.g., `B2` seen in samples); exact code strings, no top-list given beyond distinct count.
- Dates (`publication_date`, `filing_date`, `grant_date`, `priority_date`) are free-form natural-language text, not a fixed format — samples show varied phrasings for the same concept, e.g. "Aug 3rd, 2021", "dated 5th March 2019", "3rd August 2021", "on December 2nd, 2016", "2020, April 7th", "March the 18th, 2019". No consistent parseable pattern is guaranteed; string parsing/normalisation is required, not a single format assumption.

## Text columns that need reading
- `patents_publicationinfo.Patents_info`: natural-language summary text containing application number, publication number, assignee/holder name, and country/status, e.g. "PANASONIC IP MAN CO LTD holds the US patent application (ID US-201916293577-A), with publication number US-11081687-B2." Per hints.txt this field "includes information like `application_number`, `publication_number`, `assignee_harmonized`, and `country_code`" — these are embedded in prose, not separate columns.
- `patents_publicationinfo.cpc`, `ipc`, `citation`, `priority_claim`, `inventor_harmonized`, `examiner`, `parent`, `child`: JSON-like text arrays of objects (e.g., `cpc` entries have `code`, `first`, `inventive`, `tree`; `citation` entries have `application_number`, `category`, `filing_date`, `npl_text`, `publication_number`, `type`). These require JSON-style parsing to extract individual values.
- `patents_publicationinfo.claims_localized_html` / `description_localized_html`: HTML-tagged text (`<claims>`, `<description>`, `<heading>`, `<p>` tags visible in samples) requiring tag-aware extraction to read plain text.
- `patents_publicationinfo.title_localized` / `abstract_localized`: JSON-like text array with `language` and `text` keys (e.g., `[{"language": "en", "text": "..."}]`) — the actual title/abstract string is nested inside.
- `patents_cpc_definition.titleFull`, `titlePart`, `definition`, `glossary`: descriptive free text for the CPC symbol; `titlePart` is itself a JSON-like list of strings (e.g., `["Swine"]`).

## Conventions in the description/hints
- "When counting patent filings per CPC technology area, use only a patent's primary CPC codes (the entries flagged `first = true` in the `cpc` field) and count each patent once per CPC group, even if the same code is listed multiple times."
- "When computing an exponential moving average of filings per year for a CPC group, include every year from the group's first filing year to its last, counting years without filings as zero. If multiple years share the highest average, take the earliest."
- "The `Patents_info` field in the `publicationinfo` table is a natural-language summary that includes information like `application_number`, `publication_number`, `assignee_harmonized`, and `country_code`."
- "Citation information is stored in the `citation` field of the `publicationinfo` table in `publication_database`."

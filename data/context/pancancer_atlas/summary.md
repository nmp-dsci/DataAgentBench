## Shape
- Two stores: `clinical_database` (Postgres) and `molecular_database` (described upstream as DuckDB, but per schema.md all three tables are exposed as Postgres tables under schema `dataagentbench`).
- `pancancer_atlas_clinical_info` — 10,761 rows, one row per patient. Wide table (~100 columns) of demographics, diagnosis, staging, treatment and outcome fields.
- `pancancer_atlas_mutation_data` — 2,127,885 rows. One row per called mutation (gene x sample x variant).
- `pancancer_atlas_rnaseq_expression` — 9,995,877 rows, the largest table. One row per (sample, gene) expression measurement.
- The two molecular tables are the most joined pair (measured in joins.md). `pancancer_atlas_rnaseq_expression` is the largest table by far and likely the most expensive to scan.

## Keys and joins
- **Only join with measured overlap** (joins.md): `pancancer_atlas_mutation_data."ParticipantBarcode"` → `pancancer_atlas_rnaseq_expression."ParticipantBarcode"`.
  - distinct A = 8,017; raw share = 0.5034; normalised (trim/`#`-strip/lower-case) share = 0.5092; digits-only share = 0.5204.
  - The normalised and digits-only shares are only marginally higher than raw, so this is a real ~50% overlap, not a formatting artifact — roughly half of mutation participants have no matching RNA-seq participant (or vice versa), and no cleaning recovers much more.
- **Clinical ↔ molecular join is NOT column-to-column and has no measured overlap in joins.md.** Per hints.txt: "You can match molecular data by 'Patient_description' in clinical_info and 'ParticipantBarcode'." `pancancer_atlas_clinical_info` has no column storing the TCGA barcode directly — the barcode (e.g. `TCGA-31-1953`) appears embedded inside the free-text `Patient_description` column, not as a standalone field. `patient_id` in clinical_info stores only the last numeric segment of the barcode (e.g. `1953`, `0933`), not the full barcode, so it cannot be joined to `ParticipantBarcode` directly without extraction/reconstruction, and no overlap measurement exists to confirm the correct extraction.
- No other joins (e.g. between mutation_data and clinical_info directly) are documented or measured.

## Literal values
- `pancancer_atlas_mutation_data."Variant_Classification"` top values: `Missense_Mutation`, `Nonsense_Mutation`, `Frame_Shift_Del`, `Splice_Site`, `Frame_Shift_Ins`, `In_Frame_Del`, `Translation_Start_Site`, `Nonstop_Mutation`, `In_Frame_Ins`.
- `pancancer_atlas_mutation_data."FILTER"` top values: `PASS`, `wga`, `oxog`, `common_in_exac`, `nonpreferredpair`, `filterr`, `native_wga_mix`, plus comma-joined combinations (e.g. `common_in_exac,wga`).
- `pancancer_atlas_rnaseq_expression."SampleTypeLetterCode"` top values: `TP`, `NT`, `TM`, `TB`, `TR`, `TAP`, `TAM`. `"SampleType"` spells these out, e.g. `Primary solid Tumor`, `Solid Tissue Normal`, `Metastatic`, `Primary Blood Derived Cancer - Peripheral Blood`, `Recurrent Solid Tumor`, `Additional - New Primary`, `Additional Metastatic`.
- `pancancer_atlas_mutation_data."Normal_SampleTypeLetterCode"` top values: `NB`, `NT`, `NBC`.
- `pancancer_atlas_clinical_info."race"` top values: `WHITE`, `BLACK OR AFRICAN AMERICAN`, `ASIAN`, `[Not Evaluated]`, `[Unknown]`, `AMERICAN INDIAN OR ALASKA NATIVE`, `NATIVE HAWAIIAN OR OTHER PACIFIC ISLANDER`.
- `pancancer_atlas_clinical_info."pathologic_stage"` and `"clinical_stage"` use exact spellings like `Stage I`, `Stage IIA`, `Stage IIIC`, `[Not Applicable]` — case and Roman-numeral form must match exactly.
- Sentinel/placeholder strings recur across many clinical_info categorical columns: `[Not Applicable]`, `[Unknown]`, `[Not Evaluated]`, `[Discrepancy]` — these are not true NULLs, they are literal string values.
- Diagnosis-related acronyms from hints.txt: "LGG means Brain lower grade glioma, BRCA means Breast Invasive Carcinoma." — these acronyms are not literal column values seen in samples; they must be interpreted, not matched literally, unless found in text.
- `pancancer_atlas_clinical_info."form_completion_date"` is text, sample format `2009-10-20` (also seen as `2009-6-2`, i.e. non-zero-padded month/day — not a reliable date type).
- `days_to_death`, `days_to_last_followup`, `days_to_new_tumor_event_after_initial_treatment`, `number_of_lymphnodes_positive`, `lymph_node_examined_count`, `karnofsky_performance_score`, `eastern_cancer_oncology_group` are all stored as **text** even though values are numeric-looking (e.g. `943.0`, `[Not Applicable]`), so they mix numbers and sentinel strings in one column.

## Text columns that need reading
- `pancancer_atlas_clinical_info."Patient_description"` is a free-text sentence per patient (distinct for all 10,761 rows) containing, per hints.txt, "uuid, barcode, gender, and vital status" — e.g. "In the Ovarian serous cystadenocarcinoma dataset, patient TCGA-31-1953 (UUID 61feee94-...) is recorded as a FEMALE with vital status: Alive." Sentence templates vary (samples show at least 3 distinct phrasings), so gender, vital status, barcode and UUID must be extracted from this text, not from dedicated columns — clinical_info has no separate gender, vital_status, uuid, or full-barcode columns.
- `pancancer_atlas_mutation_data."HGVSp_Short"` and `"HGVSc"` are structured mutation-notation strings (e.g. `p.P1033Rfs*46`, `c.3098delC`) that encode protein/coding change details, including a literal `.` meaning no protein change recorded.
- `pancancer_atlas_clinical_info."histological_type_other"`, `"anatomic_neoplasm_subdivision_other"`, `"tumor_tissue_site_other"`, `"init_pathology_dx_method_other"` are free-text override fields, mostly `[Not Applicable]`, with sparse free-text detail otherwise.

## Conventions from description/hints
- "In gene expression analysis, the average log10-transformed value is typically computed as the mean of log10(normalized_count + 1) across samples."
- "Compute chi-square statistic as: χ² = Σ (Oij - Eij)² / Eij, where Eij = (row_total * col_total) / grand_total."
- "You can match molecular data by 'Patient_description' in clinical_info and 'ParticipantBarcode'."
- "You can use clinical_info's 'Patient_description' column to obtain more information about patients, such as uuid, barcode, gender, and vital status."
- "LGG means Brain lower grade glioma, BRCA means Breast Invasive Carcinoma."

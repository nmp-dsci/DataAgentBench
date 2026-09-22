# pancancer_atlas — schema

Postgres schema `dataagentbench`; every table is `pancancer_atlas_<table>`.

## store `clinical_database`

### `pancancer_atlas_clinical_info` — 10,761 rows (source table `clinical_info`)

| column | type |
|---|---|
| Patient_description | text |
| days_to_birth | double precision |
| days_to_death | text |
| days_to_last_followup | text |
| days_to_initial_pathologic_diagnosis | double precision |
| age_at_initial_pathologic_diagnosis | double precision |
| icd_10 | text |
| tissue_retrospective_collection_indicator | text |
| icd_o_3_histology | text |
| tissue_prospective_collection_indicator | text |
| history_of_neoadjuvant_treatment | text |
| icd_o_3_site | text |
| tumor_tissue_site | text |
| new_tumor_event_after_initial_treatment | text |
| radiation_therapy | text |
| race | text |
| prior_dx | text |
| ethnicity | text |
| informed_consent_verified | text |
| person_neoplasm_cancer_status | text |
| patient_id | text |
| year_of_initial_pathologic_diagnosis | double precision |
| histological_type | text |
| tissue_source_site | text |
| form_completion_date | text |
| pathologic_T | text |
| pathologic_M | text |
| clinical_M | text |
| pathologic_N | text |
| system_version | text |
| pathologic_stage | text |
| clinical_stage | text |
| clinical_T | text |
| clinical_N | text |
| extranodal_involvement | text |
| postoperative_rx_tx | text |
| primary_therapy_outcome_success | text |
| lymph_node_examined_count | text |
| primary_lymph_node_presentation_assessment | text |
| initial_pathologic_diagnosis_method | text |
| number_of_lymphnodes_positive_by_he | double precision |
| eastern_cancer_oncology_group | text |
| anatomic_neoplasm_subdivision | text |
| residual_tumor | text |
| histological_type_other | text |
| init_pathology_dx_method_other | text |
| karnofsky_performance_score | text |
| neoplasm_histologic_grade | text |
| height | double precision |
| weight | double precision |
| number_of_lymphnodes_positive_by_ihc | double precision |
| tobacco_smoking_history | text |
| number_pack_years_smoked | double precision |
| stopped_smoking_year | double precision |
| performance_status_scale_timing | text |
| laterality | text |
| targeted_molecular_therapy | text |
| year_of_tobacco_smoking_onset | double precision |
| anatomic_neoplasm_subdivision_other | text |
| patient_death_reason | text |
| tumor_tissue_site_other | text |
| menopause_status | text |
| margin_status | text |
| kras_gene_analysis_performed | text |
| venous_invasion | text |
| lymphatic_invasion | text |
| perineural_invasion_present | text |
| her2_immunohistochemistry_level_result | text |
| breast_carcinoma_progesterone_receptor_status | text |
| breast_carcinoma_surgical_procedure_name | text |
| breast_neoplasm_other_surgical_procedure_descriptive_text | text |
| axillary_lymph_node_stage_method_type | text |
| breast_carcinoma_estrogen_receptor_status | text |
| cytokeratin_immunohistochemistry_staining_method_micrometastasi | text |
| lab_proc_her2_neu_immunohistochemistry_receptor_status | text |
| lab_procedure_her2_neu_in_situ_hybrid_outcome_type | text |
| additional_pharmaceutical_therapy | text |
| additional_radiation_therapy | text |
| lymphovascular_invasion_present | text |
| location_in_lung_parenchyma | text |
| pulmonary_function_test_performed | text |
| egfr_mutation_performed | text |
| diagnosis | text |
| eml4_alk_translocation_performed | text |
| days_to_new_tumor_event_after_initial_treatment | text |
| hemoglobin_result | text |
| serum_calcium_result | text |
| platelet_qualitative_result | text |
| number_of_lymphnodes_positive | text |
| white_cell_count_result | text |
| alcohol_history_documented | text |
| family_history_of_cancer | text |
| braf_gene_analysis_performed | text |
| city_of_procurement | text |
| surgical_approach | text |
| peritoneal_wash | text |
| total_pelv_lnr | double precision |
| total_aor_lnr | double precision |
| prior_glioma | text |

## store `molecular_database`

### `pancancer_atlas_mutation_data` — 2,127,885 rows (source table `Mutation_Data`)

| column | type |
|---|---|
| ParticipantBarcode | character varying |
| Tumor_SampleBarcode | character varying |
| Tumor_AliquotBarcode | character varying |
| Normal_SampleBarcode | character varying |
| Normal_AliquotBarcode | character varying |
| Normal_SampleTypeLetterCode | character varying |
| Hugo_Symbol | character varying |
| HGVSp_Short | character varying |
| Variant_Classification | character varying |
| HGVSc | character varying |
| CENTERS | character varying |
| FILTER | character varying |

### `pancancer_atlas_rnaseq_expression` — 9,995,877 rows (source table `RNASeq_Expression`)

| column | type |
|---|---|
| ParticipantBarcode | character varying |
| SampleBarcode | character varying |
| AliquotBarcode | character varying |
| SampleTypeLetterCode | character varying |
| SampleType | character varying |
| Symbol | character varying |
| Entrez | bigint |
| normalized_count | double precision |


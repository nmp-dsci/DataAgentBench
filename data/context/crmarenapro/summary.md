# crmarenapro — dataset summary

## 1. Shape
Six stores backing 22 tables total (Postgres schema `dataagentbench`, tables named `crmarenapro_<table>`). Description says the stores map to different original engines (SQLite/DuckDB/Postgres) but all are queried here as Postgres tables.

- **activities**: `crmarenapro_event` (54 rows, calendar events), `crmarenapro_task` (4,783 rows, activities/tasks — largest activity table, heavily joined via WhatId/OwnerId), `crmarenapro_voicecalltranscript__c` (4,033 rows, call transcripts).
- **core_crm**: `crmarenapro_account` (101 rows), `crmarenapro_contact` (886 rows), `crmarenapro_user` (212 rows, sales team incl. system users like "Integration User", "Automated Process").
- **products_orders**: `crmarenapro_order` (163), `crmarenapro_orderitem` (689), `crmarenapro_pricebook2` (2), `crmarenapro_pricebookentry` (50), `crmarenapro_product2` (51), `crmarenapro_productcategory` (10), `crmarenapro_productcategoryproduct` (100).
- **sales_pipeline**: `crmarenapro_contract` (163), `crmarenapro_lead` (1,465), `crmarenapro_opportunity` (1,170), `crmarenapro_opportunitylineitem` (4,926 — most-joined line-item table), `crmarenapro_quote` (704), `crmarenapro_quotelineitem` (2,966).
- **support**: `crmarenapro_case` (153), `crmarenapro_casehistory__c` (393), `crmarenapro_emailmessage` (5,686 — largest table overall), `crmarenapro_issue__c` (15), `crmarenapro_knowledge__kav` (194), `crmarenapro_livechattranscript` (58).
- **territory**: `crmarenapro_territory2` (10), `crmarenapro_userterritory2association` (184).

The most central tables for joins are `crmarenapro_account`, `crmarenapro_opportunity`, `crmarenapro_contact`, and `crmarenapro_opportunitylineitem`/`crmarenapro_quotelineitem` (per joins.md, most pairs involving these hit normalised share 1.0).

## 2. Keys and joins (all overlaps from joins.md; all require normalisation: strip a leading `#` and trim whitespace — "normalised share" columns confirm raw shares are depressed by this corruption)
- `crmarenapro_event."WhatId"` ↔ `crmarenapro_task."WhatId"`: raw 0.9677, normalised 1.0.
- `crmarenapro_event."OwnerId"` ↔ `crmarenapro_task."OwnerId"` / `crmarenapro_lead."OwnerId"` / `crmarenapro_opportunity."OwnerId"`: raw 1.0 / 0.9556 / 0.9556, normalised 1.0 in all three.
- `crmarenapro_task."OwnerId"` ↔ `crmarenapro_lead."OwnerId"` (raw 0.9667→1.0) / `crmarenapro_opportunity."OwnerId"` (raw 0.9444→1.0).
- `crmarenapro_account."Id"` ↔ `crmarenapro_contact."AccountId"` (0.9703→1.0), `crmarenapro_opportunity."AccountId"` (0.9802→1.0), `crmarenapro_quote."AccountId"` (0.9604→1.0).
- `crmarenapro_contact."AccountId"` ↔ `crmarenapro_opportunity."AccountId"` (0.9787→1.0), `crmarenapro_quote."AccountId"` (0.9202→1.0).
- `crmarenapro_order."Id"` ↔ `crmarenapro_orderitem."OrderId"` (0.9325→1.0).
- `crmarenapro_order."AccountId"` ↔ `crmarenapro_contract."AccountId"` (0.7273→1.0), `crmarenapro_opportunity."AccountId"` (0.9899→1.0), `crmarenapro_quote."AccountId"` (0.9798→1.0).
- `crmarenapro_order."Pricebook2Id"` ↔ `crmarenapro_pricebook2."Id"` (0.5→1.0) and `crmarenapro_pricebookentry."Pricebook2Id"` (1.0→1.0).
- `crmarenapro_orderitem."Product2Id"` ↔ `crmarenapro_pricebookentry."Product2Id"` / `crmarenapro_product2."Id"` (0.4789/0.5211 → 1.0), and ↔ `crmarenapro_opportunitylineitem."Product2Id"` / `crmarenapro_quotelineitem."Product2Id"` (1.0→1.0).
- `crmarenapro_orderitem."PriceBookEntryId"` ↔ `crmarenapro_pricebookentry."Id"` (0.6923→1.0), ↔ `crmarenapro_opportunitylineitem."PricebookEntryId"` / `crmarenapro_quotelineitem."PricebookEntryId"` (1.0→1.0).
- `crmarenapro_pricebookentry."Product2Id"` ↔ `crmarenapro_product2."Id"` (0.6→1.0).
- `crmarenapro_productcategory."Id"` ↔ `crmarenapro_productcategoryproduct."ProductCategoryId"` (1.0/1.0).
- `crmarenapro_contract."AccountId"` ↔ `crmarenapro_opportunity."AccountId"` (0.989→1.0), `crmarenapro_quote."AccountId"` (0.978→1.0).
- `crmarenapro_lead."OwnerId"` ↔ `crmarenapro_opportunity."OwnerId"` (0.9598→1.0).
- `crmarenapro_opportunity."Id"` ↔ `crmarenapro_opportunitylineitem."OpportunityId"` (0.9179→1.0).
- `crmarenapro_opportunity."AccountId"` ↔ `crmarenapro_quote."AccountId"` (0.9235→1.0).
- `crmarenapro_quote."Id"` ↔ `crmarenapro_quotelineitem."QuoteId"` (0.9162→1.0).
- `crmarenapro_territory2."Id"` ↔ `crmarenapro_userterritory2association."Territory2Id"` (1.0/1.0).
- **Weaker joins — normalisation alone does not fully fix them, treat with caution:**
  - `crmarenapro_opportunitylineitem."Product2Id"` ↔ `crmarenapro_quotelineitem."Product2Id"`: raw 0.9545, normalised only 0.9565 (not 1.0).
  - `crmarenapro_opportunitylineitem."PricebookEntryId"` ↔ `crmarenapro_quotelineitem."PricebookEntryId"`: raw/normalised both 0.9565.
  - `crmarenapro_opportunity."Id"` ↔ `crmarenapro_quote."OpportunityId"`: raw 0.3624, normalised only 0.6017 — quote-to-opportunity linkage is measurably incomplete even after cleaning.
  - `crmarenapro_case."accountid"` ↔ `crmarenapro_livechattranscript."accountid"`: raw 0.5641, normalised 0.7963.
  - `crmarenapro_account."Id"`/`contact."AccountId"`/`opportunity."AccountId"`/`quote."AccountId"` ↔ `crmarenapro_case."accountid"`: normalised only ~0.53–0.53, ↔ `crmarenapro_livechattranscript."accountid"`: normalised only ~0.43. These account joins into support tables are unreliable even cleaned.
  - `crmarenapro_contact."Id"` ↔ `crmarenapro_case."contactid"`: normalised only 0.0813 — do not treat as a reliable join key.
  - No usable join found between `crmarenapro_account."Name"` and any product/opportunity/quote/territory `Name` column (all shares 0.0) — names are not shared identifiers across domains.

## 3. Literal values (exact spellings, from profile.json top values)
- `crmarenapro_task."Priority"`: `High`, `Normal`, `Low` (clean, no whitespace variants).
- `crmarenapro_task."Status"`: base values `Not Started`, `In Progress`, `Deferred`, `Waiting` — but stored with variable trailing whitespace (`"Not Started "`, `"Not Started  "`, etc.) as separate distinct values.
- `crmarenapro_case.status`: `Closed`, `Waiting on Customer`, `Working` — likewise with trailing-space variants.
- `crmarenapro_case.priority`: `Medium`, `High`, `Low`.
- `crmarenapro_lead."Status"`: `Converted`, `New`, `Working`, `Qualified` plus whitespace-padded variants.
- `crmarenapro_opportunity."StageName"`: `Closed`, `Discovery`, `Quote`, `Negotiation`, `Qualification` plus whitespace-padded variants (20 distinct values total for 5 semantic stages).
- `crmarenapro_quote."Status"`: `Approved`, `Accepted`, `Needs Review`, `In Review`, `Presented`, `Draft`, `Rejected`, plus whitespace variants (31 distinct).
- `crmarenapro_order."Status"` / `crmarenapro_contract."Status"`: effectively only `Activated` (plus whitespace-padded variants — 4 distinct values, all "Activated").
- `crmarenapro_casehistory__c.field__c`: `Owner Assignment`, `Case Creation`, `Case Closed`.
- Date/time columns are all stored as **text** (character varying / text), not native date/timestamp types:
  - Timestamp format `YYYY-MM-DDTHH:MM:SS.000+0000` (UTC offset) in `crmarenapro_event."StartDateTime"`, `crmarenapro_lead."CreatedDate"`/`ConvertedDate"` (CreatedDate has time, ConvertedDate is date-only `YYYY-MM-DD`), `crmarenapro_opportunity."CreatedDate"`, `crmarenapro_quote."CreatedDate"`, `crmarenapro_case.createddate`/`closeddate`, `crmarenapro_casehistory__c.createddate`, `crmarenapro_emailmessage.messagedate`, `crmarenapro_livechattranscript.endtime`, `crmarenapro_voicecalltranscript__c."CreatedDate"`.
  - Plain date format `YYYY-MM-DD` in `crmarenapro_task."ActivityDate"`, `crmarenapro_contract."StartDate"/"CustomerSignedDate"/"CompanySignedDate"`, `crmarenapro_order."EffectiveDate"`, `crmarenapro_quote."ExpirationDate"`, `crmarenapro_voicecalltranscript__c."EndTime__c"`.
  - `crmarenapro_user."TimeZoneSidKey"` is uniformly `America/Los_Angeles`; `"LanguageLocaleKey"`/`"LocaleSidKey"` uniformly `en_US`; `"EmailEncodingKey"` uniformly `UTF-8` (all 212 rows, per profile.json).

## 4. Text columns that need reading
- `crmarenapro_account."Description"`: prose naming the account's industry focus and the specific named products it uses (e.g. product names like "AI Cirku-Tech", "OptiPower Manager" appear only in this free text).
- `crmarenapro_product2."Description"`: short prose describing what each product does; `External_ID__c` embeds comma-separated category names plus a numeric suffix (e.g. `"PCB Design Solutions,Customizable Workflow Automation_46"`) — this is a composite text field, not a simple id.
- `crmarenapro_opportunity."Description"` / `crmarenapro_quote."Description"` / `crmarenapro_contract."Description"`: narrative deal/contract summaries naming products, accounts, and terms.
- `crmarenapro_case.description` / `crmarenapro_issue__c.description__c`: narrative of the customer's reported problem.
- `crmarenapro_knowledge__kav.faq_answer__c` and `.summary`: long-form FAQ/competitor-profile text (titles are literally "Competitor: <name>" in the sample).
- `crmarenapro_emailmessage.textbody`: full email body text; `toids` is a JSON-array-formatted string of recipient user ids (e.g. `["005Wt000003NJBVIA4"]`).
- `crmarenapro_livechattranscript.body`: timestamped chat transcript with speaker labels embedded as text (e.g. `[2023-03-08T06:51:22] Jakob Hansen (Customer): ...`), HTML-entity encoded (`&#39;`).
- `crmarenapro_voicecalltranscript__c."Body__c"`: timestamped call transcript with speaker names embedded as text.
- `crmarenapro_territory2."Description"`: comma-separated list of US state abbreviations covered by the territory (e.g. `"MO,KS,OK"`).

## 5. Conventions in the description/hints (quoted)
- "~25% of ID-like fields may include a leading # (e.g., #001Wt00000PFj4zIAD)."
- "~20% of text fields may contain trailing whitespace (e.g., \"Company Name \")."
- "Corruption may appear in: Id, AccountId, ContactId, Name, FirstName, LastName, Email, Subject, Status."
- "Corruption handling is needed for reliable joins"
- "Domain-specific CRM knowledge is required"
- Per description.txt, `ProductCategoryProduct`, `Pricebook2`, and `PricebookEntry` are each explicitly labeled "one of the pricing and mapping tables."
- No numeric/aggregation formulas are stated anywhere in description.txt or hints.txt beyond the above; do not assume a formula (e.g. for win rate, margin) that isn't written here.

# crmarenapro — schema

Postgres schema `dataagentbench`; every table is `crmarenapro_<table>`.

## store `activities`

### `crmarenapro_event` — 54 rows (source table `Event`)

| column | type |
|---|---|
| Id | character varying |
| WhatId | character varying |
| OwnerId | character varying |
| StartDateTime | character varying |
| Subject | character varying |
| Description | character varying |
| DurationInMinutes | character varying |
| Location | character varying |
| IsAllDayEvent | bigint |

### `crmarenapro_task` — 4,783 rows (source table `Task`)

| column | type |
|---|---|
| Id | character varying |
| WhatId | character varying |
| OwnerId | character varying |
| Priority | character varying |
| Status | character varying |
| ActivityDate | character varying |
| Subject | character varying |
| Description | character varying |

### `crmarenapro_voicecalltranscript__c` — 4,033 rows (source table `VoiceCallTranscript__c`)

| column | type |
|---|---|
| Id | character varying |
| OpportunityId__c | character varying |
| LeadId__c | character varying |
| Body__c | character varying |
| CreatedDate | character varying |
| EndTime__c | character varying |

## store `core_crm`

### `crmarenapro_account` — 101 rows (source table `Account`)

| column | type |
|---|---|
| Id | character varying |
| Name | character varying |
| Phone | character varying |
| Industry | character varying |
| Description | character varying |
| NumberOfEmployees | double precision |
| ShippingState | character varying |

### `crmarenapro_contact` — 886 rows (source table `Contact`)

| column | type |
|---|---|
| Id | character varying |
| FirstName | character varying |
| LastName | character varying |
| Email | character varying |
| AccountId | character varying |

### `crmarenapro_user` — 212 rows (source table `User`)

| column | type |
|---|---|
| Id | character varying |
| FirstName | character varying |
| LastName | character varying |
| Email | character varying |
| Phone | character varying |
| Username | character varying |
| Alias | character varying |
| LanguageLocaleKey | character varying |
| EmailEncodingKey | character varying |
| TimeZoneSidKey | character varying |
| LocaleSidKey | character varying |

## store `products_orders`

### `crmarenapro_order` — 163 rows (source table `Order`)

| column | type |
|---|---|
| Id | character varying |
| AccountId | character varying |
| Status | character varying |
| EffectiveDate | character varying |
| Pricebook2Id | character varying |
| OwnerId | character varying |

### `crmarenapro_orderitem` — 689 rows (source table `OrderItem`)

| column | type |
|---|---|
| Id | character varying |
| OrderId | character varying |
| Product2Id | character varying |
| Quantity | character varying |
| UnitPrice | character varying |
| PriceBookEntryId | character varying |

### `crmarenapro_pricebook2` — 2 rows (source table `Pricebook2`)

| column | type |
|---|---|
| Id | character varying |
| Name | character varying |
| Description | character varying |
| IsActive | bigint |
| ValidFrom | character varying |
| ValidTo | character varying |

### `crmarenapro_pricebookentry` — 50 rows (source table `PricebookEntry`)

| column | type |
|---|---|
| Id | character varying |
| Pricebook2Id | character varying |
| Product2Id | character varying |
| UnitPrice | character varying |

### `crmarenapro_product2` — 51 rows (source table `Product2`)

| column | type |
|---|---|
| Id | character varying |
| Name | character varying |
| Description | character varying |
| IsActive | bigint |
| External_ID__c | character varying |

### `crmarenapro_productcategory` — 10 rows (source table `ProductCategory`)

| column | type |
|---|---|
| Id | character varying |
| Name | character varying |
| CatalogId | character varying |

### `crmarenapro_productcategoryproduct` — 100 rows (source table `ProductCategoryProduct`)

| column | type |
|---|---|
| Id | character varying |
| ProductCategoryId | character varying |
| ProductId | character varying |

## store `sales_pipeline`

### `crmarenapro_contract` — 163 rows (source table `Contract`)

| column | type |
|---|---|
| Id | character varying |
| AccountId | character varying |
| Status | character varying |
| StartDate | character varying |
| CustomerSignedDate | character varying |
| CompanySignedDate | character varying |
| Description | character varying |
| ContractTerm | character varying |

### `crmarenapro_lead` — 1,465 rows (source table `Lead`)

| column | type |
|---|---|
| Id | character varying |
| FirstName | character varying |
| LastName | character varying |
| Email | character varying |
| Phone | character varying |
| Company | character varying |
| Status | character varying |
| ConvertedContactId | character varying |
| ConvertedAccountId | character varying |
| Title | character varying |
| CreatedDate | character varying |
| ConvertedDate | character varying |
| IsConverted | bigint |
| OwnerId | character varying |

### `crmarenapro_opportunity` — 1,170 rows (source table `Opportunity`)

| column | type |
|---|---|
| Id | character varying |
| ContractID__c | character varying |
| AccountId | character varying |
| ContactId | character varying |
| OwnerId | character varying |
| Probability | character varying |
| Amount | double precision |
| StageName | character varying |
| Name | character varying |
| Description | character varying |
| CreatedDate | character varying |
| CloseDate | character varying |

### `crmarenapro_opportunitylineitem` — 4,926 rows (source table `OpportunityLineItem`)

| column | type |
|---|---|
| Id | character varying |
| OpportunityId | character varying |
| Product2Id | character varying |
| PricebookEntryId | character varying |
| Quantity | character varying |
| TotalPrice | character varying |

### `crmarenapro_quote` — 704 rows (source table `Quote`)

| column | type |
|---|---|
| Id | character varying |
| OpportunityId | character varying |
| AccountId | character varying |
| ContactId | character varying |
| Name | character varying |
| Description | character varying |
| Status | character varying |
| CreatedDate | character varying |
| ExpirationDate | character varying |

### `crmarenapro_quotelineitem` — 2,966 rows (source table `QuoteLineItem`)

| column | type |
|---|---|
| Id | character varying |
| QuoteId | character varying |
| OpportunityLineItemId | character varying |
| Product2Id | character varying |
| PricebookEntryId | character varying |
| Quantity | character varying |
| UnitPrice | character varying |
| Discount | character varying |
| TotalPrice | character varying |

## store `support`

### `crmarenapro_case` — 153 rows (source table `case`)

| column | type |
|---|---|
| id | text |
| priority | text |
| subject | text |
| description | text |
| status | text |
| contactid | text |
| createddate | text |
| closeddate | text |
| orderitemid__c | text |
| issueid__c | text |
| accountid | text |
| ownerid | text |

### `crmarenapro_casehistory__c` — 393 rows (source table `casehistory__c`)

| column | type |
|---|---|
| id | text |
| caseid__c | text |
| oldvalue__c | text |
| newvalue__c | text |
| createddate | text |
| field__c | text |

### `crmarenapro_emailmessage` — 5,686 rows (source table `emailmessage`)

| column | type |
|---|---|
| id | text |
| subject | text |
| textbody | text |
| parentid | text |
| fromaddress | text |
| toids | text |
| messagedate | text |
| relatedtoid | text |

### `crmarenapro_issue__c` — 15 rows (source table `issue__c`)

| column | type |
|---|---|
| id | text |
| name | text |
| description__c | text |

### `crmarenapro_knowledge__kav` — 194 rows (source table `knowledge__kav`)

| column | type |
|---|---|
| id | text |
| title | text |
| faq_answer__c | text |
| summary | text |
| urlname | text |

### `crmarenapro_livechattranscript` — 58 rows (source table `livechattranscript`)

| column | type |
|---|---|
| id | text |
| caseid | text |
| accountid | text |
| ownerid | text |
| body | text |
| endtime | text |
| livechatvisitorid | text |
| contactid | text |

## store `territory`

### `crmarenapro_territory2` — 10 rows (source table `Territory2`)

| column | type |
|---|---|
| Id | character varying |
| Name | character varying |
| Description | character varying |

### `crmarenapro_userterritory2association` — 184 rows (source table `UserTerritory2Association`)

| column | type |
|---|---|
| Id | character varying |
| UserId | character varying |
| Territory2Id | character varying |


# Glue Database — Resource Context

You are collecting information for a Glue Database in the Minerva Lakehouse (or Compute) account.

## What to Collect (11 fields)

### Identity group (session-reusable: plat_env, intake_id, enterprise, subgroup)

| # | Field | Type | Notes |
|---|-------|------|-------|
| 1 | **plat_env** | dev, prd, snd | Session-reusable. |
| 2 | **intake_id** | M or I + digits | e.g. M0000451. Session-reusable. |
| 3 | **data_construct** | Source, DataProduct | Determines account type + naming pattern. |
| 4 | **data_layer** | see table below | **Depends on data_construct.** |
| 5 | **data_env** | dev, prd, qa, stg, snd | **Defaults from plat_env.** Only ask if they differ. |
| 6 | **source_name** | lowercase string | Governance-approved: cdp, concur, sap_tc1, sap_tcl, jdee1, iiq, workday, etc. |
| 7 | **enterprise_or_func_name** | AGTR, CORP, FOOD, SPEC | Session-reusable. |
| 8 | **enterprise_or_func_subgrp_name** | see table below | Depends on enterprise. **Required for CORP.** Session-reusable. |

### Ownership group (session-reusable: all three)

| # | Field | Type | Notes |
|---|-------|------|-------|
| 9 | **data_owner_email** | @cargill.com email | Session-reusable. |
| 10 | **data_owner_github_uname** | GitHub Enterprise username | Session-reusable. |
| 11 | **data_leader** | name or PSID | e.g. k745239, Jane Smith. Session-reusable. |

Inform once: "Region will be auto-set to us-east-1."

## Dependent Field: data_construct → data_layer

| data_construct | Valid data_layer options |
|----------------|------------------------|
| Source | raw, raw_serving |
| DataProduct | curated, serving, internal |

If user picks an invalid combo (e.g. Source + curated), reject: "Source databases only support raw and raw_serving layers."

## Enterprise → Valid Subgroups

| Enterprise | Subgroups | Required? |
|------------|-----------|-----------|
| AGTR | APAC, LATAM, NA, TDA, WTG | No |
| CORP | DTD, FIN, FSQR, GTC, CPT, EHS, DPE | **Yes** |
| FOOD | PRGL, FSGL, PR_NA | No |
| SPEC | ANH, BIO | No |

## Known Source Names

Common governance-approved source systems:
`cdp`, `concur`, `sap_tc1`, `sap_tcl`, `jdee1`, `iiq`, `workday`, `ariba`, `coupa`, `successfactors`, `salesforce`, `datadog`

If user provides an unknown source name, accept it (no validation) — it may be a new source.

## data_env Defaulting

- data_env usually equals plat_env. When asking, say: "data_env will match plat_env ({value}). Is that correct, or should it differ?"
- Only force-ask if user explicitly mentioned a different data_env.

## Account Mapping

| data_construct | Account Type | Accounts |
|---------------|-------------|----------|
| Source | Lakehouse | dev: 438465132548, prd: 578647603827 |
| DataProduct | Compute (per enterprise) | see table below |

### Compute Accounts

| Enterprise | # | Dev Account | Prod Account |
|------------|---|-------------|--------------|
| AGTR | cmp1 | 068887784423 | 367241115350 |
| FOOD | cmp2 | 933999308564 | 884308299029 |
| SPEC | cmp3 | 836901248866 | 011379513867 |
| CORP | cmp4 | 324612370323 | 632247962242 |

## Naming Conventions

### Lakehouse — Source databases (raw / raw_serving)

| Pattern | When |
|---------|------|
| `lh_{source_name}_{data_layer}_{plat_env}` | Non-CDP source |
| `lh_cdp_{source_name}_{data_layer}_{plat_env}` | source_name is from CDP pipeline |

**Rules:**
- Always starts with `lh_`
- If source_name == `cdp`, insert `cdp_` after `lh_`: `lh_cdp_sap_tcl_raw_prd`
- source_name token MUST appear in the name for raw/raw_serving
- Lowercase snake_case only (`a-z0-9_`)
- Database name is **immutable** after creation

Examples:
- `lh_concur_raw_dev`
- `lh_sap_tc1_raw_serving_prd`
- `lh_cdp_sap_tcl_raw_prd` (CDP source)
- `lh_cdp_iiq_raw_prd` (CDP + IIQ)

### Compute — DataProduct databases (curated / serving / internal)

| Pattern | When |
|---------|------|
| `{owning_entity}_{product_name}_{data_layer}_{plat_env}` | curated / internal |
| `{owning_entity}_{product_name}_{data_layer}_{purpose}_{plat_env}` | serving (with purpose) |

**owning_entity** = lowercase subgroup (for CORP) or lowercase enterprise (for others):
- CORP + FIN → `fin`
- AGTR (no subgroup) → `agtr`
- FOOD + PRGL → `prgl`

Examples:
- `fin_general_ledger_curated_dev`
- `agtr_seaborne_curated_prd`
- `fin_general_ledger_serving_analytics_dev`

## S3 Location Derivation

### Source (Lakehouse)

| Layer | Pattern |
|-------|---------|
| raw (non-CDP) | `s3://{plat_env}-lh1-{entity}[-{subgrp}]-src/raw/current/{data_env}/src/{source_name}/` |
| raw (CDP) | `s3://{plat_env}-lh1-{entity}[-{subgrp}]-src/raw/cdp/{data_env}/src/{source_name}/` |
| raw_serving | `s3://{plat_env}-lh1-{entity}[-{subgrp}]-src/raw_serving/{data_env}/src/{source_name}/` |

### DataProduct (Compute)

| Layer | Pattern |
|-------|---------|
| curated | `s3://{plat_env}-cmpN-{subgrp}-dp/curated/{data_env}/{entity}/{product}/` |
| serving | `s3://{plat_env}-cmpN-{subgrp}-dp/serving/{data_env}/{entity}/{product}/{purpose}/` |

**Notes:**
- `{entity}` = lowercase enterprise
- `[-{subgrp}]` = lowercase subgroup (omit segment if empty)
- `cmpN` = compute number for that enterprise (AGTR→cmp1, FOOD→cmp2, SPEC→cmp3, CORP→cmp4)
- Trailing `/` is always required

## YAML Examples

### CDP raw DB (Lakehouse, prod, CORP FIN)
```yaml
intake_id: M0000449
database_name: lh_cdp_sap_tcl_raw_prd
database_s3_location: "s3://prd-lh1-corp-fin-src/raw/cdp/prd/src/sap_tcl/"
database_description: "Store data from SAP TCL source system copied from CDP"
aws_account_id: '578647603827'
region: us-east-1
data_construct: Source
data_env: prd
data_layer: raw
source_name: cdp
enterprise_or_func_name: CORP
enterprise_or_func_subgrp_name: FIN
data_owner_email: chris_coward@cargill.com
data_owner_github_uname: ChrisCoward
data_leader: k745239
```

### Non-CDP raw DB (Lakehouse, dev, AGTR, no subgroup)
```yaml
intake_id: M0000470
database_name: lh_concur_raw_dev
database_s3_location: "s3://dev-lh1-agtr-src/raw/current/dev/src/concur/"
database_description: "Store data from Concur source system"
aws_account_id: '438465132548'
region: us-east-1
data_construct: Source
data_env: dev
data_layer: raw
source_name: concur
enterprise_or_func_name: AGTR
enterprise_or_func_subgrp_name: ""
data_owner_email: jane_doe@cargill.com
data_owner_github_uname: JaneDoe
data_leader: k123456
```

### Raw serving DB (Lakehouse, prod, AGTR)
```yaml
intake_id: M0000444
database_name: lh_jdee1_raw_serving_prd
database_s3_location: "s3://prd-lh1-agtr-src/raw_serving/prd/src/jdee1/"
database_description: "Database for storing clean JDEE1 tables"
aws_account_id: '578647603827'
region: us-east-1
data_construct: Source
data_env: prd
data_layer: raw_serving
source_name: jdee1
enterprise_or_func_name: AGTR
enterprise_or_func_subgrp_name: ""
data_owner_email: elias_belmiro@cargill.com
data_owner_github_uname: Eliasda-Silva-Belmiro
data_leader: Jonathan Cook
```

### DataProduct curated DB (Compute, dev, CORP FIN)
```yaml
intake_id: M0000500
database_name: fin_general_ledger_curated_dev
database_s3_location: "s3://dev-cmp4-fin-dp/curated/dev/corp/general_ledger/"
database_description: "Curated general ledger data product for Finance"
aws_account_id: '324612370323'
region: us-east-1
data_construct: DataProduct
data_env: dev
data_layer: curated
source_name: sap_tc1
enterprise_or_func_name: CORP
enterprise_or_func_subgrp_name: FIN
data_owner_email: john_smith@cargill.com
data_owner_github_uname: JohnSmith
data_leader: k789012
```

### DataProduct serving DB (Compute, prod, AGTR WTG)
```yaml
intake_id: M0000501
database_name: wtg_seaborne_serving_analytics_prd
database_s3_location: "s3://prd-cmp1-wtg-dp/serving/prd/agtr/seaborne/analytics/"
database_description: "Serving layer for seaborne analytics"
aws_account_id: '367241115350'
region: us-east-1
data_construct: DataProduct
data_env: prd
data_layer: serving
source_name: internal
enterprise_or_func_name: AGTR
enterprise_or_func_subgrp_name: WTG
data_owner_email: sarah_jones@cargill.com
data_owner_github_uname: SarahJones
data_leader: k654321
```

## Key Differences from S3

- More fields (11 collect vs 5 for S3)
- Has `data_env` separate from `plat_env` (can differ)
- Has `data_layer` and `source_name` driving naming
- data_layer depends on data_construct (not free choice)
- CDP source triggers special `lh_cdp_` prefix in name
- Subgroup is **required** for CORP (not optional like S3)
- Ownership fields collected directly (not derived)
- database_name and database_s3_location are **immutable** — cannot be changed after creation

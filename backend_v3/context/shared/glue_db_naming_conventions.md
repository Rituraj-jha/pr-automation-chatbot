# Glue Database Naming Convention Reference

> Purpose: Dedicated Glue DB naming reference for MiNi. Keep this separate from `context/resources/glue_db.md` so the Glue DB skill stays concise and this document can hold naming rules, examples, and LLM derivation guidance.
>
> Current intent: use this as organizational context for LLM-first Glue DB derivation. The derivation tool may select the applicable convention and return candidate derived fields. The reviewer tool is expected to become the full governance gate.

---

## 1. Derived fields contract

For Glue DB resources, derivation must return these fields:

- `database_name`
- `database_s3_location`
- `database_description`
- `aws_account_id`
- `region`

`region` is always `us-east-1` for Minerva Lakehouse provisioning.

---

## 2. Account association

Glue DB account selection is based on `data_construct`:

| data_construct | Account association | Account lookup |
|---|---|---|
| `Source` | Lakehouse | Lakehouse account for `plat_env` |
| `DataProduct` | Compute | Compute account for `plat_env` and `enterprise_or_func_name` |

Examples:

| plat_env | construct | enterprise | account abbreviation | account id |
|---|---|---|---|---|
| `dev` | `Source` | any | `dev-lh1` | `438465132548` |
| `prd` | `Source` | any | `prd-lh1` | `578647603827` |
| `dev` | `DataProduct` | `AGTR` | `dev-cmp1` | `068887784423` |
| `prd` | `DataProduct` | `CORP` | `prd-cmp4` | `632247962242` |

---

## 3. Naming tokens and transforms

- Database names must be lowercase snake_case: `a-z`, `0-9`, and `_` only.
- File name must match `database_name`.
- `database_name`, `database_s3_location`, `aws_account_id`, and `region` are immutable after creation.
- Enterprise/subgroup codes are collected in uppercase YAML values but become lowercase name/path segments.
- Underscores in subgroup codes remain underscores in database names and path segments unless the source examples clearly use hyphens in S3 bucket names.

### Owning entity grain

For Source/Lakehouse:

- Source database names generally do not include enterprise/subgroup.
- Source S3 bucket ownership follows Lakehouse S3 source bucket grain:
  - non-CORP enterprises use enterprise/function only: `agtr`, `food`, `spec`.
  - `CORP` includes subgroup: `corp-fin`, `corp-dtd`, etc.

For DataProduct/Compute:

- Database names and paths should use subgroup/data-product grain.
- Compute data product S3 buckets use subgroup-level ownership, typically `prd-cmp1-apac-dp`, `prd-cmp4-corp-fin-dp`, etc.

---

## 4. Source / Lakehouse naming conventions

Use when `data_construct=Source`.

### 4.1 Non-CDP raw source DB

Pattern:

```text
lh_[SOURCE_TOKEN]_raw_[PLAT_ENV]
```

Examples:

```text
lh_concur_raw_dev
lh_jdee1_raw_prd
lh_sap_tc1_raw_dev
```

S3 location:

```text
s3://[PLAT_ENV]-lh1-[SOURCE_BUCKET_ENTITY]-src/raw/current/[DATA_ENV]/src/[SOURCE_TOKEN]/
```

Example:

```text
s3://prd-lh1-agtr-src/raw/current/prd/src/jdee1/
```

### 4.2 CDP-fed raw source DB

Use when the collected `source_name` is `cdp` and the actual source system token is provided separately.

Pattern:

```text
lh_cdp_[ACTUAL_SOURCE_TOKEN]_raw_[PLAT_ENV]
```

Examples:

```text
lh_cdp_sap_tcl_raw_prd
lh_cdp_iiq_raw_prd
lh_cdp_bestmix_ewoso_raw_prd
```

S3 location:

```text
s3://[PLAT_ENV]-lh1-[SOURCE_BUCKET_ENTITY]-src/raw/cdp/[DATA_ENV]/src/[ACTUAL_SOURCE_TOKEN]/
```

Examples:

```text
s3://prd-lh1-corp-fin-src/raw/cdp/prd/src/sap_tcl/
s3://prd-lh1-corp-dtd-src/raw/cdp/prd/src/iiq/
```

Important:

- If `source_name=cdp`, the LLM must not derive only `lh_cdp_raw_prd` or `lh_cdp_cdp_raw_prd`.
- It needs an actual source token such as `sap_tcl`, `iiq`, `bestmix_ewoso`, etc.
- If that token is missing, return `can_derive=false` and request `source_system_name`.

### 4.3 Raw serving DB

Pattern:

```text
lh_[SOURCE_TOKEN]_raw_serving_[PLAT_ENV]
```

Examples:

```text
lh_sap_tc1_raw_serving_dev
lh_jdee1_raw_serving_prd
lh_cacp_raw_serving_prd
```

S3 location:

```text
s3://[PLAT_ENV]-lh1-[SOURCE_BUCKET_ENTITY]-src/raw_serving/[DATA_ENV]/src/[SOURCE_TOKEN]/
```

Example:

```text
s3://prd-lh1-agtr-src/raw_serving/prd/src/jdee1/
```

---

## 5. DataProduct / Compute naming conventions

Use when `data_construct=DataProduct`.

### 5.1 Curated layer

Pattern:

```text
[OWNING_ENTITY]_[DATA_PRODUCT_NAME]_curated_[PLAT_ENV]
```

Examples:

```text
fin_general_ledger_curated_prd
apac_aus_dom_curated_prd
anh_datablocks_curated_prd
```

S3 location:

```text
s3://[PLAT_ENV]-cmpN-[BUCKET_ENTITY]-dp/curated/[DATA_ENV]/[PATH_ENTITY]/[DATA_PRODUCT_NAME]/
```

Examples:

```text
s3://prd-cmp4-corp-fin-dp/curated/prd/fin/general_ledger/
s3://prd-cmp1-apac-dp/curated/prd/apac/aus_dom/
s3://prd-cmp3-anh-dp/curated/prd/anh/datablocks/
```

### 5.2 Serving layer

Pattern:

```text
[OWNING_ENTITY]_[DATA_PRODUCT_NAME]_serving_[PURPOSE]_[PLAT_ENV]
```

If no purpose is provided and the established convention for that product omits it, a shorter pattern may be used:

```text
[OWNING_ENTITY]_[DATA_PRODUCT_NAME]_serving_[PLAT_ENV]
```

Examples:

```text
fin_general_ledger_serving_prd
latam_dms_serving_analytics_prd
anh_datablocks_serving_analytics_prd
```

S3 location:

```text
s3://[PLAT_ENV]-cmpN-[BUCKET_ENTITY]-dp/serving/[DATA_ENV]/[PATH_ENTITY]/[DATA_PRODUCT_NAME]/[PURPOSE]/
```

If no purpose is used, omit the final purpose segment:

```text
s3://[PLAT_ENV]-cmpN-[BUCKET_ENTITY]-dp/serving/[DATA_ENV]/[PATH_ENTITY]/[DATA_PRODUCT_NAME]/
```

### 5.3 Internal layer

Pattern:

```text
[OWNING_ENTITY]_[DATA_PRODUCT_NAME]_internal_[PLAT_ENV]
```

S3 location:

```text
s3://[PLAT_ENV]-cmpN-[BUCKET_ENTITY]-dp/internal/[DATA_ENV]/[PATH_ENTITY]/[DATA_PRODUCT_NAME]/
```

---

## 6. Source bucket entity rules

For Source/Lakehouse `database_s3_location`, source bucket entity follows the Lakehouse S3 source bucket convention:

| Enterprise | subgroup | source bucket entity |
|---|---|---|
| `AGTR` | any | `agtr` |
| `FOOD` | any | `food` |
| `SPEC` | any | `spec` |
| `CORP` | `FIN` | `corp-fin` |
| `CORP` | `DTD` | `corp-dtd` |
| `CORP` | `GTC` | `corp-gtc` |

Examples:

```text
prd-lh1-agtr-src
prd-lh1-spec-src
prd-lh1-food-src
prd-lh1-corp-fin-src
prd-lh1-corp-dtd-src
```

---

## 7. Compute bucket entity and path entity rules

For DataProduct/Compute `database_s3_location`:

- AWS account is selected by enterprise/function.
- Bucket entity is usually subgroup-level.
- For `CORP`, bucket often includes `corp-[subgroup]`, e.g. `prd-cmp4-corp-fin-dp`.
- For non-CORP, bucket often uses subgroup only, e.g. `prd-cmp1-apac-dp`, `prd-cmp3-anh-dp`.
- Path entity is usually subgroup lowercase, such as `fin`, `apac`, `anh`.

Examples:

```text
prd-cmp1-apac-dp/curated/prd/apac/aus_dom/
prd-cmp4-corp-fin-dp/curated/prd/fin/general_ledger/
prd-cmp3-anh-dp/serving/prd/anh/datablocks/analytics/
```

---

## 8. LLM derivation guidance for Glue DB naming

When deriving Glue DB fields with LLM assistance:

1. Identify `data_construct`: `Source` or `DataProduct`.
2. Identify `data_layer`: `raw`, `raw_serving`, `curated`, `serving`, or `internal`.
3. Select account association:
   - `Source` → Lakehouse.
   - `DataProduct` → Compute.
4. Select account ID and account abbreviation from the provided account list.
5. Select naming convention from sections 4–5.
6. Derive source/product token:
   - Source non-CDP: use `source_name` as source token.
   - Source CDP: use `source_system_name` as actual source token; if missing, request it.
   - DataProduct: prefer `data_product_name`; if missing and `source_name` appears to be a product token, use `source_name` with low/medium confidence; otherwise request `data_product_name`.
7. For serving DataProduct DBs, use `serving_purpose` if provided. If missing and the request clearly says analytics/events/etc., request or infer with low confidence.
8. Derive `database_name`, `database_s3_location`, `database_description`, `aws_account_id`, and `region`.
9. Return a short derivation trace explaining selected convention and assumptions.
10. Do not perform full reviewer validation. Reviewer will check governance correctness later.

The LLM must not invent governance-sensitive values. If a required semantic token is missing, return missing inputs instead of guessing.

---

## 9. Implementation notes

- Glue DB derivation is intended to be LLM-first, matching the S3 derivation approach.
- Python should only do minimal tool-safety checks in this phase: parse JSON, ensure required output keys exist, and surface missing inputs.
- The reviewer tool is expected to become the full governance gate for naming correctness, account/folder alignment, and S3 location compliance.
- `source_system_name` is an optional collected field for CDP actual source tokens.
- `data_product_name` is an optional collected field for DataProduct naming and S3 path derivation.
- `serving_purpose` is an optional collected field for serving-layer DataProduct DBs such as `analytics` or `events`.

# Review Rules Reference

This document is read by the agent ONLY when `review_yaml` fails. It explains each error code, why it matters, and how to fix it.

---

## Error Codes

### NAMING_CONVENTION

**Why:** Bucket/database names must follow strict patterns for infrastructure automation and DNS compliance. Downstream tools parse the name to determine environment, account, and enterprise.

**Fix Strategy:**
1. Check which naming pattern applies (see resource .md for patterns).
2. Re-derive the name field using `derive_fields`.
3. If user overrode the name via `edit_derived_field`, validate their override against the pattern regex.
4. If override is invalid, explain why and suggest the correct derived name.

**S3 Examples:**
- Correct: `prd-lh1-agtr-apac-src`
- Wrong: `prd-lh1-agtr-src` (missing subgroup when subgroup is set)
- Wrong: `PRD-LH1-AGTR-SRC` (uppercase not allowed)
- Wrong: `prd_lh1_agtr_src` (underscores not allowed in S3 — use hyphens)

**Glue DB Examples:**
- Correct: `lh_cdp_sap_tcl_raw_prd`
- Wrong: `lh_sap_tcl_raw_prd` (missing cdp prefix when source is CDP)
- Wrong: `cdp_sap_tcl_raw_prd` (missing lh_ prefix for Source databases)

---

### ACCOUNT_MISMATCH

**Why:** Wrong account ID causes deployments to land in the wrong AWS account. Source data belongs in lakehouse, DataProducts in compute.

**Fix Strategy:**
1. Check the resource's usage_type (s3) or data_construct (glue_db).
2. Look up the correct account type: Source → lakehouse, DataProduct → compute.
3. Re-derive `aws_account_id` based on the correct type + enterprise + plat_env.
4. Never let a user override aws_account_id — it's locked.

**Account Quick Reference:**
| Type | Dev | Prod |
|------|-----|------|
| Lakehouse (all) | 438465132548 | 578647603827 |
| Compute AGTR | 068887784423 | 367241115350 |
| Compute FOOD | 933999308564 | 884308299029 |
| Compute SPEC | 836901248866 | 011379513867 |
| Compute CORP | 324612370323 | 632247962242 |

---

### CDP_PREFIX_MISSING

**Why:** CDP (Customer Data Platform) sources require the `cdp` token in the database name for governance tracking. Without it, data lineage tools can't identify CDP-sourced data.

**Fix Strategy:**
1. Check if `source_name == cdp` in collected fields.
2. If yes, re-derive `database_name` ensuring pattern is `lh_cdp_{actual_source}_{layer}_{env}`.
3. The "actual source" after cdp is the real source system (e.g. sap_tcl, iiq, salesforce).

**Examples:**
- Correct: `lh_cdp_sap_tcl_raw_prd` (source_name=cdp, actual source=sap_tcl)
- Wrong: `lh_sap_tcl_raw_prd` (source is CDP but cdp prefix missing)

---

### SUBGROUP_MISSING

**Why:** CORP enterprise always requires a subgroup. Without it, naming conventions break and account routing fails.

**Fix Strategy:**
1. Check if `enterprise_or_func_name == CORP`.
2. If yes and `enterprise_or_func_subgrp_name` is empty → this is a field collection error, not a derivation error.
3. Ask user for their subgroup. Valid options: DTD, FIN, FSQR, GTC, CPT, EHS, DPE.
4. After setting subgroup, re-derive all dependent fields.

---

### S3_LOCATION_MISMATCH

**Why:** The S3 location URI must correctly reference the bucket that corresponds to the enterprise, subgroup, and environment. If it points to the wrong bucket, data lands in the wrong location.

**Fix Strategy:**
1. Re-derive `database_s3_location` from scratch using the collected fields.
2. Verify the bucket segment matches: `{plat_env}-lh1-{entity}[-{subgrp}]-src` for Source, `{plat_env}-cmpN-{subgrp}-dp` for DataProduct.
3. Verify path segments match: data_env, source_name, data_layer.
4. Ensure trailing slash is present.

**Common causes:**
- Enterprise changed after initial derivation
- Subgroup added/removed after derivation
- plat_env changed but S3 location wasn't re-derived

---

### LAYER_CONSTRUCT_MISMATCH

**Why:** Source databases can only have `raw` or `raw_serving` layers. DataProduct databases can only have `curated`, `serving`, or `internal` layers. Invalid combos produce infrastructure that automation can't process.

**Fix Strategy:**
1. Check `data_construct` and `data_layer` values.
2. If Source + curated/serving/internal → ask user if they meant DataProduct, or correct data_layer to raw/raw_serving.
3. If DataProduct + raw/raw_serving → ask user if they meant Source, or correct to curated/serving.
4. After correction, re-derive.

**Valid combos:**
| data_construct | Allowed data_layers |
|---------------|-------------------|
| Source | raw, raw_serving |
| DataProduct | curated, serving, internal |

---

### SUFFIX_MISMATCH (S3 only)

**Why:** The bucket name suffix must match the usage_type. This is how automation tools identify bucket purpose.

**Fix Strategy:**
1. Check usage_type vs the last segment of bucket_name.
2. Expected: Source→`-src`, DataProduct→`-dp`, Scripts→`-scripts`, EngAssets→`-eng-assets`.
3. Re-derive bucket_name if mismatch.

---

### SOURCE_NAME_MISSING_IN_DB_NAME (Glue DB only)

**Why:** For raw/raw_serving databases, the source_name token must appear in database_name so data lineage tools can trace the origin.

**Fix Strategy:**
1. Check if `data_layer in [raw, raw_serving]`.
2. If yes, verify `source_name` appears as a substring in `database_name`.
3. If not, re-derive database_name.

---

### LH_PREFIX_MISSING (Glue DB only)

**Why:** All Source (lakehouse) databases must start with `lh_` to distinguish them from compute databases in the catalog.

**Fix Strategy:**
1. If `data_construct == Source` and database_name doesn't start with `lh_`, re-derive.
2. If user overrode the name, explain that lakehouse DBs must start with `lh_`.

---

## General Recovery Flow

When review fails:
1. Read the specific error code from this document.
2. Apply the fix strategy.
3. If fix requires changing a collected field → use `set_fields` (re-derive fires automatically).
4. If fix only requires re-derivation → the guardrail handles it after field change.
5. Re-generate YAML → review runs again automatically.
6. If review passes → resource moves to DONE.

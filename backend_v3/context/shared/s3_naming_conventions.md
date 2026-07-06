# S3 Naming Convention Reference

> Purpose: Dedicated S3 bucket naming reference for MiNi. Keep this separate from `context/resources/s3.md` so the S3 skill stays concise and this document can hold the larger naming rules, examples, and lead guidance.
>
> Current intent: use this as organizational context for LLM-assisted S3 naming derivation. The LLM may select the applicable convention and identify missing semantic inputs, but final values must still be validated before YAML/PR creation.

---

## 1. Universal S3 bucket pattern

All Minerva S3 bucket names follow this high-level shape:

```text
[AWS_ACCT_ABBR]-[OWNING_ENTITY]-[USAGE_SUFFIX]
```

Where:

- `AWS_ACCT_ABBR` identifies platform environment and account, such as `dev-lh1`, `prd-lh1`, `dev-cmp1`, `prd-cmp4`.
- `OWNING_ENTITY` is derived from enterprise/function, subgroup, source system, or operations-specific context depending on the convention.
- `USAGE_SUFFIX` is one of:
  - `src`
  - `dp`
  - `scripts`
  - `eng-assets`
  - `ops`

S3 bucket names are global, so environment/account abbreviation must always stay in the name to avoid dev/prod collisions.

---

## 2. Enterprise/function and subgroup vocabulary

### Owning enterprise/function

| Code | Meaning |
|---|---|
| `AGTR` | Ag & Trading |
| `CORP` | Corporate |
| `FOOD` | Food |
| `SPEC` | Specialized Portfolio |

### Common owning subgroup values

| Enterprise | Subgroups |
|---|---|
| `AGTR` | `EMEA`, `NA`, `LATAM`, `APAC`, `WTG`, `WTG_CDAS`, `OT`, `CRM`, `TCM`, `MET`, `GLOBAL` |
| `CORP` | `GI_SUST`, `EHS`, `FIN`, `GTC`, `CPT`, `HR`, `AUDIT`, `DTD`, `LAW`, `DTD_DPE`, `RMG`, `FSQR`, `DTD_GIS` |
| `FOOD` | `FSGL`, `FS_NA`, `FS_LATAM`, `FS_APAC`, `FS_EMEA`, `PRGL`, `PR_LATAM`, `PR_NA`, `PR_APAC`, `SALT`, `CE`, `RD` |
| `SPEC` | `ANH`, `CBI`, `DS` |

### Bucket-name casing/transforms

- Enterprise and subgroup codes are stored in YAML as uppercase values.
- Bucket-name segments are lowercase.
- Underscores in subgroup codes become hyphens in bucket names.
  - `WTG_CDAS` → `wtg-cdas`
  - `GI_SUST` → `gi-sust`
  - `DTD_DPE` → `dtd-dpe`

---

## 3. Convention 1 — Lakehouse Ent/Func specific source buckets

Use for source buckets aligned to an enterprise/function in the Lakehouse account.

```text
[AWS_ACCT_ABBR]-[OWNING_ENTITY]-src
```

Examples:

```text
dev-lh1-corp-fin-src
dev-lh1-agtr-src
```

Rules:

- Account association: Lakehouse.
- Usage suffix: `src`.
- Lead guidance: for Lakehouse S3 buckets, use only the enterprise/function level in the owning entity, except for `CORP`, where subgroup is included.
- For non-CORP enterprises (`AGTR`, `FOOD`, `SPEC`), do not include subgroup in the bucket name even if subgroup is present in YAML.
- For `CORP`, include subgroup because Corporate needs subgroup grain.

Owning entity derivation:

| Input | Owning entity segment |
|---|---|
| `enterprise_or_func_name=AGTR`, `subgroup=APAC` | `agtr` |
| `enterprise_or_func_name=FOOD`, `subgroup=PRGL` | `food` |
| `enterprise_or_func_name=SPEC`, `subgroup=ANH` | `spec` |
| `enterprise_or_func_name=CORP`, `subgroup=FIN` | `corp-fin` |

---

## 4. Convention 2 — Lakehouse source-system specific buckets

Use for source buckets that are not aligned to enterprise/function.

```text
[AWS_ACCT_ABBR]-[SRC_SYS_NAME]-src
```

Example:

```text
dev-lh1-sap-src
```

Rules:

- Account association: Lakehouse.
- Usage suffix: `src`.
- This pattern is effectively deprecated / unlikely for new Minerva requests because Governance expects source resources to align to an Enterprise/Function.
- If the LLM thinks this convention applies, it should not silently proceed. It should ask whether this is an approved exception and capture the source-system token.

---

## 5. Convention 3 — Compute Ent/Func subgroup specific data product buckets

Use for data product buckets in compute accounts.

```text
[AWS_ACCT_ABBR]-[OWNING_ENTITY]-dp
```

Examples:

```text
dev-cmp1-wtg-dp
dev-cmp1-wtg-cdas-dp
dev-cmp2-gi-sust-dp
```

Rules:

- Account association: Compute.
- Usage suffix: `dp`.
- Owning entity should be at subgroup level, not beyond subgroup level.
- Do not include unnecessary product/team/purpose tokens in the bucket name.
- Select compute account from enterprise/function and platform environment.

Owning entity derivation:

| Enterprise/subgroup | Owning entity segment |
|---|---|
| `AGTR` + `WTG` | `wtg` |
| `AGTR` + `WTG_CDAS` | `wtg-cdas` |
| `CORP` + `GI_SUST` | `gi-sust` |
| `FOOD` + `SALT` | `salt` |
| `SPEC` + `CBI` | `cbi` |

---

## 6. Convention 4 — Owning entity specific scripts buckets

Use for scripts/code artifacts in Lakehouse or Compute accounts.

```text
[AWS_ACCT_ABBR]-[OWNING_ENTITY]-scripts
```

Examples:

```text
dev-lh1-corp-fin-scripts
dev-cmp1-wtg-scripts
dev-cmp3-cbi-scripts
dev-cmp4-salt-scripts
```

Rules:

- Account association: Lakehouse or Compute.
- Usage suffix: `scripts`.
- If the bucket is in a Lakehouse account, owning entity should be restricted to enterprise/function level, except `CORP` includes subgroup.
- If the bucket is in a Compute account, owning entity should be subgroup level.
- Keep account abbreviation in the name to prevent dev/prod/global S3 collisions.

---

## 7. Convention 5 — Owning entity specific engineering assets buckets

Use for logs, temp data, and engineering artifacts in Lakehouse or Compute accounts.

```text
[AWS_ACCT_ABBR]-[OWNING_ENTITY]-eng-assets
```

Examples:

```text
dev-lh1-corp-fin-eng-assets
dev-cmp1-wtg-eng-assets
dev-cmp3-cbi-eng-assets
dev-cmp4-salt-eng-assets
```

Rules:

- Account association: Lakehouse or Compute.
- Usage suffix: `eng-assets`.
- If the bucket is in a Lakehouse account, owning entity should be restricted to enterprise/function level, except `CORP` includes subgroup.
- If the bucket is in a Compute account, owning entity should be subgroup level.
- Intended for logs, temporary data, and engineering support assets.

---

## 8. Convention 6 — Owning entity specific operations buckets

Use for operations/ad-hoc buckets in Lakehouse or Compute accounts.

```text
[AWS_ACCT_ABBR]-[OWNING_ENTITY]-ops
```

Examples:

```text
dev-lh1-corp-fin-ops
dev-lh1-dtd-miw-ops
dev-cmp1-dtd-miw-ops
dev-cmp4-salt-ops
```

Rules:

- Account association: Lakehouse or Compute.
- Usage suffix: `ops`.
- Potential uses: ad-hoc CSV dumps, explicit reports, operational safeguards, future operational mechanisms.
- If the bucket is in a Lakehouse account, owning entity should be restricted to enterprise/function level, except `CORP` includes subgroup.
- If the bucket is in a Compute account, owning entity should be subgroup level.
- Some examples include an extra operations identifier such as `miw` (`dtd-miw`). If the request implies an operations bucket but does not provide that identifier, the agent should ask for it rather than invent it.
- This may not be an immediate requirement. If used, confirm whether MIW expects this template for the request.

---

## 9. LLM derivation guidance for S3 naming

When deriving an S3 bucket name with LLM assistance:

1. Identify the account association: `Lakehouse`, `Compute`, or ambiguous.
2. Identify the intended usage suffix: `src`, `dp`, `scripts`, `eng-assets`, or `ops`.
3. Select the convention from sections 3–8.
4. Derive `AWS_ACCT_ABBR` from platform environment and account selection.
5. Derive `OWNING_ENTITY` using the convention-specific grain:
   - Lakehouse source/scripts/eng-assets/ops: enterprise/function level; `CORP` includes subgroup.
   - Compute data product/scripts/eng-assets/ops: subgroup level.
   - Source-system-specific exception: source-system token.
6. If the convention requires a source-system token or operations identifier and it is missing, ask the user.
7. Produce a derivation trace explaining which convention was selected and why.
8. Validate the final bucket name before saving generated/derived fields.

The LLM should not invent governance-sensitive values. It may propose a convention and candidate segments, but unclear or exceptional cases must be clarified with the user.

---

## 10. Implementation notes

- S3 derivation is intended to be LLM-first: the derivation tool reads this document, selects a convention, and returns candidate derived fields.
- Python should only do minimal tool-safety checks in this phase: parse JSON, ensure required output keys exist, and surface missing inputs.
- The reviewer tool is expected to become the full governance gate for naming correctness and convention compliance.
- `Ops` is available as an S3 `usage_type` in resource config.
- `source_system_name` is available as an optional collected field for approved source-system-specific bucket exceptions.
- `ops_identifier` is available as an optional collected field when examples like `dtd-miw-ops` apply.

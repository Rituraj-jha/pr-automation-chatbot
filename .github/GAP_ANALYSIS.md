# Gap Analysis — Backend V3 Config & Context Files

This document identifies gaps, inconsistencies, and missing pieces in the current `.md` and `.yaml` files
relative to the refined architecture defined in [ARCHITECTURE.md](./ARCHITECTURE.md).

---

## 1. `config/settings.yaml` — Gaps

| # | Gap | Impact | Fix |
|---|-----|--------|-----|
| 1 | No `aliases` for supported resources | LLM cannot map "bucket" → s3, "database" → glue_db, "storage" → s3 from natural language | Add `aliases` list per resource type |
| 2 | No `unsupported_message` | Agent has no configured fallback when user asks for something unsupported (e.g. "Lambda function") | Add a response template |
| 3 | No `display_name` per resource | Frontend/agent doesn't know the human-friendly name without loading each resource YAML | Add inline `display_name` |
| 4 | `supported_resources` is flat list | Only has type names, no metadata for intent detection | Expand to objects with `type`, `display`, `aliases` |

**Proposed fix:**
```yaml
supported_resources:
  - type: s3
    display: "S3 Bucket"
    aliases: [bucket, s3 bucket, storage, s3, object storage]
  - type: glue_db
    display: "Glue Database"
    aliases: [database, glue database, gluedb, glue db, catalog, glue catalog]
  # - type: iam
  #   display: "IAM Role"
  #   aliases: [role, iam role, permissions, access role]

unsupported_message: |
  I can only help provision these resources: S3 Buckets, Glue Databases.
  Would you like to create one of these?
```

---

## 2. `config/resources/s3.yaml` — Gaps

| # | Gap | Impact | Fix |
|---|-----|--------|-----|
| 1 | No `group` tag on fields | Cannot detect common fields across resource types for multi-resource batching | Add `group: identity` to plat_env, intake_id, enterprise, subgrp |
| 2 | No `session_reuse: true` flag | Tool doesn't know which fields to persist in session DB for auto-prefill | Add per-field flag |
| 3 | No `depends_on` for subgrp field | Validation cannot dynamically filter subgroup options based on enterprise value | Add `depends_on: enterprise_or_func_name` |
| 4 | No `allowed_values_ref` for subgrp | Subgroup field has no configured options — relies on free text with normalize_case | Reference `accounts.yaml` enterprises section or inline options-by-parent |
| 5 | `usage_type` field has no `group` | Cannot identify it as unique-to-s3 for multi-resource field batching | Add `group: s3_specific` or similar |
| 6 | `plat_env` missing `snd` option | S3 also supports sandbox but only shows dev/prd | Add snd option if applicable, or document it's intentionally excluded |
| 7 | Derivation `acct_abbr` logic is prose | Derive tool must interpret English sentences rather than a lookup table | Convert to explicit mapping or reference accounts.yaml lookup |
| 8 | No `file_name_field` reference | PR tool needs to know which derived field provides the filename (bucket_name) | Add `file_name_field: bucket_name` at top level |

---

## 3. `config/resources/glue_db.yaml` — Gaps

| # | Gap | Impact | Fix |
|---|-----|--------|-----|
| 1 | `enterprise_or_func_subgrp_name` has no `depends_on` | Subgroup options aren't filtered dynamically — user can enter invalid combos | Add `depends_on: enterprise_or_func_name` |
| 2 | No `session_reuse` flags | System doesn't know plat_env, intake_id, enterprise should auto-fill from session | Add per-field |
| 3 | `data_layer` has no dependency on `data_construct` | User can select "curated" with Source construct — invalid combo. Not caught by config. | Add `depends_on: data_construct` with allowed combos |
| 4 | `source_name` has no governed list | "Governance-approved" names are mentioned but never enumerated. LLM can't validate. | Either add known names or mark as `free_text_validated_externally` |
| 5 | `data_env` often equals `plat_env` but no `default_from` | Agent always asks this even when it could default | Add `default_from: plat_env` with override option |
| 6 | `database_name` derivation patterns are ambiguous | Multiple patterns listed but no clear rule for which to pick based on inputs | Add explicit `when` conditions per pattern |
| 7 | No `file_name_field` | PR tool doesn't know filename should be `database_name` | Add `file_name_field: database_name` |
| 8 | Validations section has `when` as string expressions | Code must eval/parse these — no structured format for condition checking | Consider structured conditions: `{field: "data_layer", operator: "in", value: ["raw","raw_serving"]}` |
| 9 | `region` vs `aws_region` inconsistency | S3 uses `aws_region`, Glue DB uses `region`. Different field names for same concept. | Standardize or document the difference explicitly |
| 10 | Ownership fields have no `session_reuse` | data_owner_email and data_owner_github_uname likely same across session but not flagged | Add `session_reuse: true` |

---

## 4. `context/system.md` — Gaps

| # | Gap | Impact | Fix |
|---|-----|--------|-----|
| 1 | No supported resource declaration | LLM doesn't know definitively what it CAN and CANNOT create. Relies on tool discovery. | Add section: "You support: S3 buckets, Glue databases. Anything else → politely decline." |
| 2 | No multi-resource orchestration rules for common fields | LLM doesn't know to ask common fields first across resource types | Add: "When multiple resources share fields (same group tag), ask those fields once for all." |
| 3 | No "wait for all CONFIRMING" rule | LLM might try to confirm one resource while others are still collecting | Add: "Show YAML preview ONLY when all active resources are in CONFIRMING state." |
| 4 | No field validation guidance | LLM doesn't know to validate before storing or what to do on validation failure | Add: "Every field value is validated before storing. If validation fails, explain what's wrong and re-ask." |
| 5 | No session field reuse explanation | LLM doesn't understand the session DB auto-prefill mechanism fully | Add: "Field values are stored at session level. When creating new resources, previously provided values auto-fill matching fields." |
| 6 | No dependent field guidance | LLM doesn't know subgroup options change based on enterprise | Add: "Some fields have dependent options. When enterprise is set, subgroup choices are filtered to valid options for that enterprise." |
| 7 | No update/edit existing resource flow | LLM has no instructions for when user wants to modify existing YAML from GitHub | Add section for update flow |
| 8 | Multi-Resource section is too brief | Only says "each resource is independent" — contradicts the "wait for all" rule | Expand with batching rules, common-field-first logic |
| 9 | No "clone with changes" workflow detail | `clone_resource` is mentioned but no guidance on when/how to use it | Add: "When user says 'same as X but with Y changed', use clone_resource with overrides" |
| 10 | No guidance on what happens if user asks "same config" | Agent might re-ask vs auto-clone | Add: "If user says 'same config' or 'another like that one', clone the most recent DONE resource" |
| 11 | Confirmation section doesn't mention "all must be CONFIRMING" | Allows confirming individual resources while others collect | Align with wait-for-all rule |
| 12 | No PR target branch default | Agent always asks for branch even if user said it earlier in session | Add: "Remember the target branch within a session. Don't re-ask." |

---

## 5. `context/resources/s3.md` — Gaps

| # | Gap | Impact | Fix |
|---|-----|--------|-----|
| 1 | No dependent field information | LLM doesn't know subgroup options depend on enterprise | Add section showing enterprise→subgrp valid combos |
| 2 | Derivation for CORP+compute is unclear | For CORP DataProduct, subgroup is used in name but the doc only shows it for Source → lakehouse which doesn't use subgroup for name | Clarify: "For compute (DataProduct), subgroup IS part of bucket name: prd-cmp4-{subgrp}-dp" |
| 3 | No mention of what happens with empty subgroup + different usage types | e.g. Scripts bucket for AGTR (no subgroup) — is it `prd-lh1-agtr-scripts`? | Add explicit examples for empty subgroup cases |
| 4 | Account mapping only shows dev/prd IDs for lakehouse | Missing compute account IDs per enterprise per env | Add full lookup table or reference accounts.yaml |
| 5 | No explicit error examples | LLM doesn't know common mistakes users make | Add: "Common errors: using prod instead of prd, mixing up enterprise/subgroup" |
| 6 | No `usage_type` → account_type mapping reference | Only prose rules, no table | Add explicit table: Source→lakehouse, DataProduct→compute, Scripts→lakehouse, EngAssets→lakehouse |

---

## 6. `context/resources/glue_db.md` — Gaps

| # | Gap | Impact | Fix |
|---|-----|--------|-----|
| 1 | No dependent field info (enterprise → subgrp) | Same as S3 — LLM can't guide user on valid combos | Add enterprise→subgroup table |
| 2 | No `data_construct` → `data_layer` valid combos | User can pick Source+curated which is invalid | Add: "Source allows: raw, raw_serving. DataProduct allows: curated, serving, internal." |
| 3 | S3 location derivation for compute is vague | "cmpN" — which N? How to resolve? | Clarify: "N maps from enterprise: AGTR→1, FOOD→2, SPEC→3, CORP→4" |
| 4 | No `data_env` defaulting guidance | LLM doesn't know data_env usually equals plat_env | Add: "Default data_env to plat_env value. Only ask if they differ." |
| 5 | No list of known source_names | LLM can't validate or suggest | Add known sources: cdp, concur, sap_tc1, sap_tcl, jdee1, iiq, workday, etc. |
| 6 | No DataProduct YAML example | Only shows Source (raw, raw_serving) examples | Add curated/serving DataProduct example |
| 7 | Naming convention for compute is incomplete | Shows `{owning_entity}_{product_name}_...` but doesn't explain what owning_entity maps to | Clarify: "owning_entity = lowercase subgroup (for CORP) or lowercase enterprise" |
| 8 | `instance_suffix` in patterns not explained | Pattern shows `{instance_suffix}` but no definition | Define: "instance_suffix is empty for most cases, used for multi-instance sources" |
| 9 | PII handling mentioned in example but no rule | CDP raw DB with PII example exists but no guidance on when/how to flag PII | Either add PII classification field or remove the implication |

---

## 7. `config/accounts.yaml` — Gaps

| # | Gap | Impact | Fix |
|---|-----|--------|-----|
| 1 | No `abbreviation` → `enterprise` reverse lookup | Derive tool needs to go from enterprise+plat_env → account_id. Currently must scan list. | Add a quick-lookup section or ensure tool code indexes properly |
| 2 | Enterprise subgroup list is incomplete | AGTR shows [APAC, LATAM, NA, TDA, WTG] but real data may have more (AMER, EMEA, MENA, CHIN, JAPAN, INDO) | Verify against actual data and update |
| 3 | No `subgroup_required` flag for all enterprises | Only CORP has it. But the rule should be explicit: others are optional. | Add `subgroup_required: false` to others for clarity |
| 4 | Format mismatch with `account_directory_map.yaml` | There's a SEPARATE file `config/account_directory_map.yaml` with a different structure (dict keyed by ID). Two sources of truth. | Consolidate into one canonical source. Either use accounts.yaml everywhere or delete the duplicate. |
| 5 | No `compute_number` field | Tools need AGTR→cmp1, FOOD→cmp2, SPEC→cmp3, CORP→cmp4 mapping — currently inferred from list order | Add explicit `compute_number: 1` field per account |

---

## 8. Cross-File Inconsistencies

| # | Issue | Files Involved | Fix |
|---|-------|----------------|-----|
| 1 | `region` vs `aws_region` | s3.yaml uses `aws_region`, glue_db.yaml uses `region` | Pick one name. Recommend `region` for both (shorter, matches YAML output). |
| 2 | Two account mapping files | `config/accounts.yaml` (list format) and `config/account_directory_map.yaml` (dict format) | Consolidate. PR tool should read same file as derive tool. |
| 3 | `plat_env` options differ | S3 has [dev, prd]. Glue DB has [dev, prd, snd]. | Either align or document S3 doesn't support sandbox. |
| 4 | Subgroup values differ from accounts.yaml | accounts.yaml has AGTR: [APAC, LATAM, NA, TDA, WTG]. But s3.md examples show APAC, FIN (FIN is CORP). | Ensure resource .md examples only use valid combos. |
| 5 | `intake_id` validation regex differs | S3: `^[A-Za-z]\d+$`, Glue DB: `^[MI]\d+$` | Align — should both accept M or I prefix? |
| 6 | No `usage_type` field in glue_db | Glue DB uses `data_construct` for same concept (Source vs DataProduct). Works but confusing since same logic. | Document the mapping: s3.usage_type↔glue_db.data_construct |
| 7 | System.md references resources by prose | "S3 buckets, Glue databases, IAM roles" — but IAM doesn't exist yet | Remove IAM mention or add placeholder config |

---

## 9. Missing Files (Required for Refined Architecture)

| File | Purpose | Priority |
|------|---------|----------|
| `config/validations/dependent_fields.yaml` | Enterprise → subgroup option filtering, data_construct → data_layer combos | P0 |
| `config/pr_template.yaml` | PR intake questions, auto-fill strategies, label definitions | P2 |
| `context/review_rules.md` | Review error codes → explanations → fix strategies (agent reads on failure) | P0 |
| `tools/validate_tools.py` | Centralized validation pipeline (normalize → static → dependent → cross-field) | P0 |
| `tools/reviewer_tools.py` | Post-confirmation business-rule quality gate | P0 |
| `tools/pre_validate_tools.py` | Pre-creation gates: approval image (vision) + intake ID validation | P3 |
| `tools/github_tools.py` | Check if resource YAML file already exists on GitHub (for update flow) | P4 |
| `agent/guardrails.py` | Extracted guardrail logic (currently inline in loop.py) | P1 |
| `db/schema.sql` → `session_fields` table | Cross-resource field reuse within a session | P1 |
| `db/schema.sql` → `approval_validations` table | Track which sessions passed approval image check | P3 |

---

## 10. Missing Concepts in Current Config

| Concept | Where it should live | Current state |
|---------|---------------------|---------------|
| **Field dependency declarations** | Each resource yaml, `depends_on` per field | Not present anywhere |
| **Session reuse flags** | Each resource yaml, `session_reuse: true/false` per field | Not present |
| **Field groups for batching** | Each resource yaml, `group` tag per field | Only in glue_db.yaml, missing from s3.yaml |
| **Supported resource aliases** | settings.yaml | Only flat list of type names |
| **Update flow instructions** | system.md | Completely absent |
| **Common field detection logic** | Either config or tool | Not defined — agent guesses |
| **Dependent option filtering** | Either resource yaml or validations/ folder | Only `required_when` exists, no option filtering |
| **File name resolution** | Resource yaml `file_name_field` | Hardcoded in pr_tools.py, not in config |
| **Default-from-another-field** | Resource yaml (e.g. data_env defaults from plat_env) | Not declared |
| **Validation as structured conditions** | Resource yaml validations block | Currently uses string expressions that need eval |
| **Pre-validation gates** | Resource yaml `pre_validations` + settings.yaml `intake_validation` | Completely absent — no concept of gating |
| **Image upload/validation** | API + tools + frontend | No image handling anywhere in the system |
| **REVIEWING state** | models/state.py ResourceStatus | Only COLLECTING, CONFIRMING, DONE, DROPPED exist |
| **Post-confirmation reviewer** | tools/reviewer_tools.py + context/review_rules.md | No quality gate between confirm and DONE |
| **PR intake questions** | config/pr_template.yaml | PR opens with auto-generated body, no template |
| **PR labels** | config/pr_template.yaml + pr_tools.py | No labels applied at all |
| **Auto-fill from context** | pr_tools.py | No smart inference of PR answers from session |
| **Wave/Team tracking** | user_profiles or session | Not stored anywhere |

---

## Priority Action Items

### P0 — Must fix for correct behavior
1. Add `depends_on` + dependent options for subgroup field (both s3.yaml and glue_db.yaml)
2. Add `data_construct → data_layer` valid combos in glue_db.yaml
3. Consolidate account mapping files (two sources of truth is a bug waiting to happen)
4. Add supported resource aliases to settings.yaml
5. Add "wait for all CONFIRMING" rule to system.md

### P1 — Required for multi-resource flow
6. Add `group` tags to ALL fields in s3.yaml (glue_db already has them)
7. Add `session_reuse` flags to fields that should persist across resources
8. Add `session_fields` table to schema.sql
9. Expand system.md multi-resource section with common-field-first logic
10. Create `config/validations/dependent_fields.yaml`

### P2 — Required for update flow
11. Create `tools/github_tools.py` (check existing file)
12. Add update flow section to system.md
13. Add `file_name_field` to resource yamls

### P3 — Quality/consistency
14. Standardize `region` vs `aws_region` across resources
15. Align `intake_id` validation regex
16. Add missing YAML examples (DataProduct glue_db)
17. Add `default_from: plat_env` for data_env field
18. Complete subgroup lists in accounts.yaml

---
---

# Additional Gaps (Post-Architecture Refinement)

The following gaps were identified after the architecture was expanded with pre-validation gates, reviewer tool, PR intake template, and labels.

---

## 11. Pre-Validation Gates — Completely Missing

No support currently exists for gating resource creation on approval evidence or intake validation.

| # | Gap | Impact | Fix |
|---|-----|--------|-----|
| 1 | No `pre_validations` field in resource YAMLs | System can't distinguish which resources need data owner approval vs which don't | Add `pre_validations: [{type: data_owner_approval, required: true}]` to glue_db.yaml, iam.yaml. Leave s3.yaml as `pre_validations: []` |
| 2 | No image upload support in API | Frontend/backend has no mechanism to accept image files from user | Add image upload endpoint or accept base64 in chat message |
| 3 | No `validate_approval_image` tool | Cannot verify approval screenshots | Create `tools/pre_validate_tools.py` with LLM vision-based validation |
| 4 | No `validate_intake_id` tool | Intake ID is only regex-checked inline in set_fields, no dedicated pre-check | Create in `tools/pre_validate_tools.py` — format + optional external API |
| 5 | No `intake_validation` config in settings.yaml | No central control over intake validation behavior (enabled, format, external API URL) | Add `intake_validation` section |
| 6 | No partial-creation logic | When some resources are blocked by missing approval, system has no way to create only the un-gated subset | Add logic in `create_resources` to filter based on pre-validation results |
| 7 | system.md has no pre-validation instructions | LLM doesn't know to ask for approval image or handle partial blocking | Add "Pre-Validation" section to system.md |

**What's needed in resource YAMLs:**
```yaml
# glue_db.yaml (requires approval)
pre_validations:
  - type: data_owner_approval
    required: true
    description: "Screenshot of data owner approval from intake system"

# s3.yaml (does NOT require approval)
pre_validations: []
```

**What's needed in settings.yaml:**
```yaml
intake_validation:
  enabled: true
  format_regex: "^[MI]\\d+$"
  external_api: null  # future: URL to intake tracking system
  allow_proceed_on_not_found: true
```

---

## 12. Reviewer Tool — Completely Missing

No post-confirmation quality gate exists. Currently, after user confirms → status goes directly to DONE with no business-rule verification.

| # | Gap | Impact | Fix |
|---|-----|--------|-----|
| 1 | No `review_yaml` tool | Confirmed YAML is never checked for business-rule violations (naming conventions, account correctness, cross-field consistency) | Create `tools/reviewer_tools.py` |
| 2 | No `context/review_rules.md` | Agent has no reference for understanding/fixing review failures | Create the file with error codes, explanations, fix strategies |
| 3 | No `REVIEWING` state in ResourceStatus enum | State model only has COLLECTING → CONFIRMING → DONE. No intermediate review step. | Add `REVIEWING` to `models/state.py` ResourceStatus enum |
| 4 | No auto-review guardrail in loop.py | After `generate_yaml`, nothing triggers the reviewer automatically | Add guardrail #10 in `agent/guardrails.py` |
| 5 | No review check rules in resource YAMLs `validations` section | S3 config has no validations block at all. Glue DB has one but uses string expressions. | Add/refine `validations` section per resource with structured conditions |
| 6 | system.md has no reviewer flow instructions | LLM doesn't know about the review step, how to handle failures, or how to present fixes | Add "Review" section explaining: reviewer runs → if fail → read review_rules.md → fix → re-confirm |
| 7 | Frontend has no "reviewing" state indicator | UI shows CONFIRMING and DONE but nothing for the in-between review state | Add visual state for REVIEWING in ResourcePanel |

**What `context/review_rules.md` should contain:**
```markdown
# Review Rules Reference

## Error Codes

### NAMING_CONVENTION
- **Why:** Bucket/database names must follow strict patterns for infrastructure automation
- **Fix Strategy:** Re-derive the name field. If user overrode it, check their override against the pattern.
- **Correct:** prd-lh1-agtr-apac-src
- **Wrong:** prd-lh1-agtr-src (missing subgroup when subgroup is set)

### ACCOUNT_MISMATCH
- **Why:** Wrong account causes deployments to fail
- **Fix Strategy:** Re-derive aws_account_id based on usage_type/data_construct + enterprise + plat_env

### CDP_PREFIX_MISSING
- **Why:** CDP sources require 'cdp' in name for governance tracking
- **Fix Strategy:** Re-derive database_name ensuring cdp token after lh_

... (one block per error code)
```

---

## 13. PR Template & Labels — Completely Missing

Current `create_pr` tool commits files and opens a PR with auto-generated title/body but has NO intake questions and NO labels.

| # | Gap | Impact | Fix |
|---|-----|--------|-----|
| 1 | No `config/pr_template.yaml` | PR intake questions, auto-fill strategies, and label definitions not configurable | Create the config file |
| 2 | No intake question collection in PR flow | PRs are opened without mandatory MIW template answers — will be rejected by reviewers | Add question collection step before commit |
| 3 | No label application via GitHub API | PRs don't get mandatory labels (ENV, Enterprise, Subgroup, Wave, Team) | Add label API call in `pr_tools.py` |
| 4 | No `CREATED_BY:MiNi` label | Cannot identify bot-created PRs for triage/audit | Always apply this label |
| 5 | No auto-fill logic from session context | Agent asks ALL questions even when answers are derivable from session (objective, intake approval, data flow) | Implement auto-fill using session state |
| 6 | No Wave/Team fields in user profile or session | These labels have no source — must be asked every time | Store in user profile after first ask, reuse across sessions |
| 7 | PR body doesn't follow MIW template | Current body is just YAML blocks — missing the 6 mandatory intake questions format | Format body using template from pr_template.yaml |
| 8 | system.md has no PR intake question instructions | LLM doesn't know to ask questions before creating PR, or which to auto-fill | Add "PR Creation" section with intake flow |

**Labels that need to be auto-applied:**
```
ENV:dev | ENV:prd
Enterprise:AGTR | Enterprise:CORP | Enterprise:FOOD | Enterprise:SPEC
Subgroup:APAC | Subgroup:FIN | ... (skip if empty)
Wave:W1 | Wave:W2 | Wave:W3 (ask user)
Team:DataEng | Team:... (from user profile or ask)
CREATED_BY:MiNi (always)
```

---

## 14. `models/state.py` — Gaps

| # | Gap | Impact | Fix |
|---|-----|--------|-----|
| 1 | No `REVIEWING` status | State machine can't represent the post-confirm pre-DONE step | Add to ResourceStatus enum |
| 2 | No `pre_validation_passed` flag on Session | Can't track whether approval image was already validated this session | Add `approval_validated: bool` field |
| 3 | No `pr_intake_answers` storage | PR intake question answers have nowhere to live between collection and PR creation | Add `pr_context: dict` to Session |
| 4 | No `approval_image_ref` field | If user uploaded approval, we have no reference to it | Add field to session or resource |

---

## 15. `tools/pr_tools.py` — Gaps (relative to new architecture)

| # | Gap | Impact | Fix |
|---|-----|--------|-----|
| 1 | No label application | PRs created without mandatory labels | Add GitHub API call: `POST /repos/{owner}/{repo}/issues/{pr_number}/labels` |
| 2 | No intake question collection | PR body is just YAML content, no template answers | Accept `intake_answers` dict param, format into body |
| 3 | PR body format doesn't match MIW template | Will be rejected by reviewers | Use `pr_template.yaml` to structure body |
| 4 | No `pr_template.yaml` config loading | Tool doesn't read any template config | Load and use for body formatting + question list |
| 5 | No label derivation from session | Labels are not computed from resource fields | Derive ENV, Enterprise, Subgroup from DONE resources |

---

## 16. `agent/loop.py` — Gaps

| # | Gap | Impact | Fix |
|---|-----|--------|-----|
| 1 | No auto-review guardrail | After generate_yaml, reviewer doesn't auto-fire | Add guardrail: if generate_yaml succeeds → call review_yaml |
| 2 | No pre-validation gate logic | Resources can be created without approval check | Add check before create_resources for gated types |
| 3 | Guardrails are inline | Hard to maintain, test, or extend | Extract to `agent/guardrails.py` |
| 4 | No intake_id pre-validation trigger | Intake ID is validated only by regex inside set_fields | Add early validate_intake_id call |

---

## 17. `db/schema.sql` — Gaps

| # | Gap | Impact | Fix |
|---|-----|--------|-----|
| 1 | No `session_fields` table | Cross-resource field reuse not persisted | Add table: `session_fields(session_id, field_name, field_value, updated_at)` |
| 2 | No `approval_validations` table | Can't track which sessions have passed approval | Add: `approval_validations(session_id, resource_type, image_ref, validated_at, result)` |
| 3 | Resources table has no `REVIEWING` status handling | Status column allows any text but code expects enum values | Ensure ResourceStatus enum includes REVIEWING |

---

## 18. Frontend — Gaps (relative to new architecture)

| # | Gap | Impact | Fix |
|---|-----|--------|-----|
| 1 | No image upload UI | User can't provide approval screenshots | Add file/image upload in chat input |
| 2 | No REVIEWING state badge | ResourcePanel only shows COLLECTING, CONFIRMING, DONE | Add "reviewing" badge/spinner |
| 3 | No PR intake question form | User must type answers in chat — no structured form | Add PR intake form (similar to FieldPromptsCard) |
| 4 | No label preview before PR creation | User can't see what labels will be applied | Show label chips in PR confirmation UI |

---

## Revised Priority Action Items

### P0 — Must fix for correct behavior (original + new)
1. Add `depends_on` + dependent options for subgroup field (both s3.yaml and glue_db.yaml)
2. Add `data_construct → data_layer` valid combos in glue_db.yaml
3. Consolidate account mapping files (two sources of truth)
4. Add supported resource aliases to settings.yaml
5. Add "wait for all CONFIRMING" rule to system.md
6. **NEW:** Add `REVIEWING` state to ResourceStatus enum
7. **NEW:** Create `tools/reviewer_tools.py` + `context/review_rules.md`
8. **NEW:** Add auto-review guardrail (generate_yaml → review_yaml)

### P1 — Required for multi-resource flow
9. Add `group` tags to ALL fields in s3.yaml
10. Add `session_reuse` flags to fields that should persist
11. Add `session_fields` table to schema.sql
12. Expand system.md multi-resource section with common-field-first logic
13. Create `config/validations/dependent_fields.yaml`
14. **NEW:** Add `pre_validations` to resource YAMLs (glue_db needs approval, s3 doesn't)

### P2 — Required for PR flow (new)
15. **NEW:** Create `config/pr_template.yaml` (intake questions + labels)
16. **NEW:** Add label application to `pr_tools.py`
17. **NEW:** Add intake question collection + auto-fill logic
18. **NEW:** Format PR body using MIW template
19. **NEW:** Add `CREATED_BY:MiNi` label (always)

### P3 — Required for pre-validation gates (new)
20. **NEW:** Create `tools/pre_validate_tools.py` (approval image + intake ID)
21. **NEW:** Add `intake_validation` config to settings.yaml
22. **NEW:** Add image upload support in API + frontend
23. **NEW:** Add partial-creation logic (only non-gated resources if approval fails)

### P4 — Required for update flow
24. Create `tools/github_tools.py` (check existing file)
25. Add update flow section to system.md
26. Add `file_name_field` to resource yamls

### P5 — Quality/consistency
27. Standardize `region` vs `aws_region` across resources
28. Align `intake_id` validation regex
29. Add missing YAML examples (DataProduct glue_db)
30. Add `default_from: plat_env` for data_env field
31. Complete subgroup lists in accounts.yaml
32. **NEW:** Add Wave/Team to user profile storage
33. **NEW:** Add frontend REVIEWING state + image upload + PR form

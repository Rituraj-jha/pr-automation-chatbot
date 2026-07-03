# MiNi Agent — Implementation Reference

Complete inventory of all files, tools, configs, and context documents needed for the refined backend_v3 agent.

---

## Tools Needed (by flow stage)

### Stage 1: Pre-Validation (before resource creation)

| Tool | File | Purpose | Input | Output |
|------|------|---------|-------|--------|
| `validate_approval_image` | `tools/pre_validate_tools.py` | Verify data owner approval screenshot using LLM vision | `image_data` (base64), `resource_types` (list) | `{valid, reason, approved_for[], missing_for[]}` |
| `validate_intake_id` | `tools/pre_validate_tools.py` | Check intake ID format + optionally query external system | `intake_id` (str) | `{valid, status, message, intake_details{}}` |

### Stage 2: Resource Creation & Field Collection

| Tool | File | Purpose | Input | Output |
|------|------|---------|-------|--------|
| `create_resources` | `tools/session_tools.py` | Create 1+ resources with initial_fields, prefill from session DB | `resources[]` with type + initial_fields | Resource IDs, prefilled fields, auto_derived flag |
| `get_session_state` | `tools/session_tools.py` | Returns full session JSON (auto-injected) | — | Full session state |
| `drop_resource` | `tools/session_tools.py` | Cancel a resource | `resource_id` | Confirmation |
| `clone_resource` | `tools/session_tools.py` | Copy from existing resource with overrides | `source_resource_id`, `overrides` | New resource ID |
| `set_fields` | `tools/field_tools.py` | Set collected fields with validation + session DB write | `resource_id`, `fields{}` | `{stored, errors, collection_complete}` |
| `get_resource_info` | `tools/field_tools.py` | Load .md context for LLM | `resource_type` | MD content |
| `get_common_fields` | `tools/field_tools.py` | Find shared fields across resource types for batching | `resource_types[]` | `{common_fields[], specific_fields{}}` |
| `validate_fields` | `tools/validate_tools.py` | Explicit 4-stage validation | `resource_id`, `fields{}` | `{valid, errors[], warnings[]}` |

### Stage 3: Derivation & Confirmation

| Tool | File | Purpose | Input | Output |
|------|------|---------|-------|--------|
| `derive_fields` | `tools/derive_tools.py` | Compute derived values from collected fields | `resource_id` | Derived fields dict |
| `edit_derived_field` | `tools/field_tools.py` | User override on constrained/free derived field | `resource_id`, `field_name`, `value` | Updated field |
| `generate_yaml` | `tools/generate_tools.py` | Produce final YAML with field order + quoting | `resource_id` | YAML string |

### Stage 4: Review (quality gate)

| Tool | File | Purpose | Input | Output |
|------|------|---------|-------|--------|
| `review_yaml` | `tools/reviewer_tools.py` | Business-rule checks on confirmed YAML | `resource_id` | `{pass, errors[], warnings[]}` |

### Stage 5: PR Creation

| Tool | File | Purpose | Input | Output |
|------|------|---------|-------|--------|
| `create_pr` | `tools/pr_tools.py` | Full PR workflow: questions → labels → commit → open PR | `target_branch`, `intake_answers{}` | `{pr_url, pr_number, labels[]}` |

### Stage 6: Update Existing (extension)

| Tool | File | Purpose | Input | Output |
|------|------|---------|-------|--------|
| `check_existing_resource` | `tools/github_tools.py` | Check if YAML file exists on GitHub | `resource_type`, `resource_name` | `{exists, content, file_path}` |

### Utility

| Tool | File | Purpose | Input | Output |
|------|------|---------|-------|--------|
| `update_user_profile` | `tools/preference_tools.py` | Store behavioral observations | `profile` (text) | Confirmation |

---

## Config Files Needed

| File | Purpose | Key Contents |
|------|---------|-------------|
| `config/settings.yaml` | App config + supported resources | `supported_resources` with aliases, `intake_validation` config, LLM settings, agent params |
| `config/accounts.yaml` | AWS account directory | 10 accounts (dev/prd × lakehouse/compute), enterprise↔subgroup mapping |
| `config/pr_template.yaml` | PR submission template | 6 intake questions with auto-fill strategies, label definitions, team label config |
| `config/resources/s3.yaml` | S3 bucket resource spec | collect_fields (5), derive_fields (4), derivation logic, yaml_output rules, `pre_validations`, `group`/`session_reuse`/`depends_on` per field |
| `config/resources/glue_db.yaml` | Glue database resource spec | collect_fields (11), derive_fields (5), validations, yaml_output, `pre_validations: [data_owner_approval]` |
| `config/resources/iam.yaml` | IAM role resource spec (future) | TBD — similar structure |
| `config/validations/dependent_fields.yaml` | Dependent field option mappings | enterprise→subgrp options, data_construct→data_layer valid combos |

---

## Context Files Needed (for LLM)

| File | Purpose | When Loaded |
|------|---------|-------------|
| `context/system.md` | Main system prompt — behavior rules, workflow, tone | Every turn (in system message) |
| `context/resources/s3.md` | S3 derivation examples, naming rules, YAML examples | When LLM calls `get_resource_info("s3")` |
| `context/resources/glue_db.md` | Glue DB naming conventions, S3 location patterns, examples | When LLM calls `get_resource_info("glue_db")` |
| `context/review_rules.md` | Review error codes → explanations → fix strategies | Only when `review_yaml` fails — agent reads to understand WHY |

---

## Database Tables Needed

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `sessions` | Chat sessions | session_id, user_id, title, created_at |
| `resources` | Resource state per session | resource_id, session_id, type, status, collected_fields (JSON), derived_fields (JSON), overrides (JSON), yaml_output |
| `messages` | Chat history | session_id, role, content, tool_calls (JSON), timestamp |
| `preferences` | User preferences (key-value) | user_id, key, value |
| `user_profiles` | Behavioral observations | user_id, profile (text) |
| `github_tokens` | OAuth tokens | user_id, token, updated_at |
| `session_fields` | **NEW** — Cross-resource field reuse | session_id, field_name, field_value, updated_at |

---

## Agent Layer Files

| File | Purpose |
|------|---------|
| `agent/loop.py` | ReAct tool-calling loop (max 10 iterations) |
| `agent/context_builder.py` | Assembles system prompt + user profile + resource hints |
| `agent/guardrails.py` | **NEW** — All code-enforced guardrails in one module |

---

## Guardrails (ordered by when they fire)

| # | Guardrail | Stage | Trigger | Action |
|---|-----------|-------|---------|--------|
| 1 | Pre-validation gate | Before creation | Resource types identified | Check approval requirement, ask for image if needed |
| 2 | Intake ID validation | Before creation | intake_id provided | Validate format + external check |
| 3 | Auto-inject state | Every turn | Turn start | Inject fresh session state as system message |
| 4 | Validate before store | Field collection | `set_fields` called | Run 4-stage validation pipeline before writing |
| 5 | Session field persistence | Field collection | After successful `set_fields` | Write values to `session_fields` table |
| 6 | Auto-derive | Field collection | `collection_complete=true` | Auto-call `derive_fields` |
| 7 | Block premature YAML preview | Confirmation | `_build_structured` | Only show preview when ALL active resources are CONFIRMING |
| 8 | Block generate_yaml same turn | Confirmation | After `create_resources` | Prevent generate_yaml in same loop iteration |
| 9 | Re-derive on edit | Confirmation | `edit_derived_field` called | Re-derive all dependent fields |
| 10 | Auto-review after confirm | Review | After `generate_yaml` | Auto-call `review_yaml`, block DONE until pass |
| 11 | Block PR without review | PR creation | `create_pr` called | Reject if any resource in REVIEWING (not passed) |

---

## Resource Config Structure (template for any resource)

```yaml
# {resource_type}.yaml — canonical structure

resource_type: <type_name>
display_name: "<Human Name>"
description: "<One-liner>"

# Pre-validation gates
pre_validations:
  - type: data_owner_approval    # requires image upload
    required: true/false
  # Add more gates as needed

# Fields the user provides
collect_fields:
  - name: <field_name>
    label: "<Display Label>"
    description: "<Help text>"
    group: identity|ownership|<custom>    # for multi-resource batching
    session_reuse: true|false              # auto-fill from session DB
    required: true|false
    allow_empty: true|false
    depends_on: <parent_field_name>        # dynamic option filtering
    required_when: "<condition>"           # conditional requirement
    options:
      - value: <val>
        label: "<label>"
        description: "<desc>"
    normalize: { <alias>: <canonical> }
    normalize_case: upper|lower
    validation: "<regex>"
    placeholder: "<example>"

# Fields derived automatically
derive_fields:
  - name: <field_name>
    label: "<Label>"
    description: "<desc>"
    editable: locked|constrained|free
    validation: "<regex>"
    auto_value: "<static_value>"  # if always the same

# Derivation logic
derivation:
  <field_name>:
    pattern: "<template>"
    rules: [...]
    # or
    template: "<simple template>"

# Validations after derivation (reviewer uses these)
validations:
  - name: <check_name>
    type: contains|starts_with|regex|required_if
    check_field: <field>
    when: "<condition>"
    error: "<message>"

# YAML output rules
yaml_output:
  field_order: [...]
  quoting:
    <field>: single|double|double_if_spaces|double_if_empty|none
    default: none
  conditional_fields:
    - field: <name>
      include_when: "<condition>"
      value: <static_value>

# Account constraints
constraints:
  <rule_name>:
    <value>: <account_type>
```

---

## Flow Summary (what happens in order)

```
1. USER MESSAGE arrives
2. INTENT CLASSIFICATION → create / update / PR / unsupported
3. PRE-VALIDATION GATES
   a. Check which resources need data_owner_approval
   b. If needed → ask for approval image → validate_approval_image
   c. If fail → only create non-gated resources
   d. Validate intake_id → validate_intake_id
4. CREATE RESOURCES in state (with initial_fields + session prefill)
5. FIELD COLLECTION
   a. Detect common fields (same group across resources) → ask once for all
   b. Ask resource-specific remaining fields one at a time
   c. Each set_fields → normalize → validate → store → session DB
   d. Auto-derive when all fields complete
6. CONFIRMATION (wait for ALL resources to reach CONFIRMING)
   a. Show paginated YAML editor
   b. User can edit → re-validate → re-derive
7. REVIEW (quality gate)
   a. generate_yaml → review_yaml
   b. If fail → agent reads review_rules.md → auto-fixes → re-confirms
   c. Loop until all pass → DONE
8. PR CREATION
   a. Ask target branch
   b. Collect PR intake answers (auto-fill what's possible)
   c. Build labels from session context
   d. Commit to fork → open PR with template body + labels
   e. Return PR URL
```

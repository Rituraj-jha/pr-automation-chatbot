# Project Context — PR Automation Chatbot (MiNi)

> This document provides full context for continuing development with a new Copilot session.

---

## 1. Project Overview

**MiNi** is a conversational AI chatbot that provisions AWS infrastructure (S3 Buckets, Glue Databases) through natural language. It collects user inputs, derives calculated fields, generates validated YAML configs, and commits them as Pull Requests to GitHub Enterprise.

**Tech Stack:**
- **Backend**: FastAPI (Python 3.11+), SQLite, OpenAI-compatible LLM (function calling)
- **Frontend**: React + Vite (port 5173)
- **LLM**: Azure OpenAI / TrueFoundry endpoint (GPT-4o class)
- **Branch**: `pr_creation`

---

## 2. Directory Structure (Active Code)

The active backend is `backend_v3/` (not `backend/` or `backend_wlg/` — those are older iterations).

```
backend_v3/
├── api.py                      # FastAPI endpoints, structured response builder
├── auth.py                     # Auth middleware
├── console.py                  # CLI chat interface for testing
├── requirements.txt
├── agent/
│   ├── context_builder.py      # Assembles system prompt + dynamic context
│   ├── guardrails.py           # 6 code-enforced rules (NOT prompt-driven)
│   └── loop.py                 # Main agent loop (LLM ↔ tools)
├── config/
│   ├── settings.yaml           # Supported resources, aliases, intake validation config
│   ├── accounts.yaml           # Account directory mapping
│   ├── pr_template.yaml        # PR description template
│   ├── resources/
│   │   ├── s3.yaml             # S3 field definitions, derivation rules, normalize maps
│   │   └── glue_db.yaml        # Glue DB field definitions, derivation rules
│   └── validations/
│       └── dependent_fields.yaml
├── context/
│   ├── system.md               # Global system prompt (~100 lines, concise)
│   ├── review_rules.md         # Reviewer validation rules
│   └── resources/
│       ├── s3.md               # Skill file — behavioral guidance (NOT field list)
│       └── glue_db.md          # Skill file — behavioral guidance (NOT field list)
├── db/
│   ├── connection.py           # SQLite async connection management
│   ├── repository.py           # CRUD: sessions, resources, messages, session_fields
│   └── schema.sql              # Table definitions
├── models/
│   └── state.py                # Session, Resource, Message, Preference dataclasses
├── services/
│   └── llm.py                  # OpenAI-compatible API wrapper
└── tools/
    ├── registry.py             # Tool function map + OpenAI tool schemas (17 tools)
    ├── field_tools.py          # set_fields, get_resource_info, get_common_fields
    ├── session_tools.py        # create_resources, drop_resource, clone_resource, get_session_state
    ├── derive_tools.py         # derive_fields (auto-calculates from collected)
    ├── generate_tools.py       # generate_yaml (produces YAML from all_fields)
    ├── validate_tools.py       # validate_fields (regex/option checks)
    ├── reviewer_tools.py       # review_yaml (mock — always passes, moves to DONE)
    ├── intake_tools.py         # check_intake_id (mock list), validate_approval_image (mock)
    ├── pr_tools.py             # create_pr (GitHub Enterprise API)
    └── preference_tools.py     # update_user_profile
```

---

## 3. State Machine

```
COLLECTING → CONFIRMING → REVIEWING → DONE
                                          ↓
                                      (PR creation when ≥1 DONE resource)
```

- **COLLECTING**: Fields being gathered from user
- **CONFIRMING**: All fields collected + derived → YAML preview shown → user confirms
- **REVIEWING**: YAML generated → auto-reviewer runs (currently mock, always passes)
- **DONE**: Ready for PR
- **DROPPED**: User cancelled this resource

Transitions are code-enforced (not LLM-decided):
- `set_fields` → checks `collection_complete` → guardrail auto-derives → status moves to CONFIRMING
- `generate_yaml` → status stays CONFIRMING (reviewer guardrail fires next)
- `review_yaml` → moves to DONE (or back to COLLECTING if issues found)

---

## 4. Architecture Decisions Made in This Session

### 4.1 Config-Driven (Not Prompt-Driven)
- Resource field definitions, options, normalize maps, derivation rules all live in `config/resources/*.yaml`
- The system prompt and skill files reference config as source of truth — they don't enumerate values
- `get_resource_info` tool returns structured JSON with field metadata (options, regex, normalize maps)
- Pre-validation gates defined per-resource in config (`pre_validations` array)

### 4.2 Guardrails (Code-Enforced, Not LLM-Dependent)
Six guardrails fire automatically in the agent loop:
1. **Auto-inject state** — injects fresh session state at turn start
2. **Auto-derive** — after `set_fields` returns `collection_complete`, triggers `derive_fields`
3. **Auto-review** — after `generate_yaml`, triggers `review_yaml`
4. **Block PR without review** — rejects `create_pr` if any resource in REVIEWING
5. **Session field persistence** — saves fields to `session_fields` table for cross-resource reuse
6. **Auto-check intake ID** — validates intake_id after storage (partially redundant now)

### 4.3 Pre-Store Validation (Key Fix)
- **Problem**: Invalid values (e.g., wrong intake_id) were being stored to state first, then flagged after. This caused YAML preview to appear with invalid data.
- **Solution**: `set_fields` and `create_resources` now validate externally BEFORE mutating state.
- **Implementation**: `_validate_external_field()` in `field_tools.py` and `_validate_initial_field_external()` in `session_tools.py` check intake_id against the external API (mock list) before writing to `resource.collected_fields`.
- Invalid fields are returned in an `errors` dict and never stored.

### 4.4 Dynamic Supported Resources
- `context_builder.py` reads `config/settings.yaml` to build the supported resources section dynamically
- No hardcoded resource lists in prompts
- Alias resolution (`bucket` → `s3`, `database` → `glue_db`) via settings

### 4.5 Multi-Resource Common-Field-First Flow
- When user requests multiple resources (e.g., "S3 + Glue DB"), the LLM asks for **common fields first** (plat_env, intake_id, enterprise names) then resource-specific fields
- YAML preview only shown when ALL active resources reach CONFIRMING
- `api.py` `_build_structured_data` enforces this wait

### 4.6 Concise Response Style
- System prompt enforces: max 2-3 sentences, list format for options, no recap of what was just done
- Skill files are behavioral guides (what to ask, how to normalize) not reference manuals

---

## 5. Key Files to Understand

### `tools/field_tools.py`
- `set_fields(resource_id, fields)` — validates options, regex, external checks → stores only valid fields → returns `{set: {...}, errors: {...}, collection_complete: bool}`
- `get_resource_info(resource_type)` — returns full field metadata as structured JSON (labels, options with descriptions, normalize maps, regex patterns, dependency info)
- `get_common_fields(resource_types)` — finds fields shared across requested types

### `tools/session_tools.py`
- `create_resources(resources_list)` — resolves aliases, checks pre-validation gates (e.g., data_owner_approval), validates initial_fields externally, creates Resource objects
- `bind_session(session)` — module-level binding for current session (called by API per request)
- `_get_session()` — returns current bound session

### `tools/intake_tools.py`
- `check_intake_id(intake_id)` — mock: checks against `APPROVED_INTAKE_IDS` list
- `validate_approval_image(image_url)` — mock: always returns approved, persists to session_fields
- **TODO**: Replace with real Power BI API call and LLM vision respectively

### `tools/derive_tools.py`
- `derive_fields(resource_id)` — reads derivation rules from config, computes derived field values from collected fields (e.g., `bucket_name` derived from plat_env + enterprise + usage_type)

### `agent/loop.py`
- Runs the full agent turn: inject state → LLM call → process tool calls → apply guardrails → repeat until LLM returns text
- Imports all guardrails and executes them in sequence

### `api.py`
- `/chat` endpoint: receives user message, loads/creates session, runs agent turn, returns structured response
- `_build_structured_data()`: builds sidebar data (fields table, YAML preview, resource cards) from session state
- YAML preview only included when all active resources are CONFIRMING or beyond

---

## 6. Config Files

### `config/settings.yaml`
```yaml
supported_resources:
  - type: s3
    display: "S3 Bucket"
    aliases: [bucket, s3 bucket, storage, s3, object storage]
  - type: glue_db
    display: "Glue Database"
    aliases: [database, glue database, gluedb, glue db, catalog]

intake_validation:
  enabled: true
  format_regex: "^[MI]\\d+$"
  external_api: null
  allow_proceed_on_not_found: true
```

### `config/resources/s3.yaml` (pattern — glue_db.yaml follows same structure)
```yaml
resource_type: s3
display_name: "S3 Bucket"
file_name_field: bucket_name
pre_validations: []          # glue_db has: [data_owner_approval]

collect_fields:
  - name: plat_env
    label: "Environment"
    options: [{value: dev, label: Dev}, {value: prd, label: Prod}]
    normalize: {development: dev, production: prd, prod: prd}
    session_reuse: true
    required: true
  - name: intake_id
    validation: "^[MI]\\d+$"
    session_reuse: true
  - name: usage_type
    options: [Source, DataProduct, Scripts, EngAssets]
    normalize: {source: Source, dataproduct: DataProduct, ...}
  - name: enterprise_or_func_name
    options: [AGTR, AH, CBS, ...]
  - name: enterprise_or_func_subgrp_name
    depends_on: enterprise_or_func_name    # dependent field
    ...

derive_fields:
  - name: bucket_name
    template: "cargill-{plat_env}-usea1-{enterprise_lower}-{subgrp_lower}-{usage_lower}"
  - name: account_id
    lookup: accounts.yaml
  ...
```

---

## 7. Frontend

- React SPA at `frontend/` (Vite, port 5173)
- Calls backend `/chat` endpoint
- Renders structured data sidebar (resource cards, field tables, YAML preview)
- YAML preview is built from **backend state dictionaries** (`resource.all_fields`), NOT from LLM text output
- Session management: create, switch, delete, rename sessions

---

## 8. Current State & Known TODOs

### Working:
- Full flow: S3 and Glue DB creation through chat
- Pre-store validation (invalid intake_id never stored)
- Config-driven field collection with normalize maps
- Auto-derivation, auto-review guardrails
- Multi-resource common-field-first collection
- YAML preview waits for all resources to be CONFIRMING
- Session field reuse across resources
- Alias resolution for resource types
- PR creation (GitHub Enterprise)

### Mock/TODO:
- `check_intake_id` uses hardcoded list → needs Power BI API integration
- `validate_approval_image` always passes → needs LLM vision integration
- `review_yaml` always passes → needs real rule engine (rules exist in `context/review_rules.md`)
- `guardrail_auto_check_intake_id` is partially redundant (validation moved pre-store) — could simplify
- No automated test suite yet (only manual validation scripts)

### Recent Bugs Fixed:
1. "Export" accepted as `usage_type` → added normalization + strict options validation
2. Invalid intake_id stored before validation → moved validation BEFORE state mutation
3. YAML preview shown for invalid resources → gated behind all-CONFIRMING check
4. `generate_yaml` was setting status to DONE directly → now stays CONFIRMING, reviewer moves to DONE
5. Skill docs listing field values caused LLM to invent options → made skill docs config-referencing only

---

## 9. How to Run

```bash
# Backend
cd backend_v3
pip install -r requirements.txt
python -m uvicorn api:app --host 0.0.0.0 --port 8000

# Frontend
cd frontend
npm install
npx vite --port 5173
```

Database: SQLite file `mini.db` (auto-created on first run via `db/schema.sql`)

---

## 10. Design Principles

1. **Config is truth** — field options, normalize maps, derivation rules live in YAML config, not prompts
2. **Code enforces, prompts guide** — guardrails handle correctness; prompts handle UX/tone
3. **Validate before store** — external validation happens BEFORE state mutation
4. **LLM sees structured data** — tools return JSON; system prompt tells LLM how to interpret it
5. **Minimal LLM surface** — keep system prompt short (~100 lines), skill files minimal, let tools carry context
6. **Multi-resource aware** — common fields collected once, applied to all resources in session

# Copilot Handoff Context — PR Automation Chatbot / MiNi

> Prepared for another team member's Copilot session. Current date: 2026-07-05.

This document summarizes the full working context from the recent Copilot chat: what was requested, what was implemented, which files matter, what tests were run, what still needs work, and how the next person should continue.

---

## 1. Project Snapshot

**MiNi** is a conversational AI assistant for infrastructure provisioning. Users request resources such as S3 Buckets and Glue Databases in natural language. The backend collects required fields, derives computed values, generates YAML, validates/reviews it, and creates GitHub Enterprise Pull Requests.

**Active implementation:** `backend_v3/` is the main backend for the current work. Older folders such as `backend/`, `backend_v2/`, and `backend_wlg/` are historical/experimental unless explicitly referenced.

**Frontend:** `frontend/` is the main React/Vite UI. `frontend_v2/` contains debug/experimental UI work.

**Important repo paths:**
- `backend_v3/agent/` — LLM loop, context builder, guardrails.
- `backend_v3/tools/` — tool implementations used by the LLM.
- `backend_v3/config/` — resource configs, PR template, repo mapping, update capabilities.
- `backend_v3/context/` — system prompt and route/resource skills.
- `frontend/` and `frontend_v2/` — UI clients.
- `miw-repo/` — local/mock MIW repository area used by repo lookup tooling.

---

## 2. User's Main Requests in This Chat

The user wanted the assistant to fix and improve the create/PR workflow:

1. **Add PR-intake gating before PR creation**
   - `create_pr` must not run until required PR-template answers are collected.
   - Safe values should auto-fill from completed resources when possible.
   - Missing PR metadata should be asked in a controlled way.

2. **Auto-fill PR template and PR labels**
   - Use resource/session state to derive objective, intake approval, labels like environment/enterprise/subgroup, etc.
   - Ask only missing items such as consumers, PII, Wave, Team, and target branch.

3. **Separate create and update flows**
   - A bare request such as `want s3` or `s3` must be treated as create flow.
   - Create flow must not ask update-only values such as `branch`, `file_path`, or `resource_name`.
   - Update flow should only start when the user explicitly says update/modify/edit/append an existing resource/file.

4. **Route lock and prompt filtering**
   - Each chat session should lock to either `create` or `update` route.
   - The LLM prompt should only include relevant route guidance after route lock.

5. **Improve collection behavior**
   - Intake ID first.
   - Approval requested only at the right time.
   - No duplicate resources on retry after approval.
   - Do not expose internal backend/tool details in normal user prompts.

6. **Create a handoff/context summary**
   - This file is the requested summary for another team member's Copilot context.

---

## 3. Current Architecture

### 3.1 Backend stack

- Python FastAPI backend in `backend_v3/`.
- SQLite persistence for sessions, messages, resources, and session fields.
- OpenAI-compatible function/tool calling through `backend_v3/services/llm.py`.
- GitHub Enterprise PR operations via `httpx` in PR/repo tools.

### 3.2 LLM control pattern

MiNi uses a hybrid design:

- **Prompts guide UX.**
  - `backend_v3/context/system.md`
  - `backend_v3/context/skills/create_resource.md`
  - `backend_v3/context/skills/update_resource.md`
  - `backend_v3/context/resources/*.md`

- **Code guardrails enforce correctness.**
  - `backend_v3/agent/guardrails.py`
  - `backend_v3/agent/loop.py`

- **Config is source of truth.**
  - `backend_v3/config/resources/s3.yaml`
  - `backend_v3/config/resources/glue_db.yaml`
  - `backend_v3/config/pr_template.yaml`
  - `backend_v3/config/update_capabilities.yaml`
  - `backend_v3/config/repo_directory_map.yaml`

### 3.3 Resource lifecycle

Resource creation generally follows:

```text
COLLECTING -> CONFIRMING -> REVIEWING -> DONE -> PR intake -> create PR
```

Key rule: after YAML review passes and a resource becomes `DONE`, the assistant should stop and tell the user they can request PR creation. It must not call `create_pr` in the same turn as YAML generation/review.

---

## 4. Major Changes Implemented in the Recent Chat

### 4.1 PR intake gate and auto-fill

Implemented in `backend_v3/tools/pr_tools.py`.

New/important session field keys:

- `__pr_intake_answers`
- `__pr_label_answers`
- `__pr_target_branch`

New/important functions:

- `prepare_pr_intake()`
  - Loads `backend_v3/config/pr_template.yaml`.
  - Finds completed `DONE` resources.
  - Auto-fills safe PR answers from resource/session state.
  - Returns missing intake questions, missing labels, target branch status, label preview, and `ready` boolean.

- `set_pr_intake_answers()`
  - Stores user-provided PR answers.
  - Validates option fields such as PII, Wave, and Team.
  - Persists reusable label answers in session fields.
  - Returns field-level errors if invalid.

- `_build_pr_intake_status()`
  - Core readiness builder used by both prepare and create paths.

- `create_pr()`
  - Now checks PR-intake readiness before any GitHub PR creation.
  - Refuses with a clear error if intake is incomplete.
  - Uses stored intake and label answers to build PR body and labels.

### 4.2 PR template configuration

Configured in `backend_v3/config/pr_template.yaml`.

Current required PR intake questions:

- `objective` — auto-filled from completed resources.
- `intake_approval` — auto-filled from intake ID/session state.
- `data_flow` — currently drafted/derived where possible but user can override.
- `consumers` — must ask user.
- `pii` — must ask user; valid values are `Yes`, `No`, `Unknown — pending classification`.
- `compliance` — optional/defaults to `None`.

Current labels:

- Derived labels: `ENV`, `Enterprise`, optional `Subgroup`.
- Asked labels: `Wave` with values `W1`, `W2`, `W3`, `W4`; `Team` with values `DataEng`, `Analytics`, `Platform`, `Governance`.
- Static label: `CREATED_BY:MiNi`.

### 4.3 Tool registry updates

Implemented in `backend_v3/tools/registry.py`.

New/important registered tools include:

- `prepare_pr_intake`
- `set_pr_intake_answers`
- `create_pr`
- `create_update_pr`
- `check_resource_exists`
- `check_update_capability`
- `fetch_existing_resource_file`
- `stage_append_only_update`
- `stage_full_updated_yaml`
- `validate_append_only_change`
- `preview_update_diff`

The OpenAI-style function schemas were updated so the LLM can call these tools.

### 4.4 Route lock and create/update separation

Implemented in `backend_v3/agent/guardrails.py` and `backend_v3/agent/loop.py`.

Important session field key:

- `__active_route`

Behavior:

- Create intent examples: `create`, `provision`, `make`, `want`, `need`, or a bare supported resource mention like `s3`.
- Update intent examples: `update`, `modify`, `edit`, `append`, `patch`, or explicit existing resource/file language.
- Bare supported resource requests default to create route.
- Once a session is locked, cross-route user requests are blocked with a message telling the user to start a new request or cancel/reset.
- Tool usage is also route-enforced. Create-route tools cannot be called in update mode and update-route tools cannot be called in create mode.

The specific user bug fixed here was: **typing `want s3` caused the assistant to ask update fields (`branch`, `file_path`, `resource_name`) during create collection.** The fix was to default bare resource mentions to create route and to filter update prompt guidance out of the system prompt when active route is create.

### 4.5 Route-aware prompt filtering

Implemented in `backend_v3/agent/context_builder.py`.

Key changes:

- `build_system_prompt(session, user_profile, active_route=None)` accepts the active route.
- `_build_route_skills_section(active_route)` includes only create skill or update skill when route is known.
- `_build_update_capabilities_section(active_route)` hides update capabilities unless active route is `update`.
- `_filter_system_prompt_for_route(system_md, active_route)` removes the opposite route section from `system.md`.
- `backend_v3/agent/loop.py` loads `__active_route` from session fields and passes it into `build_system_prompt()`.

Expected result: in create route, the system prompt should not contain update guidance or update required inputs.

### 4.6 Repo existence and update tooling

Implemented in `backend_v3/tools/repo_tools.py` and integrated with PR/generate tools.

Important session field keys:

- `__resource_exists:<resource_id>`
- `__resource_existence_detail:<resource_id>`
- `__pending_update`

Key capabilities:

- Resolve generated resource YAML path via `backend_v3/config/repo_directory_map.yaml`.
- Check whether a generated create resource already exists in the configured repo path.
- Prevent create PR flow when a create resource already exists or existence is unknown.
- Support update-route staging:
  - `check_update_capability`
  - `fetch_existing_resource_file`
  - `stage_append_only_update`
  - `stage_full_updated_yaml`
  - `validate_append_only_change`
  - `preview_update_diff`
  - `create_update_pr`

Current update config in `backend_v3/config/update_capabilities.yaml`:

- S3 update is enabled.
- S3 update is append-only.
- Update route requires `branch` and either `resource_name` or `file_path`.
- Glue DB update is disabled.
- IAM update is disabled.

### 4.7 Approval and collection flow fixes

The chat also included fixes/requirements around data-owner approval and collection order:

- Collect normal required fields before requesting data-owner approval.
- If a resource needs approval, keep using the existing `resource_id`; do not call `create_resources` again and create duplicates.
- Approval upload should pass exact `resource_ids` to the approval validator.
- For create field collection, never ask update-only inputs (`branch`, `file_path`, `resource_name`).

These behaviors are now strongly documented in `backend_v3/context/system.md` and supported by backend logic.

---

## 5. Current Create Flow Contract

Use this as the mental model when continuing work:

1. User asks for a resource, e.g. `want s3`.
2. Guardrail infers create route and stores `__active_route=create`.
3. System prompt is rebuilt without update route guidance.
4. LLM resolves resource type and calls `create_resources`.
5. Assistant collects `intake_id` first, then remaining required create fields from resource config.
6. `set_fields` validates and stores fields.
7. Once required fields are complete, guardrail auto-runs derivation.
8. If needed, approval gate runs after required field collection, not before.
9. Repo existence check verifies generated YAML path does not already exist.
10. User confirms field/YAML values.
11. `generate_yaml` runs; reviewer runs automatically.
12. Resource becomes `DONE`.
13. Assistant tells user they can say `create PR` when ready.
14. On a separate explicit PR request, LLM calls `prepare_pr_intake` first.
15. Assistant asks only missing PR intake/label/target branch fields.
16. LLM calls `set_pr_intake_answers` with user answers.
17. When `ready=true`, LLM may call `create_pr`.

Important: `create_pr` itself still enforces the readiness gate, so even if the LLM tries to skip steps, the backend blocks it.

---

## 6. Current Update Flow Contract

Use update route only when user explicitly asks to update/modify/edit/append an existing file or resource.

Expected flow:

1. Guardrail infers update route and stores `__active_route=update`.
2. Prompt includes update guidance and update capabilities.
3. LLM calls `check_update_capability(resource_type)`.
4. If enabled, assistant asks for target `branch` and either `resource_name` or `file_path`.
5. LLM calls `fetch_existing_resource_file`.
6. User provides append-only update content or a full updated YAML.
7. LLM calls `stage_append_only_update` or `stage_full_updated_yaml`.
8. Backend validates append-only behavior with `validate_append_only_change`.
9. Assistant shows `preview_update_diff` and asks user to confirm.
10. After confirmation, LLM calls `create_update_pr`.

Important: update flow is not fully end-to-end tested yet in realistic GitHub conditions.

---

## 7. Important File Map

### Agent and prompt routing

- `backend_v3/agent/loop.py`
  - Main ReAct/tool loop.
  - Calls route guardrail before building prompt.
  - Passes `active_route` to prompt builder.
  - Enforces tool route guardrail before tool execution.

- `backend_v3/agent/guardrails.py`
  - Route inference and route lock.
  - Tool allow/deny lists for create/update/neutral tools.
  - Auto-inject state, auto-derive, auto-review, PR blocking, session field persistence, intake check.

- `backend_v3/agent/context_builder.py`
  - Dynamic system prompt builder.
  - Adds supported resources, pre-validation requirements, route skills, update capabilities.
  - Filters unrelated route sections.

- `backend_v3/context/system.md`
  - Main system instructions.
  - Includes create route, update route, pre-validation gates, field collection, lifecycle, PR creation rules.

- `backend_v3/context/skills/create_resource.md`
  - Create-route behavioral skill.

- `backend_v3/context/skills/update_resource.md`
  - Update-route behavioral skill.

### Tools

- `backend_v3/tools/pr_tools.py`
  - PR intake, PR body/title/labels, create PR, create update PR.

- `backend_v3/tools/repo_tools.py`
  - Repo path resolution, existence checks, update fetch/stage/diff helpers.

- `backend_v3/tools/registry.py`
  - Central tool map and function schemas.

- `backend_v3/tools/session_tools.py`
  - Resource creation/drop/clone/session state.

- `backend_v3/tools/field_tools.py`
  - Field collection, validation, resource info, common field analysis.

- `backend_v3/tools/derive_tools.py`
  - Derived fields.

- `backend_v3/tools/generate_tools.py`
  - YAML generation.

- `backend_v3/tools/reviewer_tools.py`
  - YAML review, currently mock-ish/limited.

- `backend_v3/tools/intake_tools.py`
  - Intake ID and approval document validation hooks.

### Config

- `backend_v3/config/settings.yaml`
  - Supported resources and aliases.

- `backend_v3/config/resources/s3.yaml`
  - S3 collect/derive rules.

- `backend_v3/config/resources/glue_db.yaml`
  - Glue DB collect/derive rules.

- `backend_v3/config/pr_template.yaml`
  - PR intake questions, labels, PR body template, title template.

- `backend_v3/config/update_capabilities.yaml`
  - Update route enablement and required inputs.

- `backend_v3/config/repo_directory_map.yaml`
  - MIW repo path mapping and existence-check settings.

- `backend_v3/config/pre_validations.yaml`
  - Central approval/pre-validation behavior.

---

## 8. Validation Performed in the Chat

### 8.1 Compile checks

Python compile checks were run against modified modules and completed without syntax errors.

### 8.2 PR-intake smoke test results

A custom smoke script exercised PR intake preparation, validation, and create gate behavior. Key output:

```text
ready_initial = False
auto_keys = ['compliance', 'data_flow', 'intake_approval', 'objective']
missing_intake = ['consumers', 'pii']
missing_labels = ['Wave', 'Team']
target_branch_missing = True
create_blocked_error = "PR intake is incomplete. Cannot create PR yet."
invalid_valid = False
field_errors = {
  'pii': "Must be one of: ['Yes', 'No', 'Unknown — pending classification']",
  'Wave': "Must be one of: ['W1', 'W2', 'W3', 'W4']"
}
ready_final = True
labels_preview = ['ENV:dev', 'Enterprise:AGTR', 'Subgroup:APAC', 'Wave:W2', 'Team:DataEng', 'CREATED_BY:MiNi']
post_gate_error = "GitHub token not found. Please re-authenticate via GitHub OAuth."
```

Interpretation:

- PR intake gate works.
- Auto-fill works for safe fields.
- Invalid PII/Wave values are rejected.
- Once intake is ready, the flow proceeds to GitHub token check, which is expected to fail without OAuth credentials.

### 8.3 Route leakage smoke test results

After route-aware prompt filtering, a smoke test for `want s3` showed:

```text
route_block = None
active_route = create
has_update_skill = False
has_update_flow = False
has_update_cap_required_inputs = False
has_create_skill = True
```

Interpretation:

- Bare S3 request now locks to create route.
- Update guidance and update required inputs are hidden from prompt.
- Create skill remains present.

### 8.4 Backend server restart issue

Attempted to start backend with uvicorn on port 8000, but it failed:

```text
ERROR: [Errno 10048] error while attempting to bind on address ('127.0.0.1', 8000): only one usage of each socket address (protocol/network address/port) is normally permitted
```

Interpretation:

- Another backend/server process is already using port 8000.
- The running backend may not include the latest code changes unless it was restarted separately.
- Stop the existing process or run the backend on a different port before manual testing.

---

## 9. Known Current State

### Implemented and smoke-tested

- PR intake readiness and auto-fill.
- `create_pr` gate on PR intake readiness.
- PR intake answer validation and label preview.
- Route lock session field.
- Route-specific tool guardrail.
- Route-aware system prompt filtering.
- Fix for `want s3` accidentally asking update fields.

### Implemented but needs deeper testing

- Repo existence checks against configured GitHub/local repo.
- Update route end-to-end flow.
- Append-only update validation and diff preview in realistic data.
- `create_update_pr` against real GitHub credentials.
- Frontend support for new structured PR intake/update diff/approval states.

### Still mock or incomplete

- GitHub OAuth/token required for actual PR creation.
- `review_yaml` behavior is still limited/mock-like.
- Intake ID validation and data-owner approval validation may still use mock or placeholder logic depending on current tool implementation.
- Full frontend UX polish is pending.

---

## 10. How to Run Locally

Backend:

```bash
cd backend_v3
pip install -r requirements.txt
python -m uvicorn api:app --host 127.0.0.1 --port 8000
```

Frontend:

```bash
cd frontend
npm install
npx vite --port 5173
```

If port 8000 is in use, stop the old process or use another backend port and adjust frontend API configuration if needed.

---

## 11. Recommended Next Steps for the Next Copilot Session

1. **Restart backend cleanly**
   - Ensure the running backend process includes the latest code.
   - Resolve port 8000 conflict if necessary.

2. **Manually retest create flow**
   - Use a prompt such as `want s3`.
   - Confirm the assistant asks create fields only.
   - Confirm it does not ask `branch`, `file_path`, or `resource_name`.

3. **Retest PR intake from UI/API**
   - Complete a resource to `DONE`.
   - Say `create PR` in a separate message.
   - Confirm `prepare_pr_intake` runs first.
   - Confirm missing PR metadata is asked.
   - Confirm `create_pr` blocks until `ready=true`.

4. **End-to-end update flow testing**
   - Start with explicit update request, e.g. `update existing s3`.
   - Provide branch and resource name or file path.
   - Verify fetch, append-only staging, diff preview, and `create_update_pr` behavior.

5. **Frontend integration**
   - Add/verify UI surfaces for:
     - PR intake questions and missing values.
     - Approval upload with target resource IDs.
     - Update diff preview/confirmation.

6. **Add automated tests**
   - Unit tests for `prepare_pr_intake` / `set_pr_intake_answers`.
   - Guardrail tests for route inference and tool blocking.
   - Prompt composition tests verifying update sections are absent in create route.
   - Update flow tests with local mock repo files.

---

## 12. Expected User-Facing Behavior Examples

### Example A — create request

User:

```text
want s3
```

Expected assistant behavior:

- Lock route to create.
- Create an S3 resource or ask for initial create fields.
- Ask for create fields such as intake ID/environment/enterprise/usage type based on config.
- Do **not** ask for `branch`, `file_path`, or `resource_name`.

### Example B — PR request after resource is DONE

User:

```text
create PR
```

Expected assistant behavior:

- Call `prepare_pr_intake` first.
- Ask only missing PR metadata, for example:
  - downstream consumers
  - PII/sensitive classification
  - Wave
  - Team
  - target branch
- Do not call `create_pr` until `ready=true`.

### Example C — update request

User:

```text
update existing s3 bucket
```

Expected assistant behavior:

- Lock route to update.
- Call `check_update_capability`.
- Ask for target branch and either existing resource name or repo-relative file path.
- Fetch existing YAML and proceed with append-only update/diff preview.

---

## 13. Critical Rules to Preserve

- Config is truth; do not hardcode resource fields/options in prompts.
- Code guardrails enforce correctness; prompts only guide tone and flow.
- Validate before storing values.
- Do not mix create and update tools in the same active route.
- Bare supported resource requests default to create route.
- In create flow, never ask update-only inputs.
- Do not call `create_pr` in the same turn as `generate_yaml`.
- Always call `prepare_pr_intake` before `create_pr`.
- `create_pr` must remain gated by PR intake readiness.
- If repo existence check says a create resource already exists, do not silently switch to update route.

---

## 14. Quick Continuation Checklist

Before making new changes, inspect these files:

- `backend_v3/context/system.md`
- `backend_v3/agent/guardrails.py`
- `backend_v3/agent/context_builder.py`
- `backend_v3/agent/loop.py`
- `backend_v3/tools/pr_tools.py`
- `backend_v3/tools/repo_tools.py`
- `backend_v3/tools/registry.py`
- `backend_v3/config/pr_template.yaml`
- `backend_v3/config/update_capabilities.yaml`
- `backend_v3/config/repo_directory_map.yaml`

Then run/verify:

```bash
cd backend_v3
python -m py_compile agent/context_builder.py agent/guardrails.py agent/loop.py tools/pr_tools.py tools/repo_tools.py tools/registry.py
```

If backend is already running on port 8000, stop it or run on another port before testing changes.

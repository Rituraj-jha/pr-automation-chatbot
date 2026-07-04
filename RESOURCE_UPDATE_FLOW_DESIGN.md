# Resource Update Flow Design — GitHub-backed Existing YAML Updates

> Future implementation plan. This is not implemented yet.

---

## 1. Goal

Support a conversational flow where a user can update an existing resource YAML file from GitHub instead of only creating a new resource.

Example future user request:

> I want to update an IAM policy.

Current simulation target:

> Use `s3` to simulate the update flow until IAM support is added.

The assistant should first check whether the requested resource type supports update operations. If supported, it should fetch an existing YAML file from GitHub, show it to the user, let the user edit it, run review/validation, show a diff, and then create a PR.

---

## 2. High-level Requirements

1. Config must define which resources support update flow.
2. Agent must distinguish create vs update intent.
3. If update is requested for an unsupported resource, the agent must reject clearly.
4. If update is supported, collect:
   - GitHub branch
   - YAML file path or file name
5. Backend must fetch the file from GitHub.
6. UI must display fetched YAML to the user.
7. User must be able to edit the YAML.
8. Edited YAML must go through reviewer tool.
9. If review passes, UI must show Git diff.
10. User can create PR with updated YAML.
11. PR should update only the selected file/resource.

---

## 3. Config-driven Update Capability

Add a central config file:

```yaml
# backend_v3/config/update_capabilities.yaml

update_capabilities:
  s3:
    enabled: true
    display_name: "S3 Bucket"
    file_path_mode: user_provided
    accepted_file_extensions:
      - .yaml
      - .yml
    reviewer_tool: review_yaml
    diff_required_before_pr: true
    description: "Allows updating an existing S3 YAML file from GitHub. Used to simulate IAM policy update flow for now."

  glue_db:
    enabled: false
    display_name: "Glue Database"
    reason: "Glue DB update flow is not enabled yet."

  iam_policy:
    enabled: false
    display_name: "IAM Policy"
    reason: "IAM resource support is not implemented yet."
```

Later, when IAM is added:

```yaml
iam_policy:
  enabled: true
  display_name: "IAM Policy"
  file_path_mode: user_provided
  accepted_file_extensions:
    - .yaml
    - .yml
  reviewer_tool: review_yaml
  diff_required_before_pr: true
```

---

## 4. Conversation Flow

### 4.1 User asks to update unsupported resource

User:

> I want to update an IAM policy.

Agent flow:

1. Detect update intent.
2. Resolve resource type as `iam_policy`.
3. Check `config/update_capabilities.yaml`.
4. If `iam_policy.enabled == false`, respond:

Assistant:

> IAM Policy updates are not enabled yet. I can currently simulate the update flow with S3. Do you want to update an existing S3 YAML file instead?

---

### 4.2 User asks to update supported resource

User:

> I want to update an S3 bucket config.

Agent flow:

1. Detect update intent.
2. Resolve resource type as `s3`.
3. Check update capability config.
4. Ask for branch and file path if missing.

Assistant:

> S3 update flow is supported. Please provide the GitHub branch and YAML file path to update.

User:

> branch: dev, file: lakehouse/dev/s3/my-bucket.yaml

Agent calls backend tool:

```python
fetch_existing_resource_file(
  resource_type="s3",
  branch="dev",
  file_path="lakehouse/dev/s3/my-bucket.yaml"
)
```

---

## 5. Backend Tool Proposal

### 5.1 `get_update_capabilities`

Purpose: Return which resource types support updates.

Input:

```json
{}
```

Output:

```json
{
  "resources": {
    "s3": {
      "enabled": true,
      "display_name": "S3 Bucket"
    },
    "glue_db": {
      "enabled": false,
      "reason": "Glue DB update flow is not enabled yet."
    }
  }
}
```

---

### 5.2 `fetch_existing_resource_file`

Purpose: Fetch an existing YAML file from GitHub.

Input:

```json
{
  "resource_type": "s3",
  "branch": "dev",
  "file_path": "lakehouse/dev/s3/my-bucket.yaml"
}
```

Backend behavior:

1. Check update capability config.
2. Validate file extension.
3. Use GitHub Contents API or Git Tree API.
4. If file exists, return decoded content and metadata.
5. If file does not exist, return a clear error.

Output if found:

```json
{
  "found": true,
  "resource_type": "s3",
  "branch": "dev",
  "file_path": "lakehouse/dev/s3/my-bucket.yaml",
  "sha": "abc123",
  "yaml_content": "bucket_name: example\n...",
  "message": "Existing S3 YAML file loaded."
}
```

Output if missing:

```json
{
  "found": false,
  "error": "File not found on branch dev: lakehouse/dev/s3/my-bucket.yaml"
}
```

---

### 5.3 `stage_updated_resource_file`

Purpose: Store edited YAML in session state after the user edits it.

Input:

```json
{
  "resource_type": "s3",
  "branch": "dev",
  "file_path": "lakehouse/dev/s3/my-bucket.yaml",
  "original_yaml": "...",
  "updated_yaml": "..."
}
```

Output:

```json
{
  "staged": true,
  "change_type": "update",
  "resource_type": "s3",
  "file_path": "lakehouse/dev/s3/my-bucket.yaml"
}
```

---

### 5.4 `review_updated_yaml`

Purpose: Run reviewer on edited YAML.

For now this can reuse/mock `review_yaml`, but later it should support update-specific validations.

Input:

```json
{
  "resource_type": "s3",
  "file_path": "lakehouse/dev/s3/my-bucket.yaml",
  "updated_yaml": "..."
}
```

Output:

```json
{
  "passed": true,
  "issues": [],
  "message": "Updated YAML passed review."
}
```

---

### 5.5 `preview_update_diff`

Purpose: Generate a Git-style diff between original YAML and updated YAML.

Input:

```json
{
  "file_path": "lakehouse/dev/s3/my-bucket.yaml",
  "original_yaml": "...",
  "updated_yaml": "..."
}
```

Use Python `difflib.unified_diff` initially.

Output:

```json
{
  "file_path": "lakehouse/dev/s3/my-bucket.yaml",
  "change_type": "update",
  "has_changes": true,
  "diff": "--- old/lakehouse/dev/s3/my-bucket.yaml\n+++ new/lakehouse/dev/s3/my-bucket.yaml\n@@ ..."
}
```

---

### 5.6 `create_update_pr`

Purpose: Create a PR for only the edited existing file.

Input:

```json
{
  "target_branch": "dev",
  "updates": [
    {
      "file_path": "lakehouse/dev/s3/my-bucket.yaml",
      "updated_yaml": "..."
    }
  ]
}
```

This can reuse much of current `create_pr`, but must ensure only selected update files are committed.

---

## 6. Frontend UI Proposal

### 6.1 Update file fetch card

When update intent is detected, show a structured card asking:

- Branch
- File path/name

Example UI fields:

```text
Branch: [ dev                         ]
File path: [ lakehouse/dev/s3/foo.yaml ]
[Load YAML]
```

---

### 6.2 Existing YAML editor

Once file is fetched:

- Show file path
- Show branch
- Show editable YAML textarea
- Show original YAML optionally collapsed

Buttons:

- `Review Changes`
- `Cancel Update`

---

### 6.3 Review result

If review fails:

- Show issues
- Keep editor open
- Let user fix and resubmit

If review passes:

- Show diff card
- Enable PR action

---

### 6.4 Git diff card

Display unified diff with color styling:

- green for added lines
- red for removed lines
- gray for unchanged context

Buttons:

- `Create PR`
- `Back to Edit`
- `Cancel`

---

## 7. Agent Conversation Rules

Add to `context/system.md` later:

```md
# Resource Update Flow

- Detect update intent from phrases like: update, modify, edit existing, change existing, patch, revise.
- Before update flow, check `update_capabilities` config.
- If update is disabled for the resource, explain briefly and offer supported update resources.
- For update-enabled resources, collect branch and YAML file path.
- Fetch existing YAML before asking the user to edit.
- Never create a PR for an update until:
  1. Existing file was fetched successfully.
  2. User edited or confirmed updated YAML.
  3. Reviewer passed.
  4. Diff was shown to user.
  5. User explicitly confirmed PR creation.
- For update flow, commit only the selected existing file(s).
```

---

## 8. State Model Proposal

Add an `UpdateSession` or session-level structure:

```python
@dataclass
class PendingUpdate:
    update_id: str
    resource_type: str
    branch: str
    file_path: str
    original_yaml: str
    updated_yaml: str | None
    original_sha: str | None
    review_status: str
    diff: str | None
    status: str  # loaded | editing | reviewed | ready_for_pr | cancelled
```

Simpler first implementation: store this in `session_fields` as JSON:

```text
__pending_update:<update_id>
```

---

## 9. Important Difference: Create vs Update

### Create flow today

```text
collect fields → derive fields → YAML preview → confirm → review → DONE → create PR
```

### Update flow should be

```text
check update support → branch/file path → fetch existing YAML → edit YAML → review → show diff → confirm PR → create PR
```

Update flow should not force normal resource field collection unless later we decide to support structured field-based edits.

---

## 10. S3 Simulation Plan

Since IAM is not implemented yet:

1. Enable update capability for `s3` only.
2. User says:

> I want to update an S3 resource.

3. Agent asks for branch + file path.
4. Backend fetches YAML from GitHub.
5. UI displays YAML editor.
6. User edits YAML directly.
7. Mock reviewer passes.
8. UI shows diff.
9. PR updates the exact selected S3 YAML file.

This lets us test the full update architecture before adding IAM policy support.

---

## 11. Future IAM Policy Flow

When IAM is added:

1. Add `iam_policy` to `supported_resources`.
2. Add `iam_policy.yaml` resource config.
3. Enable `iam_policy` in `update_capabilities.yaml`.
4. Add IAM-specific reviewer rules.
5. Reuse the same update flow:

```text
user asks update IAM policy → config allows update → branch/file → fetch YAML → edit → review → diff → PR
```

---

## 12. Implementation Phases

### Phase 1 — Config + tool scaffolding

- Add `config/update_capabilities.yaml`
- Add `get_update_capabilities`
- Add `fetch_existing_resource_file`
- Add tool schemas
- Update system prompt

### Phase 2 — Frontend editor

- Add update file load card
- Add YAML editor card
- Add diff card

### Phase 3 — Review + diff

- Add `stage_updated_resource_file`
- Add `review_updated_yaml`
- Add `preview_update_diff`

### Phase 4 — PR update

- Add `create_update_pr`
- Ensure only selected update files are committed
- Add PR body section for update diff summary

### Phase 5 — IAM enablement

- Add IAM resource config
- Add IAM update capability
- Add IAM-specific validation/reviewer rules

---

## 13. Open Questions

1. Should user provide full GitHub file path or should we search by resource name?
2. Should update flow support multiple files at once?
3. Should user edit raw YAML only, or should we provide field-level editing later?
4. Which branch should be used for fetching existing YAML — target branch or source/fork branch?
5. Should diff be shown before or after reviewer? Recommendation: after reviewer passes, but optionally show both raw diff and reviewed diff.
6. Should no-change updates be blocked? Recommendation: yes, block PR if diff is empty.

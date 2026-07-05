# Update Resource Skill

Use this skill only when the user explicitly wants to update/modify/append to an existing resource YAML file.

Flow:
1. Resolve resource type.
2. Call `check_update_capability`.
3. If update is disabled, say it is not enabled and do not continue.
4. Read the returned `required_inputs` and ask the user for missing inputs.
5. Required for S3 before fetch: `branch` and either `resource_name` or `file_path`.
6. Prefer asking for resource name because backend can locate the YAML from repo config.
7. Never invent branch, resource name, or file path. If the user only says `s3` or `want s3`, that is not an update request; use create flow unless they explicitly say update/modify/append existing YAML.
8. If the user provides full path, valid MIW paths should be under `aws_lakehouse/`, for example `aws_lakehouse/lakehouse-001/s3/prd-lh1-agtr-src.yaml`.
9. Call `fetch_existing_resource_file` only after branch and resource_name or file_path are known from the user.
10. If file does not exist, tell the user update cannot continue for that name/path.
11. If multiple files match the name, ask the user to choose one returned path.
12. If file exists, ask what new YAML lines/block to append unless already provided.
13. Use `stage_append_only_update` to append new content.
14. Show the diff to the user and ask for confirmation.
15. If the user confirms the diff, call `create_update_pr` with the target branch.
16. Existing YAML may not be modified or deleted. Only appended lines are allowed.
17. Do not use create-route tools in update mode.

Current simulation target: S3 update flow. IAM update is disabled until IAM support is added.

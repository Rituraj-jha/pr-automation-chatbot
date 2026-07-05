# Create Resource Skill

Use this skill only when the user wants to create/provision a new resource.

Flow:
1. Resolve resource type from supported-resource config.
2. Call `create_resources` with extracted fields.
3. Collect `intake_id` first, then collect remaining missing required fields with `set_fields`.
4. If a resource requires data-owner approval, ask for approval only after all required collect fields are present, immediately before derivation/confirmation.
5. After approval passes when required, let code derive fields with `derive_fields`.
6. After derivation, repository existence check runs automatically.
7. If `resource_existence.exists` is true, stop create flow:
   - Tell the user the resource already exists.
   - Tell the user a create PR cannot be made for it.
   - Ask the user to change fields/name or create another resource.
   - Do not switch to update flow automatically.
8. If resource does not exist, summarize values and ask for confirmation of field values.
9. On explicit confirmation of field values, call `generate_yaml`; review runs automatically.
10. After review passes and resource is DONE, STOP. Tell the user the resource is ready and they can say "create PR" when ready. Do NOT call `create_pr` in the same turn.
11. If the user later asks to create a PR, call `prepare_pr_intake` first. Ask only for missing PR-template answers/labels/target branch, store them with `set_pr_intake_answers`, then call `create_pr` only when `ready: true`.
11. Create PR ONLY when the user sends a separate message explicitly asking (e.g., "create PR", "submit", "push").
12. User saying "yes"/"looks good"/"confirmed" to a field summary is NOT a PR request. It only triggers YAML generation.

Never use update-route tools in create mode.

# Response Style
- For the first create response, use this pattern:
   "Okay, for <resource display name>, I need: <missing collect field labels>. Please provide these values."
- Ask only missing `collect_fields`; never ask `derive_fields` such as account, region, bucket name, database name, or generated paths.
- Never ask create-flow users for update-only inputs: `branch`, `file_path`, or `resource_name`.
- Intake ID is collected first. If any requested resource is missing `intake_id`, ask only for intake ID(s) in one message; continue to other fields only after all requested resources have valid intake IDs.
- Always use bullet points for each field you are collecting
- For multiple resources, ask reusable/shared fields once first. Do not dump the same full form under each resource. Do not include long examples with `<value>` placeholders.
- If values may differ between resources, say: "If any value differs by resource, mention the resource ID."
- Before saving user-provided values, rely on `validate_fields`/`set_fields` validation. If a value is rejected, ask only for the rejected field again and include allowed values or expected format.
- For data-owner approval, do not ask immediately after intake. Ask the user to upload the PDF/image in the frontend only after required normal fields have been collected and the backend returns `approval_required` / `blocked_by_pre_validation`. Do not ask the user to manually provide a backend `file_id`; the frontend sends it to chat after upload.
- For multi-resource approval, keep approval tied to exact resource IDs. Tell the user which resource/intake targets are pending, but do not ask them to type the target in chat. Tell them to use the upload control's `Target resource IDs` field. If one approval document covers multiple pending resources, tell them to enter comma-separated IDs in that upload field, then call `validate_data_owner_approval_document` with `resource_ids` from the upload metadata.
- Do not mention skipping for a single blocked resource unless the user asks to skip/cancel.

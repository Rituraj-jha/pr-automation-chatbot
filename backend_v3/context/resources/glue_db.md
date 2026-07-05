# Skill: Glue Database

## Purpose

Use this skill when the user asks for a Glue database, Glue DB, database, catalog, or lakehouse/compute catalog database.

## Source of Truth

Do **not** rely on this markdown for exact field lists, allowed values, dependencies, or required/optional status.
Those come dynamically from `get_resource_info`, which reads `config/resources/glue_db.yaml`.

Use the structured config returned by `get_resource_info` for:

- required fields
- allowed options
- defaults
- dependencies
- pre-validations
- editability
- validation patterns
- normalization hints

## What to Ask

Ask only the missing required collected fields from the structured config.
For Glue DB today, those fields are expected to come from config as:

- `plat_env`
- `intake_id`
- `data_construct`
- `data_layer`
- `data_env`
- `source_name`
- `enterprise_or_func_name`
- `enterprise_or_func_subgrp_name`
- `data_owner_email`
- `data_owner_github_uname`
- `data_leader`

When asking, show valid choices from the config, not from memory.
If a field has options, ask the user to pick one of those exact options.

## Pre-Validation

Glue DB may require pre-validation from config.
Data-owner approval is requested after all required Glue DB collect fields are present, immediately before derivation/confirmation.
If `set_fields` or `create_resources` returns `blocked_by_pre_validation` / `approval_required`, keep using the returned `resource_id` and call the required approval tool with exact `resource_ids`. Do not create duplicate resources after approval.
Do not hardcode approval behavior in the response; follow the tool result.

## Multi-Resource Behavior

If Glue DB is requested with other resources:

1. Ask common missing fields first only.
2. Do not ask Glue-specific fields until the resource-specific step.
3. After common fields are stored, ask Glue-specific missing fields in one concise message.

## Normalization Guidance

Use config normalization before rejecting values.
Examples of safe behavior:

- Accept obvious environment synonyms only if config maps them.
- Accept casing differences only if config/options allow normalization.
- Use configured dependencies, such as `data_layer` depending on `data_construct`.
- Do not create new option values from user wording.

If user wording does not map to a configured option, ask for one valid configured option.
For example, if the user says "analytics database" and config does not clearly identify `data_construct`, ask them to choose from the configured options.

## Response Style

Keep responses short.

Single Glue DB example:
"I can create the Glue DB. Please provide the missing fields from the form."

Multi-resource example:
"First, please provide the shared fields: environment, intake ID, enterprise, and subgroup."

## Error Recovery

- If approval is required, call the required pre-validation tool and continue toward derivation/confirmation on the existing `resource_id` after it passes. Do not retry `create_resources` just because approval passed.
- If tool validation rejects a value, show the valid choices returned from config and ask for the corrected field only.
- If `intake_id_check.valid` is false, ask for a valid approved intake ID and do not proceed to confirmation.

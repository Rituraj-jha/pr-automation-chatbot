"""
Tool registry — maps tool names to implementations and OpenAI function schemas.
Central place to register all tools the agent can use.
"""
from __future__ import annotations

from typing import Callable, Any

from tools.session_tools import get_session_state, create_resources, drop_resource, clone_resource
from tools.field_tools import set_fields, get_resource_info, edit_derived_field, get_common_fields
from tools.derive_tools import derive_fields
from tools.generate_tools import generate_yaml
from tools.validate_tools import validate_fields
from tools.reviewer_tools import review_yaml
from tools.intake_tools import check_intake_id, validate_approval_image, validate_data_owner_approval_document
from tools.preference_tools import update_user_profile
from tools.pr_tools import create_pr, create_update_pr, prepare_pr_intake, set_pr_intake_answers
from tools.repo_tools import (
    check_resource_exists,
    check_update_capability,
    fetch_existing_resource_file,
    preview_update_diff,
    stage_append_only_update,
    stage_full_updated_yaml,
    validate_append_only_change,
)

# ─── Tool function map ────────────────────────────────────────────────────────

TOOL_FUNCTIONS: dict[str, Callable] = {
    "get_session_state": get_session_state,
    "create_resources": create_resources,
    "drop_resource": drop_resource,
    "clone_resource": clone_resource,
    "set_fields": set_fields,
    "get_resource_info": get_resource_info,
    "get_common_fields": get_common_fields,
    "edit_derived_field": edit_derived_field,
    "derive_fields": derive_fields,
    "generate_yaml": generate_yaml,
    "validate_fields": validate_fields,
    "review_yaml": review_yaml,
    "check_intake_id": check_intake_id,
    "validate_data_owner_approval_document": validate_data_owner_approval_document,
    "validate_approval_image": validate_approval_image,
    "check_resource_exists": check_resource_exists,
    "check_update_capability": check_update_capability,
    "fetch_existing_resource_file": fetch_existing_resource_file,
    "stage_append_only_update": stage_append_only_update,
    "stage_full_updated_yaml": stage_full_updated_yaml,
    "validate_append_only_change": validate_append_only_change,
    "preview_update_diff": preview_update_diff,
    "update_user_profile": update_user_profile,
    "prepare_pr_intake": prepare_pr_intake,
    "set_pr_intake_answers": set_pr_intake_answers,
    "create_pr": create_pr,
    "create_update_pr": create_update_pr,
}

# ─── OpenAI tool schemas ─────────────────────────────────────────────────────

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_session_state",
            "description": "Get the current session state including all resources and their statuses/fields. State is auto-injected each turn, but call this if you need a refresh.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_resources",
            "description": "Create one or more new resources only for a new create request. Pass initial_fields with any values extracted from the user's message (e.g. plat_env, enterprise). Remaining fields will be auto-prefilled from session history. If create_resources already returned resource_ids that are pending approval or field collection, do not call this again; continue with set_fields on those existing resource_ids. If called again with the same active resource type and intake_id, the tool reuses the existing resource instead of creating a duplicate.",
            "parameters": {
                "type": "object",
                "properties": {
                    "resources": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "resource_type": {
                                    "type": "string",
                                    "description": "Type of resource (e.g. 's3', 'glue_db')",
                                },
                                "initial_fields": {
                                    "type": "object",
                                    "description": "Fields extracted from the user's message to set immediately (e.g. {\"plat_env\": \"dev\", \"enterprise_or_func_name\": \"AGTR\"}). These take priority over prefilled values from session history.",
                                },
                            },
                            "required": ["resource_type"],
                        },
                        "description": "List of resources to create",
                    },
                },
                "required": ["resources"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "drop_resource",
            "description": "Drop/abandon a resource. Use when user wants to cancel a specific resource.",
            "parameters": {
                "type": "object",
                "properties": {
                    "resource_id": {
                        "type": "string",
                        "description": "ID of the resource to drop (e.g. 's3_0')",
                    },
                },
                "required": ["resource_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clone_resource",
            "description": "Clone a new resource from an existing one, copying all collected fields. Optionally override specific fields. Use when user says 'same as previous but change X'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "source_resource_id": {
                        "type": "string",
                        "description": "ID of the resource to clone from (e.g. 's3_0')",
                    },
                    "overrides": {
                        "type": "object",
                        "description": "Fields to override in the clone (e.g. {\"enterprise_or_func_name\": \"CORP\"})",
                    },
                },
                "required": ["source_resource_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_fields",
            "description": "Set collected field values on a resource after extracting from user message. Handles normalization and validation. When all required fields are set, derivation runs automatically.",
            "parameters": {
                "type": "object",
                "properties": {
                    "resource_id": {
                        "type": "string",
                        "description": "ID of the resource (e.g. 's3_0')",
                    },
                    "fields": {
                        "type": "object",
                        "description": "Key-value pairs of field names and their values",
                    },
                },
                "required": ["resource_id", "fields"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_resource_info",
            "description": "Get the field specification and context for a resource type. Returns what fields to collect, what to derive, and behavioral instructions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "resource_type": {
                        "type": "string",
                        "description": "Type of resource (e.g. 's3')",
                    },
                },
                "required": ["resource_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_derived_field",
            "description": "Edit a derived field value (e.g. bucket_name, bucket_description). Only works on fields marked as 'constrained' or 'free'. Locked fields (aws_account_id, aws_region) cannot be changed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "resource_id": {
                        "type": "string",
                        "description": "ID of the resource",
                    },
                    "field_name": {
                        "type": "string",
                        "description": "Name of the derived field to edit",
                    },
                    "value": {
                        "type": "string",
                        "description": "New value for the field",
                    },
                },
                "required": ["resource_id", "field_name", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "derive_fields",
            "description": "Derive computable fields (bucket_name, account_id, etc.) from collected values. Normally auto-triggered — call manually only if you need to re-derive after a field change.",
            "parameters": {
                "type": "object",
                "properties": {
                    "resource_id": {
                        "type": "string",
                        "description": "ID of the resource to derive fields for",
                    },
                },
                "required": ["resource_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_yaml",
            "description": "Generate the final YAML output for a confirmed resource. Only call after user explicitly confirms. Auto-triggers review_yaml via guardrail.",
            "parameters": {
                "type": "object",
                "properties": {
                    "resource_id": {
                        "type": "string",
                        "description": "ID of the resource to generate YAML for",
                    },
                },
                "required": ["resource_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_common_fields",
            "description": "Find fields to batch for multi-resource collection. For multiple resources of the same type, returns reusable/session_reuse required fields as common_fields to ask once, and non-reusable required fields as specific_fields to ask per resource. Do not dump the full form per resource when common_fields are available.",
            "parameters": {
                "type": "object",
                "properties": {
                    "resource_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of resource types to compare (e.g. ['s3', 'glue_db'])",
                    },
                },
                "required": ["resource_types"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "validate_fields",
            "description": "Pre-store validation for collected field values. Validates candidate fields against resource config before set_fields writes them to state: normalizes values, rejects unknown fields, enforces allowed options/regex, and runs dependent/cross-field checks. If invalid, use field_errors to ask for corrected values instead of calling set_fields for those values.",
            "parameters": {
                "type": "object",
                "properties": {
                    "resource_id": {
                        "type": "string",
                        "description": "ID of the resource to validate",
                    },
                    "fields": {
                        "type": "object",
                        "description": "Candidate field values to validate before set_fields. If omitted, validates current collected state.",
                    },
                },
                "required": ["resource_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "review_yaml",
            "description": "Run business-rule review on a confirmed resource. Quality gate between CONFIRMING and DONE. Normally auto-triggered after generate_yaml — call manually only to re-review after fixing errors.",
            "parameters": {
                "type": "object",
                "properties": {
                    "resource_id": {
                        "type": "string",
                        "description": "ID of the resource to review",
                    },
                },
                "required": ["resource_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_intake_id",
            "description": "Check if an intake ID exists in the approved intake list (Power BI). Call this after the user provides their intake_id to verify it's valid before proceeding.",
            "parameters": {
                "type": "object",
                "properties": {
                    "intake_id": {
                        "type": "string",
                        "description": "The intake ID to validate (e.g. 'M0000485')",
                    },
                },
                "required": ["intake_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_resource_exists",
            "description": "Create-route guardrail tool. After derivation, check if the derived resource YAML already exists in the configured MIW/GitHub repo path. If it exists, create flow must be blocked; do not switch to update flow.",
            "parameters": {
                "type": "object",
                "properties": {
                    "resource_id": {
                        "type": "string",
                        "description": "ID of the derived resource to check, e.g. 's3_0'.",
                    },
                },
                "required": ["resource_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_update_capability",
            "description": "Update-route tool. Check whether a resource type supports update flow and what inputs are required before fetching. After this tool returns, ask the user for missing required_inputs; do not invent branch or file_path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "resource_type": {
                        "type": "string",
                        "description": "Resource type to check, e.g. 's3'.",
                    },
                },
                "required": ["resource_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_existing_resource_file",
            "description": "Update-route tool. Fetch an existing resource YAML file from the configured repo source. Call after the user has explicitly provided branch and either resource_name or repo-relative file_path. Prefer resource_name; backend can locate the file from repo config. Do not invent placeholder values.",
            "parameters": {
                "type": "object",
                "properties": {
                    "resource_type": {
                        "type": "string",
                        "description": "Resource type, e.g. 's3'.",
                    },
                    "branch": {
                        "type": "string",
                        "description": "Target branch explicitly provided by the user, e.g. 'main'. Do not invent this value.",
                    },
                    "file_path": {
                        "type": "string",
                        "description": "Optional repo-relative YAML file path explicitly provided by the user, under aws_lakehouse/, e.g. aws_lakehouse/lakehouse-001/s3/prd-lh1-agtr-src.yaml. Do not invent this value.",
                    },
                    "resource_name": {
                        "type": "string",
                        "description": "Optional existing resource name explicitly provided by the user, e.g. S3 bucket name prd-lh1-agtr-src. Use this when full file_path is not provided.",
                    },
                },
                "required": ["resource_type", "branch"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stage_append_only_update",
            "description": "Update-route tool. Stage an append-only YAML change by appending new lines to the fetched original YAML, then return updated YAML and git diff.",
            "parameters": {
                "type": "object",
                "properties": {
                    "resource_type": {"type": "string", "description": "Resource type, e.g. 's3'."},
                    "branch": {"type": "string", "description": "Target branch."},
                    "file_path": {"type": "string", "description": "Repo-relative file path."},
                    "original_yaml": {"type": "string", "description": "Original YAML content fetched from repo."},
                    "appended_yaml": {"type": "string", "description": "Only the new YAML lines/block to append."},
                },
                "required": ["file_path", "original_yaml", "appended_yaml"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "validate_append_only_change",
            "description": "Update-route guardrail tool. Validate that updated YAML only appends new content and does not modify or delete existing YAML.",
            "parameters": {
                "type": "object",
                "properties": {
                    "original_yaml": {"type": "string", "description": "Original YAML content."},
                    "updated_yaml": {"type": "string", "description": "Proposed updated YAML content."},
                },
                "required": ["original_yaml", "updated_yaml"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stage_full_updated_yaml",
            "description": "Update-route tool. Stage a full edited YAML document only if it preserves all existing content and appends new lines only. Use when the user edits the update diff/editor content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "resource_type": {"type": "string", "description": "Resource type, e.g. 's3'."},
                    "branch": {"type": "string", "description": "Target branch."},
                    "file_path": {"type": "string", "description": "Repo-relative file path."},
                    "original_yaml": {"type": "string", "description": "Original YAML content fetched from repo."},
                    "updated_yaml": {"type": "string", "description": "Full edited YAML content from the user/editor."},
                },
                "required": ["file_path", "original_yaml", "updated_yaml"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "preview_update_diff",
            "description": "Update-route tool. Generate a unified git-style diff between original and updated YAML for user review.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Repo-relative file path."},
                    "original_yaml": {"type": "string", "description": "Original YAML content."},
                    "updated_yaml": {"type": "string", "description": "Updated YAML content."},
                },
                "required": ["file_path", "original_yaml", "updated_yaml"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "validate_data_owner_approval_document",
            "description": "Mock-validate uploaded data owner approval evidence for resources that require it. Accepts frontend-provided PDF/image metadata or content. Call this when create_resources returns blocked_by_pre_validation with required_tool validate_data_owner_approval_document.",
            "parameters": {
                "type": "object",
                "properties": {
                    "resource_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Blocked resource types that require approval, e.g. ['glue_db']",
                    },
                    "resource_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional exact pending resource IDs this approval document applies to, e.g. ['glue_db_0']. Use this for multi-resource requests with the same resource type. If the same document covers multiple resources, include all matching resource IDs.",
                    },
                    "file_id": {
                        "type": "string",
                        "description": "Backend file_id sent by the frontend after /api/data-owner-approval/upload. Prefer this over raw file content; do not ask the user to manually type it.",
                    },
                    "file_name": {
                        "type": "string",
                        "description": "Uploaded file name from frontend, e.g. approval.pdf or screenshot.png",
                    },
                    "file_type": {
                        "type": "string",
                        "description": "MIME type from frontend, e.g. application/pdf or image/png",
                    },
                    "file_content_base64": {
                        "type": "string",
                        "description": "Optional base64 file content. For now this is accepted but not analyzed.",
                    },
                    "file_url": {
                        "type": "string",
                        "description": "Optional uploaded-file URL or backend file reference.",
                    },
                    "intake_id": {
                        "type": "string",
                        "description": "Optional intake ID to associate with approval validation.",
                    },
                },
                "required": ["resource_types"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "validate_approval_image",
            "description": "Legacy alias for validate_data_owner_approval_document. Prefer validate_data_owner_approval_document for new flows.",
            "parameters": {
                "type": "object",
                "properties": {
                    "resource_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of resource types that require approval (e.g. ['glue_db'])",
                    },
                },
                "required": ["resource_types"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_user_profile",
            "description": "Update the user's behavioral profile based on observed patterns. Call after productive interactions to record: preferred enterprise, typical usage, interaction style, common field defaults. Profile is a cumulative natural language description.",
            "parameters": {
                "type": "object",
                "properties": {
                    "profile": {
                        "type": "string",
                        "description": "Full updated profile text (replaces previous). Include all prior observations plus new ones.",
                    },
                },
                "required": ["profile"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "prepare_pr_intake",
            "description": "Prepare PR creation metadata from pr_template.yaml. Auto-fills safe answers from completed resources/session state, previews labels, and returns missing required PR intake answers, label answers, and target branch. Call this first when the user explicitly asks to create/raise/submit a PR.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_branch": {
                        "type": "string",
                        "description": "Optional target branch if the user already provided it, e.g. 'main' or 'dev'.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_pr_intake_answers",
            "description": "Store and validate user-provided PR template answers before create_pr. Validates configured options such as PII, Wave, and Team. Returns readiness; call create_pr only when ready is true.",
            "parameters": {
                "type": "object",
                "properties": {
                    "intake_answers": {
                        "type": "object",
                        "description": "PR intake answers keyed by pr_template.yaml question id, e.g. {\"consumers\": \"Analytics team\", \"pii\": \"No\", \"compliance\": \"None\"}.",
                    },
                    "label_answers": {
                        "type": "object",
                        "description": "PR label answers keyed by label prefix for ask labels, e.g. {\"Wave\": \"W2\", \"Team\": \"DataEng\"}.",
                    },
                    "target_branch": {
                        "type": "string",
                        "description": "Target branch to push to and open PR against, e.g. 'main' or 'dev'.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_pr",
            "description": "Create a pull request with all completed (DONE) resources only after PR intake is complete. Before calling, call prepare_pr_intake and set_pr_intake_answers until ready is true. Commits YAML files to the user's fork and opens a cross-fork PR to upstream.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_branch": {
                        "type": "string",
                        "description": "The branch name to push to in the fork and create PR against in the upstream repo (e.g. 'main', 'dev')."
                    }
                },
                "required": ["target_branch"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_update_pr",
            "description": "Update-route tool. Create a PR for the staged append-only update after the user confirms the diff. Requires append-only validation to have passed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_branch": {
                        "type": "string",
                        "description": "The branch name to push to and open PR against, e.g. 'main' or 'dev'."
                    }
                },
                "required": ["target_branch"],
            },
        },
    },
]

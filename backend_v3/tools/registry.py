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
from tools.intake_tools import check_intake_id, validate_approval_image
from tools.preference_tools import update_user_profile
from tools.pr_tools import create_pr

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
    "validate_approval_image": validate_approval_image,
    "update_user_profile": update_user_profile,
    "create_pr": create_pr,
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
            "description": "Create one or more new resources. Pass initial_fields with any values extracted from the user's message (e.g. plat_env, enterprise). Remaining fields will be auto-prefilled from session history. If all fields are complete, derivation fires automatically.",
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
            "description": "Find fields shared across multiple resource types for multi-resource batching. Returns common fields (ask once for all) and specific fields (ask per resource).",
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
            "description": "Run 4-stage validation pipeline on a resource's fields (normalize → static → dependent → cross-field). Call to explicitly validate before storing, or to check current state.",
            "parameters": {
                "type": "object",
                "properties": {
                    "resource_id": {
                        "type": "string",
                        "description": "ID of the resource to validate",
                    },
                    "fields": {
                        "type": "object",
                        "description": "Specific fields to validate. If omitted, validates all collected fields.",
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
            "name": "validate_approval_image",
            "description": "Validate data owner approval for resources that require it (e.g. glue_db). Call this BEFORE creating resources that have pre_validations: [data_owner_approval] in their config. For now, pass the resource_types that need approval.",
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
            "name": "create_pr",
            "description": "Create a pull request with all completed (DONE) resources. Commits YAML files to the user's fork and opens a cross-fork PR to the upstream repo. The PR is created from the same branch in the fork to the same branch in upstream. Only call when user explicitly requests PR creation (e.g. 'create PR', 'submit', 'raise PR'). Always ask the user which branch to target.",
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
]

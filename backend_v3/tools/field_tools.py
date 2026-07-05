"""Field tools — set/get field values and resource specifications."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from models.state import ResourceStatus
from tools.session_tools import (
    _get_session,
    _missing_required_pre_validations,
    _stage_pending_approval_if_collection_complete,
)
from db.repository import load_session_fields, save_resource

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
_CONTEXT_DIR = Path(__file__).resolve().parent.parent / "context"

# Cache for loaded resource configs
_resource_configs: dict[str, dict] = {}


def _load_resource_config(resource_type: str) -> dict | None:
    """Load the YAML config for a resource type."""
    if resource_type in _resource_configs:
        return _resource_configs[resource_type]

    path = _CONFIG_DIR / "resources" / f"{resource_type}.yaml"
    if not path.exists():
        return None

    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    _resource_configs[resource_type] = config
    return config


def _normalize_value(field_name: str, value: Any, config: dict) -> Any:
    """Normalize a field value using the resource config's normalize map."""
    if value is None:
        return value

    str_value = str(value).strip()

    # Check collect_fields for normalize rules
    for field_spec in config.get("collect_fields", []):
        if field_spec["name"] != field_name:
            continue

        # Case normalization
        if field_spec.get("normalize_case") == "upper":
            return str_value.upper()

        # Lookup normalization
        normalize_map = field_spec.get("normalize", {})
        if normalize_map:
            lookup = str_value.lower()
            if lookup in normalize_map:
                return normalize_map[lookup]

        # If has options, try case-insensitive match
        # Options can be plain strings or dicts with "value" key
        options = field_spec.get("options", [])
        if options:
            option_values = _extract_option_values(options)
            for opt in option_values:
                if opt.lower() == str_value.lower():
                    return opt

        break

    return str_value


def _extract_option_values(options: list) -> list[str]:
    """Extract option values from either plain strings or dicts with 'value' key."""
    values = []
    for opt in options:
        if isinstance(opt, dict):
            values.append(opt["value"])
        else:
            values.append(str(opt))
    return values


async def _validate_external_field(field_name: str, value: Any) -> tuple[bool, str | None, dict | None]:
    """Run external/pre-store validation for fields that need it."""
    if field_name != "intake_id":
        return True, None, None

    from tools.intake_tools import check_intake_id

    check_result = await check_intake_id(intake_id=str(value))
    try:
        check_data = json.loads(check_result)
    except json.JSONDecodeError:
        return False, "Could not validate intake ID. Please try again.", None

    status = check_data.get("status")
    can_start_chat = check_data.get("can_start_chat")

    if status is not None:
        if status != "approved_and_ready_for_design" or not can_start_chat:
            return False, check_data.get("message", "Intake ID is not approved."), check_data
    elif not check_data.get("valid"):
        return False, check_data.get("message", "Intake ID is not approved."), check_data

    return True, None, check_data


async def set_fields(resource_id: str, fields: dict, **kwargs) -> str:
    """Set field values on a resource with normalization."""
    session = _get_session()
    resource = session.get_resource(resource_id)

    if not resource:
        return json.dumps({"error": f"Resource '{resource_id}' not found"})

    if resource.status in (ResourceStatus.DONE, ResourceStatus.DROPPED):
        return json.dumps({"error": f"Cannot set fields — resource status is '{resource.status.value}'. Resource is finalized."})

    config = _load_resource_config(resource.resource_type)
    if not config:
        return json.dumps({"error": f"No config for resource type '{resource.resource_type}'"})

    set_fields_result = {}
    errors = {}
    validation_details = {}
    validated_fields = {}

    from tools.validate_tools import validate_collect_fields

    pre_store_validation = validate_collect_fields(
        resource_type=resource.resource_type,
        current_fields=resource.collected_fields,
        incoming_fields=fields,
    )

    field_errors = pre_store_validation.get("field_errors", {}) or {}
    for field_name, detail in field_errors.items():
        errors[field_name] = detail.get("message", "Invalid value")
        validation_details[field_name] = detail

    cross_field_errors = pre_store_validation.get("cross_field_errors", []) or []
    for index, error in enumerate(cross_field_errors, start=1):
        errors[f"_cross_field_{index}"] = error

    normalized_candidates = pre_store_validation.get("normalized", {}) or {}
    if cross_field_errors:
        normalized_candidates = {}

    for field_name, normalized in normalized_candidates.items():
        if field_name in field_errors:
            continue

        external_valid, external_error, external_detail = await _validate_external_field(field_name, normalized)
        if not external_valid:
            errors[field_name] = external_error or "External validation failed"
            if external_detail:
                validation_details[field_name] = external_detail
            continue

        if external_detail:
            validation_details[field_name] = external_detail
        validated_fields[field_name] = normalized

    if validated_fields:
        # If user changes a collected field while in CONFIRMING/REVIEWING, revert to COLLECTING
        # only after at least one new value has passed validation.
        if resource.status in (ResourceStatus.CONFIRMING, ResourceStatus.REVIEWING):
            resource.status = ResourceStatus.COLLECTING
            resource.derived_fields = {}
            resource.user_overrides = {}
            resource.yaml_output = None

        for field_name, normalized in validated_fields.items():
            resource.collected_fields[field_name] = normalized
            set_fields_result[field_name] = normalized

    # Check if all required collect_fields are now set
    all_collected = True
    missing = []
    for field_spec in config.get("collect_fields", []):
        field_name_spec = field_spec["name"]

        # Determine if this field is actually required given current state
        is_required = field_spec.get("required", False)
        allow_empty = field_spec.get("allow_empty", False)

        # Handle required_when: field is required only when condition is met
        required_when = field_spec.get("required_when")
        if required_when and not is_required:
            # Parse "field_name == value" condition
            if " == " in required_when:
                cond_field, cond_value = required_when.split(" == ", 1)
                cond_field = cond_field.strip()
                cond_value = cond_value.strip()
                actual = resource.collected_fields.get(cond_field, "")
                if str(actual).strip() == cond_value:
                    is_required = True
                    allow_empty = False

        if not is_required:
            continue
        if allow_empty:
            continue
        if field_name_spec not in resource.collected_fields:
            all_collected = False
            missing.append(field_name_spec)

    if validated_fields:
        await save_resource(session.session_id, resource)

    field_collection_complete = all_collected
    pending_approval = None
    missing_pre_validations = []
    if all_collected:
        session_fields = await load_session_fields(session.session_id)
        missing_pre_validations, _validation_details = _missing_required_pre_validations(resource, config, session_fields)
        if missing_pre_validations:
            pending_approval = await _stage_pending_approval_if_collection_complete(session)
            all_collected = False

    result = {
        "resource_id": resource.resource_id,
        "set": set_fields_result,
        "errors": errors if errors else None,
        "validation_details": validation_details if validation_details else None,
        "pre_store_validation": pre_store_validation,
        "field_collection_complete": field_collection_complete,
        "missing_pre_validations": missing_pre_validations if missing_pre_validations else None,
        "approval_required": pending_approval,
        "approval_deferred_until_all_resources_collected": bool(missing_pre_validations and not pending_approval),
        "collection_complete": all_collected,
        "missing_fields": missing if missing else None,
    }
    return json.dumps({k: v for k, v in result.items() if v is not None})


async def get_resource_info(resource_type: str, **kwargs) -> str:
    """Load the resource skill plus structured config summary for the LLM."""
    # Load the MD context file — this is what the LLM reads
    context_path = _CONTEXT_DIR / "resources" / f"{resource_type}.md"
    if context_path.exists():
        context_md = context_path.read_text(encoding="utf-8")
    else:
        context_md = f"No context available for resource type '{resource_type}'."

    config = _load_resource_config(resource_type)
    if not config:
        return json.dumps({
            "resource_type": resource_type,
            "skill": context_md,
            "error": f"No config found for resource type '{resource_type}'",
        })

    collect_fields = []
    for field in config.get("collect_fields", []):
        collect_fields.append({
            "name": field.get("name"),
            "label": field.get("label", field.get("name")),
            "description": field.get("description", ""),
            "group": field.get("group"),
            "required": field.get("required", False),
            "allow_empty": field.get("allow_empty", False),
            "required_when": field.get("required_when"),
            "depends_on": field.get("depends_on"),
            "default_from": field.get("default_from"),
            "session_reuse": field.get("session_reuse", False),
            "options": _extract_option_values(field.get("options", [])) if field.get("options") else None,
            "normalize": field.get("normalize"),
            "normalize_case": field.get("normalize_case"),
            "validation": field.get("validation"),
        })

    derived_fields_after_collection = [
        {
            "name": field.get("name"),
            "label": field.get("label", field.get("name")),
            "editable": field.get("editable", "locked"),
            "do_not_ask_during_collection": True,
        }
        for field in config.get("derive_fields", [])
    ]

    return json.dumps({
        "resource_type": resource_type,
        "display_name": config.get("display_name", resource_type),
        "skill": context_md,
        "pre_validations": config.get("pre_validations", []),
        "collection_instruction": "When asking for missing values, ask only collect_fields. Do not ask for derived_fields_after_collection; they are calculated after collection.",
        "collect_fields": collect_fields,
        "derived_fields_after_collection": derived_fields_after_collection,
        "file_name_field": config.get("file_name_field"),
    }, indent=2)


async def edit_derived_field(resource_id: str, field_name: str, value: str, **kwargs) -> str:
    """Edit a derived field (user override). Validates against editability rules in config."""
    session = _get_session()
    resource = session.get_resource(resource_id)

    if not resource:
        return json.dumps({"error": f"Resource '{resource_id}' not found"})

    if resource.status not in (ResourceStatus.CONFIRMING, ResourceStatus.REVIEWING):
        return json.dumps({"error": f"Cannot edit derived fields — resource must be in 'confirming' or 'reviewing' state. Current: {resource.status.value}"})

    config = _load_resource_config(resource.resource_type)
    if not config:
        return json.dumps({"error": f"No config for resource type '{resource.resource_type}'"})

    # Find the derive field spec
    derive_spec = next(
        (f for f in config.get("derive_fields", []) if f["name"] == field_name),
        None,
    )
    if not derive_spec:
        return json.dumps({"error": f"'{field_name}' is not a derived field"})

    editable = derive_spec.get("editable", "locked")
    if editable == "locked":
        return json.dumps({"error": f"'{field_name}' is locked and cannot be edited"})

    # Validate constrained fields
    if editable == "constrained":
        validation = derive_spec.get("validation")
        if validation and not re.match(validation, str(value)):
            return json.dumps({"error": f"Invalid format for {field_name}. Must match: {validation}"})

    # Validate free fields
    if editable == "free":
        max_length = derive_spec.get("max_length", 256)
        if len(str(value)) > max_length:
            return json.dumps({"error": f"'{field_name}' exceeds max length of {max_length}"})

    # Store as user override
    resource.user_overrides[field_name] = value
    await save_resource(session.session_id, resource)

    return json.dumps({
        "resource_id": resource.resource_id,
        "field": field_name,
        "old_value": resource.derived_fields.get(field_name),
        "new_value": value,
        "source": "user_override",
    })


async def get_common_fields(resource_types: list[str], **kwargs) -> str:
    """Find fields shared across multiple resource types (same name + same group).

    Used to identify which fields to ask once for all resources (multi-resource batching).
    Returns: {common_fields: [...], specific_fields: {type: [...]}}
    """
    if not resource_types:
        return json.dumps({"error": "No resource types provided"})

    normalized_types = [str(rt).strip().lower() for rt in resource_types if str(rt).strip()]

    # Load configs for each unique type
    configs: dict[str, dict] = {}
    for rt in normalized_types:
        config = _load_resource_config(rt)
        if config:
            configs[rt] = config

    # Multiple resources of the same type still have shared/reusable fields.
    # Previously two Glue DBs collapsed to one config and returned no common
    # fields, causing the LLM to dump the full Glue form once per resource.
    if len(normalized_types) > 1 and len(configs) == 1:
        rt = next(iter(configs.keys()))
        config = configs[rt]
        common_fields = []
        specific_fields = []
        for field in config.get("collect_fields", []):
            field_name = field.get("name")
            if not field_name or field_name == "intake_id":
                continue
            if not field.get("required", False):
                continue
            if field.get("session_reuse", False):
                common_fields.append(field_name)
            else:
                specific_fields.append(field_name)
        return json.dumps({
            "common_fields": sorted(common_fields),
            "specific_fields": {rt: specific_fields},
            "instruction": "Ask common_fields once for all active resources. Do not repeat the full field list per resource. After common fields are set, ask specific_fields per resource.",
        })

    if len(configs) < 2:
        # Only one type — everything is "specific"
        if configs:
            rt = list(configs.keys())[0]
            fields = [f["name"] for f in configs[rt].get("collect_fields", [])]
            return json.dumps({"common_fields": [], "specific_fields": {rt: fields}})
        return json.dumps({"common_fields": [], "specific_fields": {}})

    # Build field→group map per resource type
    field_groups: dict[str, dict[str, str]] = {}  # {resource_type: {field_name: group}}
    for rt, config in configs.items():
        field_groups[rt] = {}
        for f in config.get("collect_fields", []):
            field_groups[rt][f["name"]] = f.get("group", "")

    # Find common fields: same name AND same group across ALL types
    all_field_names = set()
    for fg in field_groups.values():
        all_field_names.update(fg.keys())

    common_fields = []
    for field_name in all_field_names:
        # Check if this field exists in ALL types
        in_all = all(field_name in fg for fg in field_groups.values())
        if not in_all:
            continue
        # Check if same non-empty group
        groups = {fg[field_name] for fg in field_groups.values()}
        if len(groups) == 1 and "" not in groups:
            common_fields.append(field_name)

    # Specific fields = fields NOT in common
    specific_fields: dict[str, list[str]] = {}
    for rt, fg in field_groups.items():
        specific = [f for f in fg if f not in common_fields]
        if specific:
            specific_fields[rt] = specific

    return json.dumps({
        "common_fields": sorted(common_fields),
        "specific_fields": specific_fields,
    })

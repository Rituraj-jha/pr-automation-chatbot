"""Generate tools — produce final YAML from confirmed resource fields."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml as pyyaml

from models.state import ResourceStatus
from tools.session_tools import _get_session
from db.repository import load_session_fields, save_resource

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def _load_resource_config(resource_type: str) -> dict:
    path = _CONFIG_DIR / "resources" / f"{resource_type}.yaml"
    with open(path, "r", encoding="utf-8") as f:
        return pyyaml.safe_load(f)


def _generate_s3_yaml(all_fields: dict[str, Any], config: dict) -> str:
    """Generate S3 YAML following field order and quoting rules."""
    yaml_config = config.get("yaml_output", {})
    field_order = yaml_config.get("field_order", [])
    quoting = yaml_config.get("quoting", {})
    conditional = yaml_config.get("conditional_fields", [])

    lines = []
    usage_type = all_fields.get("usage_type", "")

    for field_name in field_order:
        # Check conditional fields
        is_conditional = False
        for cond in conditional:
            if cond["field"] == field_name:
                is_conditional = True
                condition = cond.get("include_when", "")
                if "Scripts" in condition and usage_type != "Scripts":
                    break  # skip this field
                # Include with fixed value
                lines.append(f"{field_name}: {cond['value']}")
                break

        if is_conditional:
            continue

        value = all_fields.get(field_name)
        if value is None:
            continue

        # Apply quoting rules
        quote_rule = quoting.get(field_name, quoting.get("default", "none"))

        if quote_rule == "single":
            lines.append(f"{field_name}: '{value}'")
        elif quote_rule == "double_if_spaces" and " " in str(value):
            lines.append(f'{field_name}: "{value}"')
        elif quote_rule == "double_if_empty" and value == "":
            lines.append(f'{field_name}: ""')
        else:
            lines.append(f"{field_name}: {value}")

    return "\n".join(lines) + "\n"


def _generate_glue_db_yaml(all_fields: dict[str, Any], config: dict) -> str:
    """Generate Glue DB YAML following field order and quoting rules."""
    yaml_config = config.get("yaml_output", {})
    field_order = yaml_config.get("field_order", [])
    quoting = yaml_config.get("quoting", {})

    lines = []

    for field_name in field_order:
        value = all_fields.get(field_name)
        if value is None:
            continue

        # Apply quoting rules
        quote_rule = quoting.get(field_name, quoting.get("default", "none"))

        if quote_rule == "single":
            lines.append(f"{field_name}: '{value}'")
        elif quote_rule == "double":
            lines.append(f'{field_name}: "{value}"')
        elif quote_rule == "double_if_empty" and value == "":
            lines.append(f'{field_name}: ""')
        else:
            lines.append(f"{field_name}: {value}")

    return "\n".join(lines) + "\n"


async def generate_yaml(resource_id: str, **kwargs) -> str:
    """Generate YAML for a confirmed resource."""
    session = _get_session()
    resource = session.get_resource(resource_id)

    if not resource:
        return json.dumps({"error": f"Resource '{resource_id}' not found"})

    if resource.status not in (ResourceStatus.CONFIRMING, ResourceStatus.REVIEWING):
        return json.dumps({"error": f"Resource must be in 'confirming' or 'reviewing' state for YAML generation. Current: {resource.status.value}"})

    session_fields = await load_session_fields(session.session_id)
    exists_key = f"__resource_exists:{resource.resource_id}"
    existence_value = session_fields.get(exists_key)
    if existence_value in {"true", "unknown"}:
        detail_raw = session_fields.get(f"__resource_existence_detail:{resource.resource_id}")
        detail = {}
        if detail_raw:
            try:
                detail = json.loads(detail_raw)
            except json.JSONDecodeError:
                detail = {}
        if existence_value == "unknown":
            return json.dumps({
                "error": "Cannot generate YAML for create PR because repository existence could not be verified.",
                "resource_id": resource.resource_id,
                "resource_type": resource.resource_type,
                "path": detail.get("path"),
                "action_needed": detail.get("action_needed"),
                "next_action": "Authenticate/configure GitHub repository access, then re-check whether this resource exists.",
            })
        return json.dumps({
            "error": "Cannot generate YAML for create PR because this resource already exists in the repository.",
            "resource_id": resource.resource_id,
            "resource_type": resource.resource_type,
            "path": detail.get("path"),
            "next_action": "Change the fields/name that derive the resource name, or create another resource. This create flow will not switch to update automatically.",
        })

    config = _load_resource_config(resource.resource_type)
    all_fields = resource.all_fields

    # Route to resource-specific generator
    if resource.resource_type == "s3":
        yaml_output = _generate_s3_yaml(all_fields, config)
    elif resource.resource_type == "glue_db":
        yaml_output = _generate_glue_db_yaml(all_fields, config)
    else:
        # Generic: just dump fields in order
        yaml_output = pyyaml.dump(all_fields, default_flow_style=False)

    # Store YAML output but do NOT change status — reviewer guardrail handles DONE transition
    resource.yaml_output = yaml_output
    await save_resource(session.session_id, resource)

    return json.dumps({
        "resource_id": resource.resource_id,
        "status": resource.status.value,
        "yaml": yaml_output,
    })

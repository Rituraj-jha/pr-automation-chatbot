"""Validate tools — 4-stage field validation pipeline.

Stages:
  1. Normalize (case, aliases)
  2. Static validation (regex, options, required)
  3. Dependent validation (enterprise→subgroup, data_construct→data_layer)
  4. Cross-field validation (account type vs usage_type, S3 location consistency)

Currently stages 3 and 4 are mocked (always pass).
TODO: Implement real dependent + cross-field validation logic.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from tools.session_tools import _get_session

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"

# Cache
_dependent_fields: dict | None = None


def _load_dependent_fields() -> dict:
    """Load dependent field mappings."""
    global _dependent_fields
    if _dependent_fields is None:
        path = _CONFIG_DIR / "validations" / "dependent_fields.yaml"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                _dependent_fields = yaml.safe_load(f) or {}
        else:
            _dependent_fields = {}
    return _dependent_fields


def _load_resource_config(resource_type: str) -> dict | None:
    path = _CONFIG_DIR / "resources" / f"{resource_type}.yaml"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _stage1_normalize(field_name: str, value: Any, field_spec: dict) -> Any:
    """Stage 1: Normalize value using field spec rules."""
    if value is None:
        return value
    str_value = str(value).strip()

    # Case normalization
    if field_spec.get("normalize_case") == "upper":
        return str_value.upper()

    # Lookup normalization
    normalize_map = field_spec.get("normalize", {})
    if normalize_map:
        lookup = str_value.lower()
        if lookup in normalize_map:
            return normalize_map[lookup]

    # Options case-insensitive match
    options = field_spec.get("options", [])
    if options:
        for opt in options:
            opt_val = opt["value"] if isinstance(opt, dict) else str(opt)
            if opt_val.lower() == str_value.lower():
                return opt_val

    return str_value


def _extract_option_values(options: list) -> list[str]:
    """Extract configured option values from strings or {value,label} objects."""
    values = []
    for opt in options or []:
        if isinstance(opt, dict):
            values.append(str(opt.get("value", "")))
        else:
            values.append(str(opt))
    return [value for value in values if value != ""]


def _collect_field_specs(config: dict) -> dict[str, dict]:
    """Return collect field specs keyed by field name."""
    return {
        str(field.get("name")): field
        for field in config.get("collect_fields", [])
        if field.get("name")
    }


def _field_error(message: str, field_spec: dict | None = None, **extra: Any) -> dict[str, Any]:
    """Build a structured field validation error."""
    payload: dict[str, Any] = {"message": message}
    if field_spec:
        payload["label"] = field_spec.get("label", field_spec.get("name"))
        options = _extract_option_values(field_spec.get("options", []))
        if options:
            payload["allowed_values"] = options
        if field_spec.get("validation"):
            payload["expected_format"] = field_spec.get("validation")
    payload.update({k: v for k, v in extra.items() if v is not None})
    return payload


def _parse_field_from_error(error: str) -> str | None:
    """Best-effort parse of 'field_name: message' validation errors."""
    if ":" not in error:
        return None
    field_name = error.split(":", 1)[0].strip()
    return field_name or None


def _stage2_static(field_name: str, value: Any, field_spec: dict) -> list[str]:
    """Stage 2: Static validation (regex, options check). Returns list of errors."""
    errors = []

    # Options check
    options = field_spec.get("options", [])
    if options:
        valid_values = [
            (o["value"] if isinstance(o, dict) else str(o)) for o in options
        ]
        if value not in valid_values:
            errors.append(f"{field_name}: must be one of {valid_values}, got '{value}'")

    # Regex validation
    validation = field_spec.get("validation")
    if validation and value:
        if not re.match(validation, str(value)):
            errors.append(f"{field_name}: invalid format (must match {validation})")

    return errors


def validate_collect_fields(
    resource_type: str,
    current_fields: dict[str, Any],
    incoming_fields: dict[str, Any],
) -> dict[str, Any]:
    """Validate candidate collect-field values before they are persisted.

    This is the deterministic pre-store gate used by `set_fields` and exposed
    through `validate_fields`. It validates only collect_fields from the resource
    config, normalizes accepted values, rejects unknown fields, enforces allowed
    options/regex, and runs dependent/cross-field checks against the merged
    current + incoming state.
    """
    config = _load_resource_config(resource_type)
    if not config:
        return {
            "valid": False,
            "errors": [f"No config for '{resource_type}'"],
            "field_errors": {},
            "cross_field_errors": [],
            "normalized": {},
            "warnings": [],
        }

    field_specs = _collect_field_specs(config)
    normalized: dict[str, Any] = {}
    field_errors: dict[str, dict[str, Any]] = {}
    cross_field_errors: list[str] = []
    warnings: list[str] = []

    for field_name, value in (incoming_fields or {}).items():
        field_spec = field_specs.get(field_name)
        if not field_spec:
            field_errors[field_name] = _field_error(
                f"'{field_name}' is not a collected field for {resource_type}.",
                allowed_fields=sorted(field_specs.keys()),
            )
            continue

        norm_value = _stage1_normalize(field_name, value, field_spec)
        normalized[field_name] = norm_value

        allow_empty = bool(field_spec.get("allow_empty", False))
        if allow_empty and str(norm_value) == "":
            continue

        options = _extract_option_values(field_spec.get("options", []))
        if options and norm_value not in options:
            field_errors[field_name] = _field_error(
                f"Must be one of: {options}.",
                field_spec,
            )
            continue

        validation = field_spec.get("validation")
        if validation and not re.match(validation, str(norm_value)):
            field_errors[field_name] = _field_error(
                f"Invalid format. Must match pattern: {validation}.",
                field_spec,
            )

    merged = {**(current_fields or {}), **normalized}
    dependent_errors = _stage3_dependent(merged, resource_type)
    cross_errors = _stage4_cross_field(merged, resource_type)
    for error in [*dependent_errors, *cross_errors]:
        parsed_field = _parse_field_from_error(error)
        if parsed_field and parsed_field in field_specs:
            field_errors[parsed_field] = _field_error(error, field_specs.get(parsed_field))
        else:
            cross_field_errors.append(error)

    flat_errors = [
        f"{field_name}: {detail.get('message', 'Invalid value')}"
        for field_name, detail in field_errors.items()
    ] + cross_field_errors

    return {
        "valid": not flat_errors,
        "errors": flat_errors,
        "field_errors": field_errors,
        "cross_field_errors": cross_field_errors,
        "normalized": normalized,
        "warnings": warnings,
    }


def _stage3_dependent(fields: dict, resource_type: str) -> list[str]:
    """Stage 3: Dependent field validation.

    TODO: Implement real logic — check enterprise→subgroup validity,
    data_construct→data_layer validity using dependent_fields.yaml.
    Currently returns empty (always passes).
    """
    errors = []
    dep_config = _load_dependent_fields()

    # Check enterprise → subgroup
    enterprise = fields.get("enterprise_or_func_name", "")
    subgroup = fields.get("enterprise_or_func_subgrp_name", "")
    if enterprise and subgroup:
        mapping = dep_config.get("enterprise_to_subgroup", {})
        if enterprise in mapping:
            valid_options = mapping[enterprise].get("options", [])
            if valid_options and subgroup not in valid_options:
                errors.append(
                    f"enterprise_or_func_subgrp_name: '{subgroup}' is not valid for "
                    f"{enterprise}. Valid: {valid_options}"
                )

    # Check data_construct → data_layer (glue_db only)
    data_construct = fields.get("data_construct", "")
    data_layer = fields.get("data_layer", "")
    if data_construct and data_layer:
        mapping = dep_config.get("data_construct_to_data_layer", {})
        if data_construct in mapping:
            valid_layers = mapping[data_construct].get("options", [])
            if valid_layers and data_layer not in valid_layers:
                errors.append(
                    f"data_layer: '{data_layer}' is not valid for {data_construct}. "
                    f"Valid: {valid_layers}"
                )

    return errors


def _stage4_cross_field(fields: dict, resource_type: str) -> list[str]:
    """Stage 4: Cross-field validation (post-derivation checks).

    TODO: Implement real logic — account type matches usage_type/data_construct,
    S3 location matches enterprise+subgroup, etc.
    Currently returns empty (always passes).
    """
    # Placeholder — will implement specific checks when reviewer is fully built out
    return []


async def validate_fields(resource_id: str, fields: dict | None = None, **kwargs) -> str:
    """Run 4-stage validation pipeline on a resource's fields.

    If `fields` is provided, validates those specific fields.
    If `fields` is None, validates ALL fields on the resource.

    Returns: {valid: bool, errors: [], warnings: [], normalized: {}}
    """
    session = _get_session()
    resource = session.get_resource(resource_id)

    if not resource:
        return json.dumps({"error": f"Resource '{resource_id}' not found"})

    config = _load_resource_config(resource.resource_type)
    if not config:
        return json.dumps({"error": f"No config for '{resource.resource_type}'"})

    # If fields are provided, validate them as incoming values against current state.
    # If omitted, validate current state as a whole.
    current_fields = resource.collected_fields if fields is not None else {}
    target_fields = fields if fields is not None else dict(resource.collected_fields)
    validation = validate_collect_fields(resource.resource_type, current_fields, target_fields)

    return json.dumps({
        "valid": validation["valid"],
        "errors": validation["errors"] if validation["errors"] else None,
        "field_errors": validation["field_errors"] if validation["field_errors"] else None,
        "cross_field_errors": validation["cross_field_errors"] if validation["cross_field_errors"] else None,
        "warnings": validation["warnings"] if validation["warnings"] else None,
        "normalized": validation["normalized"],
        "instruction": (
            "If valid is false, do not call set_fields for invalid values. "
            "Ask the user to correct the listed fields using allowed_values/expected_format."
        ),
    }, default=str)

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

    # Use provided fields or all collected fields
    target_fields = fields if fields is not None else dict(resource.collected_fields)

    all_errors: list[str] = []
    all_warnings: list[str] = []
    normalized: dict[str, Any] = {}

    # Stage 1 + 2: per-field normalization and static validation
    for field_name, value in target_fields.items():
        field_spec = next(
            (f for f in config.get("collect_fields", []) if f["name"] == field_name),
            None,
        )
        if not field_spec:
            # Unknown field — skip silently
            normalized[field_name] = value
            continue

        # Stage 1: Normalize
        norm_value = _stage1_normalize(field_name, value, field_spec)
        normalized[field_name] = norm_value

        # Stage 2: Static validation
        static_errors = _stage2_static(field_name, norm_value, field_spec)
        all_errors.extend(static_errors)

    # Stage 3: Dependent validation (uses normalized values)
    merged = {**resource.collected_fields, **normalized}
    dep_errors = _stage3_dependent(merged, resource.resource_type)
    all_errors.extend(dep_errors)

    # Stage 4: Cross-field validation
    cross_errors = _stage4_cross_field(merged, resource.resource_type)
    all_errors.extend(cross_errors)

    return json.dumps({
        "valid": len(all_errors) == 0,
        "errors": all_errors if all_errors else None,
        "warnings": all_warnings if all_warnings else None,
        "normalized": normalized,
    }, default=str)

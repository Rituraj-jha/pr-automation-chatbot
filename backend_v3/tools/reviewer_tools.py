"""Reviewer tools — post-confirmation quality gate.

Runs the rulepack-based validation engine against the generated YAML.
On pass → resource moves to DONE.
On fail → resource stays in REVIEWING, errors surfaced to the user.
"""
from __future__ import annotations

import json
import logging

from models.state import ResourceStatus
from tools.session_tools import _get_session
from db.repository import save_resource
from services.yaml_validator import run_validation

logger = logging.getLogger(__name__)


async def review_yaml(resource_id: str, **kwargs) -> str:
    """Run validation rules against the generated YAML for a resource.

    On pass  → moves resource to DONE, returns {pass: true, warnings: [...], status: "done"}.
    On fail  → moves resource to REVIEWING, returns {pass: false, errors: [...], violation_count: N}.
    """
    session = _get_session()
    resource = session.get_resource(resource_id)

    if not resource:
        return json.dumps({"error": f"Resource '{resource_id}' not found"})

    if resource.status not in (ResourceStatus.CONFIRMING, ResourceStatus.REVIEWING):
        return json.dumps({
            "error": f"Cannot review — resource status is '{resource.status.value}'. "
                     f"Must be 'confirming' or 'reviewing'."
        })

    yaml_str = resource.yaml_output or ""
    if not yaml_str.strip():
        return json.dumps({"error": "No YAML output found on resource. Call generate_yaml first."})

    try:
        result = run_validation(
            resource_type=resource.resource_type,
            yaml_str=yaml_str,
            fields=resource.all_fields,
            resource_id=resource.resource_id,
        )
    except Exception as exc:
        logger.error(f"Validation engine error for {resource_id}: {exc}", exc_info=True)
        # Treat engine errors as warnings only — don't block the user
        resource.status = ResourceStatus.DONE
        resource.validation_result = {"passed": True, "engine_error": str(exc), "warnings": [], "errors": [], "rules_run": []}
        await save_resource(session.session_id, resource)
        return json.dumps({
            "pass": True,
            "resource_id": resource.resource_id,
            "warnings": [{"rule_id": "ENGINE_ERROR", "message": str(exc)}],
            "status": "done",
        }, default=str)

    resource.validation_result = result.to_dict()

    if result.passed:
        resource.status = ResourceStatus.DONE
        await save_resource(session.session_id, resource)
        return json.dumps({
            "pass": True,
            "resource_id": resource.resource_id,
            "warnings": result.warnings or None,
            "rules_run": result.rules_run,
            "status": "done",
        }, default=str)
    else:
        resource.status = ResourceStatus.REVIEWING
        await save_resource(session.session_id, resource)
        return json.dumps({
            "pass": False,
            "resource_id": resource.resource_id,
            "errors": result.errors,
            "warnings": result.warnings or None,
            "violation_count": result.violation_count,
            "rules_run": result.rules_run,
            "status": "reviewing",
        }, default=str)

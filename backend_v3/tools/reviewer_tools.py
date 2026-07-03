"""Reviewer tools — post-confirmation quality gate (MOCK).

TODO: Implement full business-rule validation pipeline using config validations
and review_rules.md error codes. For now, always passes.
"""
from __future__ import annotations

import json

from models.state import ResourceStatus
from tools.session_tools import _get_session
from db.repository import save_resource


async def review_yaml(resource_id: str, **kwargs) -> str:
    """Mock review — always passes and moves resource to DONE.

    TODO: Implement real validation pipeline that checks:
      - naming conventions (regex, starts_with, contains)
      - account type matching
      - required_if conditions
      - cross-field consistency
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

    # MOCK: Always pass — move to DONE
    resource.status = ResourceStatus.DONE
    await save_resource(session.session_id, resource)
    return json.dumps({
        "pass": True,
        "resource_id": resource.resource_id,
        "warnings": None,
        "status": "done",
    }, default=str)

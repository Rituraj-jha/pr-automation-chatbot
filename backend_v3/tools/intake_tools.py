"""Pre-validation tools (MOCK).

Contains:
  - check_intake_id: validates intake ID against approved list (Power BI mock)
  - validate_approval_image: validates data owner approval screenshot (always passes)

TODO: Replace with real API calls.
"""
from __future__ import annotations

import json

# MOCK: Hardcoded list of "approved" intake IDs (simulating Power BI lookup)
APPROVED_INTAKE_IDS = [
    "M0000451",
    "M0000485",
    "M0000500",
    "M0000612",
    "M0000777",
    "M0000890",
    "M0001001",
    "M0001234",
    "I0000100",
    "I0000200",
]


async def check_intake_id(intake_id: str, **kwargs) -> str:
    """Check if the given intake ID exists in the approved list.

    Returns:
      - {valid: true, intake_id: "...", message: "..."} if found
      - {valid: false, intake_id: "...", message: "..."} if not found
    """
    intake_id = intake_id.strip().upper()

    if intake_id in APPROVED_INTAKE_IDS:
        return json.dumps({
            "valid": True,
            "intake_id": intake_id,
            "message": f"Intake ID '{intake_id}' is approved and exists in the system.",
        })
    else:
        return json.dumps({
            "valid": False,
            "intake_id": intake_id,
            "message": f"Intake ID '{intake_id}' was not found in the approved intake list. "
                       f"Please verify the ID is correct or check with your team.",
        })


async def validate_approval_image(resource_types: list[str], **kwargs) -> str:
    """Validate data owner approval screenshot (MOCK — always passes).

    In production, this would use LLM vision to verify the screenshot shows
    an approved intake in the data governance system.

    Args:
        resource_types: List of resource types that need approval (e.g. ["glue_db"])

    Returns:
        {valid: true, approved_for: [...], message: "..."}
    """
    # MOCK: Always passes. Persist result so create_resources can proceed on retry.
    try:
        from tools.session_tools import _get_session, _approval_key
        from db.repository import save_session_field

        session = _get_session()
        for resource_type in resource_types:
            await save_session_field(
                session.session_id,
                _approval_key(resource_type, "data_owner_approval"),
                "true",
            )
    except RuntimeError:
        # Tool can still be unit-tested without a bound session.
        pass

    return json.dumps({
        "valid": True,
        "approved_for": resource_types,
        "missing_for": [],
        "message": "Data owner approval verified successfully.",
    })

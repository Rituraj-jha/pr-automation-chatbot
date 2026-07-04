"""Pre-validation tools (MOCK).

Contains:
  - check_intake_id: validates intake ID against approved list (Power BI mock)
  - validate_approval_image: validates data owner approval screenshot (always passes)

TODO: Replace with real API calls.
"""
from __future__ import annotations

import json
import re

# Intake status values used by API + UI.
STATUS_VALID = "valid"
STATUS_NON_VALID = "non_valid"
STATUS_APPROVED_AND_READY = "approved_and_ready_for_design"

# MOCK: Intake IDs that exist but are still waiting for approval.
VALID_PENDING_INTAKE_IDS = [
    "M0002001",
    "M0002002",
    "M0002003",
    "I0000300",
]

# MOCK: Intake IDs that are approved and ready to start design/chat.
APPROVED_AND_READY_INTAKE_IDS = [
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
    """Check intake ID status for pre-chat and field validation.

    Returns:
      - status: approved_and_ready_for_design -> user can proceed to chat/design
      - status: valid -> intake exists but is waiting for approval
      - status: non_valid -> invalid format or unknown ID
    """
    intake_id = intake_id.strip().upper()

    if not re.match(r"^[MI]\d+$", intake_id):
        return json.dumps({
            "valid": False,
            "can_start_chat": False,
            "status": STATUS_NON_VALID,
            "intake_id": intake_id,
            "message": f"Intake ID '{intake_id}' is not valid. Use format like M0000485 or I0000200.",
        })

    if intake_id in APPROVED_AND_READY_INTAKE_IDS:
        return json.dumps({
            "valid": True,
            "can_start_chat": True,
            "status": STATUS_APPROVED_AND_READY,
            "intake_id": intake_id,
            "message": f"Intake ID '{intake_id}' is approved and ready for design. You can start chatting now.",
        })

    if intake_id in VALID_PENDING_INTAKE_IDS:
        return json.dumps({
            "valid": True,
            "can_start_chat": False,
            "status": STATUS_VALID,
            "intake_id": intake_id,
            "message": (
                f"Intake ID '{intake_id}' is valid, but approval is still pending. "
                "Come back after some time. It's waiting for approval."
            ),
        })

    return json.dumps({
        "valid": False,
        "can_start_chat": False,
        "status": STATUS_NON_VALID,
        "intake_id": intake_id,
        "message": (
            f"Intake ID '{intake_id}' was not found in the intake system. "
            "Please verify the ID is correct or check with your team."
        ),
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

"""Pre-validation tools (MOCK).

Contains:
  - check_intake_id: validates intake ID against approved list (Power BI mock)
  - validate_approval_image: validates data owner approval screenshot (always passes)

TODO: Replace with real API calls.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
_APPROVAL_UPLOAD_DIR = Path(__file__).resolve().parent.parent / "uploads" / "data_owner_approval"

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


def _load_data_owner_approval_config() -> dict:
    """Load the central data owner approval pre-validation config."""
    path = _CONFIG_DIR / "pre_validations.yaml"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("data_owner_approval", {}) or {}


def data_owner_approval_requirements() -> dict:
    """Return UI/agent-readable data owner approval requirements from config."""
    config = _load_data_owner_approval_config()
    resources = [str(r).strip().lower() for r in config.get("resources", []) if str(r).strip()]
    return {
        "enabled": bool(config.get("enabled", True)),
        "mock": bool(config.get("mock", True)),
        "validator_tool": config.get("validator_tool", "validate_data_owner_approval_document"),
        "resources": resources,
        "accepted_file_types": config.get("accepted_file_types", []),
        "description": config.get("description", "Upload data owner approval evidence."),
    }


def _load_uploaded_approval_file(file_id: str | None) -> dict | None:
    """Load uploaded approval file metadata by file_id."""
    if not file_id:
        return None
    safe_file_id = str(file_id).strip()
    if not re.match(r"^[a-fA-F0-9]{32}$", safe_file_id):
        return None
    metadata_path = _APPROVAL_UPLOAD_DIR / f"{safe_file_id}.json"
    if not metadata_path.exists():
        return None
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    stored_file = metadata.get("stored_file")
    metadata["file_exists"] = bool(stored_file and (_APPROVAL_UPLOAD_DIR / stored_file).exists())
    return metadata


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


async def validate_data_owner_approval_document(
    resource_types: list[str],
    file_id: str | None = None,
    file_name: str | None = None,
    file_type: str | None = None,
    file_content_base64: str | None = None,
    file_url: str | None = None,
    intake_id: str | None = None,
    **kwargs,
) -> str:
    """Validate data owner approval document evidence (MOCK — always passes).

    This is the frontend-friendly approval validator. It accepts uploaded-file
    metadata/content pointers now, and can later be replaced with real PDF page
    extraction + image analysis without changing the conversation flow.
    """
    requirements = data_owner_approval_requirements()
    uploaded_file = _load_uploaded_approval_file(file_id)

    if file_id and not uploaded_file:
        return json.dumps({
            "valid": False,
            "mock": True,
            "approved_for": [],
            "missing_for": resource_types,
            "file_id": file_id,
            "message": "I could not find the uploaded approval document. Please upload it again.",
        })

    if uploaded_file and not uploaded_file.get("file_exists"):
        return json.dumps({
            "valid": False,
            "mock": True,
            "approved_for": [],
            "missing_for": resource_types,
            "file_id": file_id,
            "message": "The uploaded approval document is not available. Please upload it again.",
        })

    if uploaded_file:
        file_name = file_name or uploaded_file.get("file_name")
        file_type = file_type or uploaded_file.get("file_type")
        intake_id = intake_id or uploaded_file.get("intake_id")

    configured_resources = set(requirements.get("resources", []))
    requested_resources = [str(r).strip().lower() for r in resource_types if str(r).strip()]
    approved_for = [r for r in requested_resources if r in configured_resources]
    skipped = [r for r in requested_resources if r not in configured_resources]

    # If the caller passes only non-gated resources, treat it as a no-op success.
    if not approved_for:
        return json.dumps({
            "valid": True,
            "mock": True,
            "approved_for": [],
            "skipped": skipped,
            "missing_for": [],
            "message": "No requested resources require data owner approval.",
        })

    # MOCK: Always passes. Persist result so create_resources can proceed on retry.
    try:
        from tools.session_tools import _get_session, _approval_key, _pending_approval_key
        from db.repository import load_session_fields, save_session_field

        session = _get_session()
        for resource_type in approved_for:
            await save_session_field(
                session.session_id,
                _approval_key(resource_type, "data_owner_approval"),
                "true",
            )
        session_fields = await load_session_fields(session.session_id)
        pending_raw = session_fields.get(_pending_approval_key("data_owner_approval"))
        if pending_raw:
            try:
                pending = json.loads(pending_raw)
                remaining = [
                    r for r in pending.get("resource_types", [])
                    if str(r).strip().lower() not in approved_for
                ]
                if remaining:
                    pending["resource_types"] = remaining
                    pending["blocked"] = [
                        item for item in pending.get("blocked", [])
                        if item.get("resource_type") in remaining
                    ]
                    await save_session_field(session.session_id, _pending_approval_key("data_owner_approval"), json.dumps(pending))
                else:
                    await save_session_field(session.session_id, _pending_approval_key("data_owner_approval"), "")
            except (json.JSONDecodeError, TypeError):
                await save_session_field(session.session_id, _pending_approval_key("data_owner_approval"), "")
    except RuntimeError:
        # Tool can still be called from tests or without a bound chat session.
        pass

    return json.dumps({
        "valid": True,
        "mock": True,
        "approved_for": approved_for,
        "skipped": skipped,
        "missing_for": [],
        "intake_id": intake_id,
        "received_file": {
            "file_id": file_id,
            "file_name": file_name,
            "file_type": file_type,
            "has_inline_content": bool(file_content_base64),
            "file_url": file_url,
            "uploaded_file_found": bool(uploaded_file),
        },
        "accepted_file_types": requirements.get("accepted_file_types", []),
        "message": "Data owner approval verified successfully. PDF/image analysis is mocked for now.",
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
    return await validate_data_owner_approval_document(resource_types=resource_types, **kwargs)

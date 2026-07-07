"""Pre-validation tools.

Contains:
  - check_intake_id: validates intake ID against approved list (Power BI mock)
  - validate_data_owner_approval_document: validates approval evidence (enhanced + mock)
  - validate_approval_image: legacy alias for approval validation

Enhanced reviewer (when enabled):
  - Uses OpenAI vision to extract approval evidence from images/PDFs
  - Validates approver, date, source system, business purpose against KB
  - Returns structured review summary with confidence scores and itemized checks
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
    resource_ids: list[str] | None = None,
    file_id: str | None = None,
    file_name: str | None = None,
    file_type: str | None = None,
    file_content_base64: str | None = None,
    file_url: str | None = None,
    intake_id: str | None = None,
    **kwargs,
) -> str:
    """Validate data owner approval document evidence.

    This validates approval evidence using OpenAI vision extraction + knowledge base
    matching when enhanced_reviewer is enabled. Falls back to mock behavior otherwise.
    
    The tool accepts uploaded-file metadata from the frontend and returns a structured
    validation result with itemized checks, confidence scores, and final decision.
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
        resource_ids = resource_ids or uploaded_file.get("resource_ids") or None

    # ─── Enhanced Reviewer Path ──────────────────────────────────────────────
    # Check if professional reviewer is enabled in settings
    settings_path = _CONFIG_DIR / "settings.yaml"
    enhanced_enabled = False
    if settings_path.exists():
        try:
            settings_data = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
            approval_settings = settings_data.get("approval_reviewer", {})
            enhanced_enabled = approval_settings.get("enhanced_reviewer_enabled", False)
        except Exception:
            pass

    if enhanced_enabled and uploaded_file and uploaded_file.get("file_exists"):
        try:
            from services.approval_reviewer import review_approval_document
            from db.repository import load_session_fields

            session = None
            session_fields = {}
            try:
                from tools.session_tools import _get_session
                session = _get_session()
                session_fields = await load_session_fields(session.session_id)
            except RuntimeError:
                pass  # Tool called outside of chat session (tests)

            file_path = _APPROVAL_UPLOAD_DIR / uploaded_file["stored_file"]
            review_summary = await review_approval_document(
                file_path=file_path,
                file_id=file_id,
                file_name=file_name,
                file_type=file_type,
                resource_ids=resource_ids,
                intake_id=intake_id,
                session_fields=session_fields,
            )

            # Convert ReviewSummary to tool response format
            if review_summary.final_decision == "approved":
                requested_resources = [str(r).strip().lower() for r in resource_types if str(r).strip()]
                approved_for = sorted(set(requested_resources))
                ev = review_summary.extracted_evidence
                check_lines = [f"- {c.check_name}: {c.status}" for c in review_summary.checks]
                summary_text = "\n".join([
                    "Approval review summary:",
                    f"- approver: {ev.approver or 'not found'}",
                    f"- approval_date: {ev.approval_date or 'not found'}",
                    f"- source_system: {ev.source_system or 'not found'}",
                    f"- business_purpose: {(ev.business_purpose[:120] + '...') if ev.business_purpose and len(ev.business_purpose) > 120 else (ev.business_purpose or 'not found')}",
                    f"- extraction_method: {ev.extraction_method}",
                    f"- overall_confidence: {review_summary.overall_confidence:.2%}",
                    "Check results:",
                    *check_lines,
                ])

                # Mark approval satisfied for matched resources
                try:
                    from tools.session_tools import _approval_key, _pending_approval_key, _all_required_present, _load_resource_config
                    from tools.derive_tools import derive_fields
                    from db.repository import save_session_field

                    if session:
                        approved_resource_ids = {r["resource_id"] for r in review_summary.approved_resources}
                        auto_derived = []

                        for approved in review_summary.approved_resources:
                            resource_id = approved["resource_id"]
                            await save_session_field(
                                session.session_id,
                                _approval_key(str(resource_id), "data_owner_approval"),
                                "true",
                            )
                            
                            # Auto-derive if ready
                            resource = session.get_resource(str(resource_id)) if resource_id else None
                            if resource:
                                config = _load_resource_config(resource.resource_type)
                                if (resource.status.value == "collecting" and config 
                                    and _all_required_present(resource, config)):
                                    derive_result = await derive_fields(resource_id=resource.resource_id)
                                    try:
                                        auto_derived.append(json.loads(derive_result))
                                    except json.JSONDecodeError:
                                        auto_derived.append({"resource_id": resource.resource_id, "result": derive_result})

                        # Update pending approval state
                        pending_raw = session_fields.get(_pending_approval_key("data_owner_approval"))
                        if pending_raw:
                            try:
                                pending = json.loads(pending_raw)
                                remaining_blocked = [
                                    item for item in pending.get("blocked", [])
                                    if str(item.get("resource_id")) not in approved_resource_ids
                                ]
                                if remaining_blocked:
                                    pending["blocked"] = remaining_blocked
                                    pending["resource_types"] = sorted({
                                        str(item.get("resource_type", "")).strip().lower()
                                        for item in remaining_blocked if item.get("resource_type")
                                    })
                                    pending["resource_ids"] = [item.get("resource_id") for item in remaining_blocked if item.get("resource_id")]
                                    pending["pending_targets"] = [
                                        {"resource_id": item.get("resource_id"), "resource_type": item.get("resource_type"), "intake_id": item.get("intake_id")}
                                        for item in remaining_blocked
                                    ]
                                    await save_session_field(session.session_id, _pending_approval_key("data_owner_approval"), json.dumps(pending))
                                else:
                                    await save_session_field(session.session_id, _pending_approval_key("data_owner_approval"), "")
                            except (json.JSONDecodeError, TypeError):
                                pass

                        return json.dumps({
                            "valid": True,
                            "mock": False,
                            "enhanced_reviewer": True,
                            "approved_for": approved_for,
                            "approved_resources": review_summary.approved_resources,
                            "auto_derived": auto_derived,
                            "review_summary": review_summary.to_dict(),
                            "message": f"Approval validated successfully with {len(review_summary.checks)} checks.\n\n{summary_text}",
                        })
                except RuntimeError:
                    pass  # Session not bound

                # Return success even without session
                return json.dumps({
                    "valid": True,
                    "mock": False,
                    "enhanced_reviewer": True,
                    "approved_for": approved_for,
                    "approved_resources": review_summary.approved_resources,
                    "review_summary": review_summary.to_dict(),
                    "message": f"Approval validated successfully. {len(review_summary.checks)} checks passed.\n\n{summary_text}",
                })

            else:
                # Rejected or needs manual review
                extracted_summary = []
                ev = review_summary.extracted_evidence
                if ev.approver:
                    extracted_summary.append(f"✓ Approver: {ev.approver} (confidence: {ev.approver_confidence:.0%})")
                else:
                    extracted_summary.append("✗ Approver: not found")
                
                if ev.approval_date:
                    extracted_summary.append(f"✓ Date: {ev.approval_date} (confidence: {ev.approval_date_confidence:.0%})")
                else:
                    extracted_summary.append("✗ Date: not found")
                
                if ev.source_system:
                    extracted_summary.append(f"✓ Source: {ev.source_system} (confidence: {ev.source_system_confidence:.0%})")
                else:
                    extracted_summary.append("✗ Source: not found")
                
                if ev.business_purpose:
                    purpose_short = ev.business_purpose[:80] + "..." if len(ev.business_purpose) > 80 else ev.business_purpose
                    extracted_summary.append(f"✓ Purpose: {purpose_short} (confidence: {ev.business_purpose_confidence:.0%})")
                else:
                    extracted_summary.append("✗ Purpose: not found")

                extraction_note = f"\n\nExtracted from document ({ev.extraction_method}):\n" + "\n".join(extracted_summary)
                
                if ev.raw_text:
                    extraction_note += f"\n\nRaw text sample (first 300 chars):\n{ev.raw_text[:300]}..."

                return json.dumps({
                    "valid": False,
                    "mock": False,
                    "enhanced_reviewer": True,
                    "approved_for": [],
                    "final_decision": review_summary.final_decision,
                    "review_summary": review_summary.to_dict(),
                    "errors": review_summary.errors,
                    "warnings": review_summary.warnings,
                    "message": f"Approval validation {review_summary.final_decision}: {'; '.join(review_summary.errors or review_summary.warnings or ['See review summary'])}{extraction_note}",
                })

        except Exception as e:
            # Fallback to mock on any error
            import traceback
            error_detail = f"Enhanced reviewer error: {str(e)}\n{traceback.format_exc()}"
            return json.dumps({
                "valid": False,
                "mock": False,
                "enhanced_reviewer_failed": True,
                "approved_for": [],
                "error": error_detail,
                "message": f"Enhanced reviewer encountered an error. Check logs for details.",
            })

    # ─── Mock/Legacy Path (default) ──────────────────────────────────────────
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

    approved_resources = []
    remaining_targets = []
    auto_derived = []

    # MOCK: Always passes. Persist result so field collection can proceed for
    # the exact approved resource_id(s). Do not approve every glue_db just
    # because a single glue_db approval image was uploaded.
    try:
        from tools.session_tools import (
            _all_required_present,
            _get_session,
            _approval_key,
            _load_resource_config,
            _pending_approval_key,
        )
        from tools.derive_tools import derive_fields
        from db.repository import load_session_fields, save_session_field

        session = _get_session()
        session_fields = await load_session_fields(session.session_id)
        pending_raw = session_fields.get(_pending_approval_key("data_owner_approval"))
        if pending_raw:
            try:
                pending = json.loads(pending_raw)
                pending_blocked = [
                    item for item in pending.get("blocked", [])
                    if isinstance(item, dict)
                    and str(item.get("resource_type", "")).strip().lower() in approved_for
                ]
                requested_ids = {str(r).strip() for r in (resource_ids or []) if str(r).strip()}
                requested_intake = str(intake_id or "").strip().upper()

                if requested_ids:
                    matched = [item for item in pending_blocked if str(item.get("resource_id")) in requested_ids]
                elif requested_intake:
                    matched = [
                        item for item in pending_blocked
                        if str(item.get("intake_id") or "").strip().upper() == requested_intake
                    ]
                elif len(pending_blocked) == 1:
                    matched = pending_blocked
                else:
                    pending_targets = [
                        {
                            "resource_id": item.get("resource_id"),
                            "resource_type": item.get("resource_type"),
                            "intake_id": item.get("intake_id"),
                        }
                        for item in pending_blocked
                    ]
                    return json.dumps({
                        "valid": False,
                        "mock": True,
                        "requires_target": True,
                        "approved_for": [],
                        "pending_targets": pending_targets,
                        "message": "Multiple pending resources require approval. Choose which resource_id(s) this uploaded document applies to, or select all matching resources if the same document covers them.",
                    })

                if not matched:
                    pending_targets = [
                        {
                            "resource_id": item.get("resource_id"),
                            "resource_type": item.get("resource_type"),
                            "intake_id": item.get("intake_id"),
                        }
                        for item in pending_blocked
                    ]
                    return json.dumps({
                        "valid": False,
                        "mock": True,
                        "approved_for": [],
                        "requested_resource_ids": sorted(requested_ids),
                        "requested_intake_id": requested_intake or None,
                        "pending_targets": pending_targets,
                        "message": "The uploaded approval did not match any pending resource target. Select the intended resource_id/intake_id and upload/send again.",
                    })

                approved_resource_ids = {str(item.get("resource_id")) for item in matched if item.get("resource_id")}
                for item in matched:
                    resource_id = item.get("resource_id")
                    if not resource_id:
                        continue
                    await save_session_field(
                        session.session_id,
                        _approval_key(str(resource_id), "data_owner_approval"),
                        "true",
                    )
                    approved_resources.append({
                        "resource_id": resource_id,
                        "resource_type": item.get("resource_type"),
                        "intake_id": item.get("intake_id"),
                    })

                remaining_blocked = [
                    item for item in pending.get("blocked", [])
                    if str(item.get("resource_id")) not in approved_resource_ids
                ]
                remaining_targets = [
                    {
                        "resource_id": item.get("resource_id"),
                        "resource_type": item.get("resource_type"),
                        "intake_id": item.get("intake_id"),
                    }
                    for item in remaining_blocked
                ]
                if remaining_blocked:
                    pending["blocked"] = remaining_blocked
                    pending["resource_types"] = sorted({
                        str(item.get("resource_type", "")).strip().lower()
                        for item in remaining_blocked
                        if item.get("resource_type")
                    })
                    pending["resource_ids"] = [item.get("resource_id") for item in remaining_blocked if item.get("resource_id")]
                    pending["pending_targets"] = remaining_targets
                    await save_session_field(session.session_id, _pending_approval_key("data_owner_approval"), json.dumps(pending))
                else:
                    await save_session_field(session.session_id, _pending_approval_key("data_owner_approval"), "")

                for approved in approved_resources:
                    resource_id = approved.get("resource_id")
                    resource = session.get_resource(str(resource_id)) if resource_id else None
                    if not resource:
                        continue
                    config = _load_resource_config(resource.resource_type)
                    if resource.status.value == "collecting" and config and _all_required_present(resource, config):
                        derive_result = await derive_fields(resource_id=resource.resource_id)
                        try:
                            auto_derived.append(json.loads(derive_result))
                        except json.JSONDecodeError:
                            auto_derived.append({"resource_id": resource.resource_id, "result": derive_result})
            except (json.JSONDecodeError, TypeError):
                await save_session_field(session.session_id, _pending_approval_key("data_owner_approval"), "")
        else:
            # Compatibility fallback for tests without pending resource state.
            for resource_type in approved_for:
                await save_session_field(
                    session.session_id,
                    _approval_key(resource_type, "data_owner_approval"),
                    "true",
                )
    except RuntimeError:
        # Tool can still be called from tests or without a bound chat session.
        pass

    return json.dumps({
        "valid": True,
        "mock": True,
        "approved_for": approved_for,
        "approved_resources": approved_resources,
        "remaining_targets": remaining_targets,
        "auto_derived": auto_derived,
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

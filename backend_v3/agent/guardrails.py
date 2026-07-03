"""Agent guardrails — code-enforced rules that fire automatically.

These are NOT prompt-dependent. They run as interceptors in the agent loop,
ensuring the system behaves correctly regardless of LLM output.

Guardrails (ordered by when they fire):
  1. Auto-inject state — every turn start
  2. Auto-derive — after set_fields returns collection_complete
  3. Auto-review — after generate_yaml succeeds
  4. Block PR without review — reject create_pr if any resource in REVIEWING
  5. Session field persistence — after successful set_fields
  6. Auto-check intake ID — after set_fields stores an intake_id
"""
from __future__ import annotations

import json
import logging
from typing import Any

from models.state import ResourceStatus

logger = logging.getLogger(__name__)


async def guardrail_auto_inject_state(llm_messages: list[dict]) -> None:
    """Guardrail 1: Inject fresh session state so LLM always has current truth."""
    from tools.registry import TOOL_FUNCTIONS

    state_fn = TOOL_FUNCTIONS["get_session_state"]
    state_json = await state_fn()
    llm_messages.append({
        "role": "system",
        "content": f"[Auto-injected current state]\n{state_json}",
    })


async def guardrail_auto_derive(
    tool_name: str, tool_result: str, tool_call_id: str
) -> str:
    """Guardrail 2: If set_fields returns collection_complete, auto-trigger derive_fields.

    Returns the enriched tool result (with derive results appended), or original.
    """
    if tool_name != "set_fields":
        return tool_result

    try:
        result_data = json.loads(tool_result)
    except json.JSONDecodeError:
        return tool_result

    if not result_data.get("collection_complete"):
        return tool_result

    resource_id = result_data.get("resource_id")
    if not resource_id:
        return tool_result

    from tools.registry import TOOL_FUNCTIONS
    derive_fn = TOOL_FUNCTIONS.get("derive_fields")
    if not derive_fn:
        return tool_result

    logger.info(f"Guardrail: auto-deriving fields for {resource_id}")
    derive_result = await derive_fn(resource_id=resource_id)

    try:
        derive_data = json.loads(derive_result)
        result_data["auto_derived"] = derive_data
    except json.JSONDecodeError:
        result_data["auto_derived"] = derive_result

    return json.dumps(result_data)


async def guardrail_auto_review(
    tool_name: str, tool_result: str, tool_call_id: str
) -> str:
    """Guardrail 3: After generate_yaml succeeds, auto-trigger review_yaml.

    Returns the enriched tool result (with review results appended), or original.
    """
    if tool_name != "generate_yaml":
        return tool_result

    try:
        result_data = json.loads(tool_result)
    except json.JSONDecodeError:
        return tool_result

    # Only trigger review if generate_yaml actually produced output
    resource_id = result_data.get("resource_id")
    if not resource_id or not result_data.get("yaml"):
        return tool_result

    from tools.registry import TOOL_FUNCTIONS
    review_fn = TOOL_FUNCTIONS.get("review_yaml")
    if not review_fn:
        # Reviewer not available — skip (resource stays in CONFIRMING → DONE is handled by generate_yaml)
        return tool_result

    logger.info(f"Guardrail: auto-reviewing {resource_id}")
    review_result = await review_fn(resource_id=resource_id)

    try:
        review_data = json.loads(review_result)
        result_data["auto_review"] = review_data
    except json.JSONDecodeError:
        result_data["auto_review"] = review_result

    return json.dumps(result_data)


async def guardrail_block_pr_without_review(
    tool_name: str, tool_args: dict
) -> str | None:
    """Guardrail 4: Block create_pr if any resource is still in REVIEWING state.

    Returns an error string if blocked, or None if allowed to proceed.
    """
    if tool_name != "create_pr":
        return None

    from tools.session_tools import _get_session
    session = _get_session()

    reviewing = [
        r.resource_id for r in session.resources
        if r.status == ResourceStatus.REVIEWING
    ]

    if reviewing:
        return json.dumps({
            "error": f"Cannot create PR — these resources are still in review: {reviewing}. "
                     "Fix review errors first, then try again.",
            "blocked_resources": reviewing,
        })

    return None


async def guardrail_session_field_persistence(
    tool_name: str, tool_result: str
) -> None:
    """Guardrail 5: After successful set_fields, persist values to session_fields table.

    This enables cross-resource field reuse within the same session.
    """
    if tool_name != "set_fields":
        return

    try:
        result_data = json.loads(tool_result)
    except json.JSONDecodeError:
        return

    # Only persist if fields were actually set (no errors)
    stored_fields = result_data.get("set", {})
    if not stored_fields:
        return

    from tools.session_tools import _get_session
    from db.repository import save_session_field

    session = _get_session()
    for field_name, field_value in stored_fields.items():
        await save_session_field(session.session_id, field_name, str(field_value))


async def guardrail_auto_check_intake_id(
    tool_name: str, tool_result: str
) -> str:
    """Guardrail 6: After set_fields stores an intake_id, auto-call check_intake_id.

    Appends the intake validation result to the tool result so the LLM sees it.
    If intake_id is invalid, the LLM will inform the user.
    """
    if tool_name != "set_fields":
        return tool_result

    try:
        result_data = json.loads(tool_result)
    except json.JSONDecodeError:
        return tool_result

    stored_fields = result_data.get("set", {})
    if "intake_id" not in stored_fields:
        return tool_result

    intake_id = stored_fields["intake_id"]

    from tools.intake_tools import check_intake_id
    logger.info(f"Guardrail: auto-checking intake ID '{intake_id}'")
    check_result = await check_intake_id(intake_id=intake_id)

    try:
        check_data = json.loads(check_result)
        result_data["intake_id_check"] = check_data
    except json.JSONDecodeError:
        result_data["intake_id_check"] = check_result

    return json.dumps(result_data)

"""Agent guardrails — code-enforced rules that fire automatically.

These are NOT prompt-dependent. They run as interceptors in the agent loop,
ensuring the system behaves correctly regardless of LLM output.

Guardrails (ordered by when they fire):
    1. Route lock — each session is either create or update route until reset
    2. Auto-inject state — every turn start
    3. Auto-derive — after set_fields returns collection_complete
    4. Auto-review — after generate_yaml succeeds
    5. Block PR without review — reject create_pr if any resource in REVIEWING
    6. Session field persistence — after successful set_fields
    7. Auto-check intake ID — after set_fields stores an intake_id
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import yaml

from models.state import ResourceStatus

logger = logging.getLogger(__name__)

ACTIVE_ROUTE_KEY = "__active_route"
_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
_SUPPORTED_RESOURCE_TERMS: set[str] | None = None

CREATE_ROUTE_TOOLS = {
    "create_resources",
    "drop_resource",
    "clone_resource",
    "set_fields",
    "edit_derived_field",
    "derive_fields",
    "check_resource_exists",
    "generate_yaml",
    "review_yaml",
    "prepare_pr_intake",
    "set_pr_intake_answers",
    "create_pr",
    "validate_fields",
}

UPDATE_ROUTE_TOOLS = {
    "check_update_capability",
    "fetch_existing_resource_file",
    "stage_append_only_update",
    "stage_full_updated_yaml",
    "validate_append_only_change",
    "preview_update_diff",
    "create_update_pr",
    "review_yaml",
}

NEUTRAL_TOOLS = {
    "get_session_state",
    "get_resource_info",
    "get_common_fields",
    "check_intake_id",
    "validate_data_owner_approval_document",
    "validate_approval_image",
    "update_user_profile",
}


def _infer_route_intent(message: str) -> str | None:
    """Infer create/update intent from a user message."""
    raw_text = message.lower()
    text = f" {raw_text} "
    update_patterns = [
        r"\bupdate\b", r"\bmodify\b", r"\bedit\b", r"\bappend\b", r"\bpatch\b", r"\brevise\b",
        r"\bexisting\s+(resource|yaml|file|bucket|database)\b",
    ]
    create_terms = [
        " create ", " provision ", " make ", " add new ", " new resource ",
        " setup ", " set up ", " generate ", " want ", " need ",
    ]
    if any(re.search(pattern, raw_text) for pattern in update_patterns):
        return "update"
    if any(term in text for term in create_terms):
        return "create"
    if _mentions_supported_resource(raw_text):
        # Bare resource requests like "s3" or "want s3" are create requests unless
        # the user explicitly says update/modify/append existing YAML.
        return "create"
    return None


def _supported_resource_terms() -> set[str]:
    """Load supported resource aliases for route intent inference."""
    global _SUPPORTED_RESOURCE_TERMS
    if _SUPPORTED_RESOURCE_TERMS is not None:
        return _SUPPORTED_RESOURCE_TERMS

    terms: set[str] = set()
    settings_path = _CONFIG_DIR / "settings.yaml"
    if settings_path.exists():
        data = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
        for item in data.get("supported_resources", []) or []:
            if not isinstance(item, dict):
                terms.add(str(item))
                continue
            for value in [item.get("type"), item.get("display"), *(item.get("aliases", []) or [])]:
                if value:
                    terms.add(str(value))
    _SUPPORTED_RESOURCE_TERMS = {re.sub(r"[^a-z0-9]+", " ", term.lower()).strip() for term in terms if term}
    return _SUPPORTED_RESOURCE_TERMS


def _mentions_supported_resource(message: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", " ", message.lower()).strip()
    if not normalized:
        return False
    for term in _supported_resource_terms():
        if term and re.search(rf"\b{re.escape(term)}s?\b", normalized):
            return True
    return False


def _is_route_reset_message(message: str) -> bool:
    text = message.lower().strip()
    return text in {"cancel", "start over", "reset", "new request", "clear route"} or "start over" in text


async def guardrail_route_user_message(session, user_message: str) -> str | None:
    """Lock a session to create or update route and reject cross-route user requests."""
    from db.repository import load_session_fields, save_session_field

    if _is_route_reset_message(user_message):
        await save_session_field(session.session_id, ACTIVE_ROUTE_KEY, "")
        return "I cleared the active route. Tell me if you want to create or update a resource."

    fields = await load_session_fields(session.session_id)
    current_route = fields.get(ACTIVE_ROUTE_KEY, "").strip()
    requested_route = _infer_route_intent(user_message)

    if current_route in {"create", "update"}:
        if requested_route and requested_route != current_route:
            other = "update" if current_route == "create" else "create"
            return (
                f"This chat is currently in {current_route}-resource mode. "
                f"To {other} a resource, please start a new request or cancel this flow."
            )
        return None

    if requested_route in {"create", "update"}:
        await save_session_field(session.session_id, ACTIVE_ROUTE_KEY, requested_route)

    return None


async def guardrail_enforce_route(tool_name: str, tool_args: dict) -> str | None:
    """Restrict tool usage to the active session route."""
    if tool_name in NEUTRAL_TOOLS:
        return None

    from tools.session_tools import _get_session
    from db.repository import load_session_fields, save_session_field

    session = _get_session()
    fields = await load_session_fields(session.session_id)
    current_route = fields.get(ACTIVE_ROUTE_KEY, "").strip()

    if tool_name in CREATE_ROUTE_TOOLS and tool_name in UPDATE_ROUTE_TOOLS:
        return None

    tool_route = None
    if tool_name in CREATE_ROUTE_TOOLS:
        tool_route = "create"
    elif tool_name in UPDATE_ROUTE_TOOLS:
        tool_route = "update"

    if not tool_route:
        return None

    if not current_route:
        await save_session_field(session.session_id, ACTIVE_ROUTE_KEY, tool_route)
        current_route = tool_route

    if current_route != tool_route:
        return json.dumps({
            "error": f"Tool '{tool_name}' is not allowed in {current_route}-resource mode.",
            "active_route": current_route,
            "tool_route": tool_route,
            "message": f"This session is locked to {current_route}. Start a new request or cancel this flow to switch routes.",
        })

    return None


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

    # Stop signal: tell the LLM to respond to user and NOT continue with PR
    result_data["instruction"] = (
        "Resource is now DONE and review passed. "
        "STOP here — respond to the user saying the resource is ready and they can say 'create PR' when ready. "
        "Do NOT call create_pr or any other tool in this turn."
    )

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

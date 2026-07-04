"""
MiNi — FastAPI server
Connects the agent to the frontend.
"""
from __future__ import annotations

import base64
import sys
import json
import uuid
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import yaml
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Add backend_v3 to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from models.state import Session, ResourceStatus
from db.connection import set_db_path, init_db, close_db
from db.repository import (
    save_session, load_session, list_sessions, delete_session,
    update_session_title, get_session_messages, save_message,
    save_resource, load_session_fields, save_session_field,
)
from tools.session_tools import bind_session
from agent.loop import run_agent_turn

_CONFIG_DIR = Path(__file__).resolve().parent / "config"
_APPROVAL_UPLOAD_DIR = Path(__file__).resolve().parent / "uploads" / "data_owner_approval"
_PENDING_APPROVAL_KEY = "__pending_pre_validation:data_owner_approval"
_VALIDATED_INTAKE_KEY = "__validated_intake"


# ─── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    db_path = Path(__file__).parent / "mini.db"
    set_db_path(db_path)
    await init_db()
    yield
    await close_db()


app = FastAPI(title="MiNi Agent API", version="3.0.0", lifespan=lifespan)

# CORS for frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _get_user(request: Request) -> str:
    """Extract user from header (stub auth)."""
    return request.headers.get("X-GitHub-User", "default")


def _generate_title(message: str) -> str:
    """Generate a short chat title from the first message."""
    clean = message.strip()[:60]
    if len(message) > 60:
        clean += "..."
    return clean


def _display_resource_type(resource_type: str) -> str:
    """Human-readable resource type label."""
    if resource_type == "glue_db":
        return "Glue DB"
    if resource_type == "s3":
        return "S3"
    return resource_type.replace("_", " ").title()


def _mentions_resource_type(message: str, resource_type: str) -> bool:
    """Check whether a user message mentions a resource type or common alias."""
    text = message.lower()
    if resource_type in text:
        return True
    if resource_type == "glue_db" and any(token in text for token in ("glue db", "gluedb", "glue database")):
        return True
    if resource_type == "s3" and any(token in text for token in ("s3", "bucket", "s3 bucket")):
        return True
    return False


async def _load_pending_approval(session_id: str) -> dict | None:
    """Load unresolved data-owner approval pending state from session fields."""
    session_fields = await load_session_fields(session_id)
    pending_raw = session_fields.get(_PENDING_APPROVAL_KEY)
    if not pending_raw:
        return None
    try:
        pending = json.loads(pending_raw)
    except json.JSONDecodeError:
        return None
    resource_types = [str(r).strip().lower() for r in pending.get("resource_types", []) if str(r).strip()]
    unresolved = [
        r for r in resource_types
        if session_fields.get(f"__pre_validation:data_owner_approval:{r}") != "true"
    ]
    if not unresolved:
        await save_session_field(session_id, _PENDING_APPROVAL_KEY, "")
        return None
    pending["resource_types"] = unresolved
    return pending


async def _handle_pending_approval_skip(session: Session, message: str) -> str | None:
    """Deterministically handle user skipping approval-gated resources."""
    text = message.lower()
    if not any(token in text for token in ("skip", "remove", "cancel", "drop")):
        return None

    pending = await _load_pending_approval(session.session_id)
    if not pending:
        return None

    pending_types = pending.get("resource_types", [])
    skip_types = [rtype for rtype in pending_types if _mentions_resource_type(message, rtype)]
    if not skip_types and any(token in text for token in ("approval", "don't have", "do not have", "no document", "later")):
        skip_types = pending_types
    if not skip_types:
        return None

    skipped_set = set(skip_types)
    for resource in session.resources:
        if resource.resource_type in skipped_set and resource.status != ResourceStatus.DROPPED:
            resource.status = ResourceStatus.DROPPED
            await save_resource(session.session_id, resource)

    remaining = [rtype for rtype in pending_types if rtype not in skipped_set]
    if remaining:
        pending["resource_types"] = remaining
        pending["blocked"] = [item for item in pending.get("blocked", []) if item.get("resource_type") in remaining]
        await save_session_field(session.session_id, _PENDING_APPROVAL_KEY, json.dumps(pending))
    else:
        await save_session_field(session.session_id, _PENDING_APPROVAL_KEY, "")

    labels = ", ".join(_display_resource_type(rtype) for rtype in skip_types)
    active_remaining = [r for r in session.resources if r.status != ResourceStatus.DROPPED]
    if active_remaining:
        return f"Skipped {labels}. I’ll continue with the remaining resource request."
    return f"Skipped {labels}. No remaining resources are active in this request."


async def _load_validated_intake(session_id: str) -> dict | None:
    """Load session-scoped validated intake details, if present."""
    session_fields = await load_session_fields(session_id)
    raw = session_fields.get(_VALIDATED_INTAKE_KEY)
    if raw:
        try:
            data = json.loads(raw)
            if data.get("status") == "approved_and_ready_for_design" and data.get("intake_id"):
                return data
        except json.JSONDecodeError:
            pass

    # Backward-compatible fallback if only the plain intake_id session field exists.
    intake_id = session_fields.get("intake_id")
    if intake_id:
        return {
            "valid": True,
            "can_start_chat": True,
            "status": "approved_and_ready_for_design",
            "intake_id": intake_id,
            "message": f"Intake ID '{intake_id}' is already validated for this session.",
            "restored": True,
        }
    return None


# ─── Auth routes ──────────────────────────────────────────────────────────────

@app.get("/auth/github")
async def auth_github():
    """Redirect user to Cargill GitHub Enterprise OAuth page."""
    from fastapi.responses import RedirectResponse
    from auth import get_auth_url
    return RedirectResponse(url=get_auth_url(), status_code=302)


@app.get("/auth/github/callback")
async def auth_github_callback(code: str | None = None, state: str | None = None):
    """Handle GitHub OAuth callback — exchange code, get username, redirect to frontend."""
    from fastapi.responses import RedirectResponse
    from auth import exchange_code, get_username, FRONTEND_URL
    from db.repository import save_github_token
    import logging

    if not code:
        return RedirectResponse(url=f"{FRONTEND_URL}?auth_error=true", status_code=302)

    try:
        token = await exchange_code(code, state)
        username = await get_username(token)
        # Persist token for PR creation
        await save_github_token(username, token)
    except Exception as e:
        logging.getLogger(__name__).error(f"OAuth callback failed: {e}")
        return RedirectResponse(url=f"{FRONTEND_URL}?auth_error=true", status_code=302)

    return RedirectResponse(
        url=f"{FRONTEND_URL}?auth=success&github_user={username}",
        status_code=302,
    )


@app.get("/auth/me")
async def auth_me(request: Request):
    """Check if user is authenticated (based on X-GitHub-User header from frontend)."""
    user = _get_user(request)
    if not user or user == "default":
        return {"authenticated": False}
    return {"authenticated": True, "github_user": user}


# ─── Chat CRUD ────────────────────────────────────────────────────────────────

@app.get("/api/chats")
async def list_chats(request: Request):
    """List all chats for the current user."""
    user = _get_user(request)
    sessions = await list_sessions(user)
    return {"chats": sessions}


@app.get("/api/resources/supported")
async def get_supported_resources():
    """Return supported resources from config/settings.yaml for UI recommenders."""
    settings_path = _CONFIG_DIR / "settings.yaml"
    if not settings_path.exists():
        return {"resources": []}

    with open(settings_path, "r", encoding="utf-8") as f:
        settings = yaml.safe_load(f) or {}

    resources = []
    for item in settings.get("supported_resources", []):
        if isinstance(item, dict):
            resources.append({
                "type": str(item.get("type", "")).strip(),
                "display": str(item.get("display", "")).strip() or str(item.get("type", "")).strip(),
            })
        else:
            value = str(item).strip()
            resources.append({"type": value, "display": value})

    resources = [r for r in resources if r.get("type")]
    return {"resources": resources}


@app.get("/api/data-owner-approval/requirements")
async def get_data_owner_approval_requirements():
    """Return data owner approval requirements from config/pre_validations.yaml."""
    from tools.intake_tools import data_owner_approval_requirements

    return data_owner_approval_requirements()


@app.post("/api/chats")
async def create_chat(request: Request):
    """Create a new empty chat session."""
    user = _get_user(request)
    session_id = str(uuid.uuid4())
    session = Session(session_id=session_id, user_id=user)
    await save_session(session, title="New Chat")
    return {
        "id": session_id,
        "title": "New Chat",
        "created_at": session.created_at.isoformat(),
        "updated_at": session.created_at.isoformat(),
        "message_count": 0,
    }


@app.get("/api/chats/{chat_id}/messages")
async def get_chat_messages(chat_id: str, request: Request):
    """Get all messages for a chat."""
    messages = await get_session_messages(chat_id)
    return messages


@app.get("/api/chats/{chat_id}/intake")
async def get_chat_intake(chat_id: str, request: Request):
    """Return previously validated intake ID for this chat session, if any."""
    intake = await _load_validated_intake(chat_id)
    if not intake:
        return {"validated": False}
    return {"validated": True, **intake}


@app.delete("/api/chats/{chat_id}")
async def delete_chat(chat_id: str, request: Request):
    """Delete a chat session."""
    await delete_session(chat_id)
    return None


# ─── Main chat endpoint ───────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    session_id: str


class IntakeValidationRequest(BaseModel):
    intake_id: str
    session_id: str | None = None


class DataOwnerApprovalValidationRequest(BaseModel):
    resource_types: list[str]
    session_id: str | None = None
    intake_id: str | None = None
    file_id: str | None = None
    file_name: str | None = None
    file_type: str | None = None
    file_content_base64: str | None = None
    file_url: str | None = None


class DataOwnerApprovalUploadRequest(BaseModel):
    resource_types: list[str]
    session_id: str | None = None
    intake_id: str | None = None
    file_name: str
    file_type: str
    file_content_base64: str


@app.post("/api/intake/validate")
async def validate_intake_id(body: IntakeValidationRequest):
    """Non-LLM Intake ID validation endpoint for UI-based pre-chat gating."""
    intake_id = body.intake_id.strip()
    if not intake_id:
        raise HTTPException(status_code=400, detail="Intake ID cannot be empty")

    from tools.intake_tools import check_intake_id

    raw_result = await check_intake_id(intake_id=intake_id)
    try:
        result = json.loads(raw_result)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Invalid intake validation response")

    if body.session_id and result.get("status") == "approved_and_ready_for_design" and result.get("can_start_chat"):
        await save_session_field(body.session_id, _VALIDATED_INTAKE_KEY, json.dumps(result))
        await save_session_field(body.session_id, "intake_id", str(result.get("intake_id", intake_id)).upper())

    return result


@app.post("/api/data-owner-approval/validate")
async def validate_data_owner_approval(body: DataOwnerApprovalValidationRequest, request: Request):
    """Mock frontend-facing data owner approval validation for PDF/images."""
    if not body.resource_types:
        raise HTTPException(status_code=400, detail="resource_types cannot be empty")

    if body.session_id:
        session = await load_session(body.session_id)
        if session is None:
            user = _get_user(request)
            session = Session(session_id=body.session_id, user_id=user)
            await save_session(session, title="New Chat")
        bind_session(session)

    from tools.intake_tools import validate_data_owner_approval_document

    raw_result = await validate_data_owner_approval_document(
        resource_types=body.resource_types,
        file_id=body.file_id,
        file_name=body.file_name,
        file_type=body.file_type,
        file_content_base64=body.file_content_base64,
        file_url=body.file_url,
        intake_id=body.intake_id,
    )
    try:
        result = json.loads(raw_result)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Invalid approval validation response")

    return result


@app.post("/api/data-owner-approval/upload")
async def upload_data_owner_approval(body: DataOwnerApprovalUploadRequest):
    """Stage a data owner approval file for later agent/tool validation.

    This endpoint intentionally does NOT validate or persist approval. It only
    stores the file and returns a file_id. The agent must call
    validate_data_owner_approval_document(file_id=...) to validate it.
    """
    from tools.intake_tools import data_owner_approval_requirements

    if not body.resource_types:
        raise HTTPException(status_code=400, detail="resource_types cannot be empty")

    requirements = data_owner_approval_requirements()
    accepted_types = requirements.get("accepted_file_types", [])
    if accepted_types and body.file_type not in accepted_types:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{body.file_type}'. Accepted: {', '.join(accepted_types)}",
        )

    try:
        file_bytes = base64.b64decode(body.file_content_base64, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 file content")

    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    _APPROVAL_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    file_id = uuid.uuid4().hex
    suffix = Path(body.file_name).suffix.lower()
    if suffix not in {".pdf", ".png", ".jpg", ".jpeg"}:
        suffix = {
            "application/pdf": ".pdf",
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
        }.get(body.file_type, ".bin")

    stored_path = _APPROVAL_UPLOAD_DIR / f"{file_id}{suffix}"
    metadata_path = _APPROVAL_UPLOAD_DIR / f"{file_id}.json"
    stored_path.write_bytes(file_bytes)
    metadata = {
        "file_id": file_id,
        "file_name": body.file_name,
        "file_type": body.file_type,
        "stored_file": stored_path.name,
        "resource_types": body.resource_types,
        "session_id": body.session_id,
        "intake_id": body.intake_id,
        "uploaded_at": datetime.utcnow().isoformat(),
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    return {
        "uploaded": True,
        "file_id": file_id,
        "file_name": body.file_name,
        "file_type": body.file_type,
        "resource_types": body.resource_types,
        "intake_id": body.intake_id,
        "message": "Approval document uploaded. The agent will validate it next.",
    }


@app.post("/api/chat")
async def chat(body: ChatRequest, request: Request):
    """Process a user message through the agent and return a structured response."""
    user = _get_user(request)
    session_id = body.session_id
    message = body.message.strip()

    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    # Load or create session
    session = await load_session(session_id)
    if session is None:
        session = Session(session_id=session_id, user_id=user)
        await save_session(session, title=_generate_title(message))

    # Bind session for tools
    bind_session(session)

    # Deterministic skip flow for approval-gated resources.
    skip_response = await _handle_pending_approval_skip(session, message)
    if skip_response:
        session.add_message("user", message)
        await save_message(session.session_id, session.messages[-1])
        session.add_message("assistant", skip_response)
        await save_message(session.session_id, session.messages[-1])
        response = skip_response
    else:
        # Run agent
        response = await run_agent_turn(session, message)

    # Update title if this is the first real message
    if len(session.messages) <= 2:
        await update_session_title(session_id, _generate_title(message))

    # Build structured response with post-processing
    structured = await _build_structured_data(session)
    resources_summary = _build_resources_summary(session)

    # Check for generated YAML
    generated_yaml = None
    for r in session.resources:
        if r.status == ResourceStatus.DONE and r.yaml_output:
            generated_yaml = r.yaml_output
            break

    return {
        "message": response,
        "session_id": session_id,
        "chat_title": _generate_title(message),
        "generated_yaml": generated_yaml,
        "structured": structured,
        "resources_summary": resources_summary,
        "updated_at": datetime.utcnow().isoformat(),
    }


# ─── Post-processing: build structured data from session state ────────────────

def _load_resource_config(resource_type: str) -> dict | None:
    path = _CONFIG_DIR / "resources" / f"{resource_type}.yaml"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _build_resources_summary(session: Session) -> list[dict]:
    """Build a compact resources summary for the frontend sidebar/cards."""
    summary = []
    for r in session.resources:
        if r.status == ResourceStatus.DROPPED:
            continue

        # Build a short title
        usage = r.collected_fields.get("usage_type", "")
        enterprise = r.collected_fields.get("enterprise_or_func_name", "")
        subgrp = r.collected_fields.get("enterprise_or_func_subgrp_name", "")
        parts = [r.resource_type.upper()]
        if usage:
            parts.append(usage)
        if enterprise:
            label = enterprise
            if subgrp:
                label += f" {subgrp}"
            parts.append(f"({label})")
        title = " — ".join(parts[:2]) + (f" {parts[2]}" if len(parts) > 2 else "")

        entry: dict[str, Any] = {
            "resource_id": r.resource_id,
            "resource_type": r.resource_type,
            "status": r.status.value,
            "title": title,
            "collected_fields": r.collected_fields,
            "derived_fields": r.derived_fields,
            "user_overrides": r.user_overrides,
            "all_fields": r.all_fields,
        }

        if r.status == ResourceStatus.DONE and r.yaml_output:
            entry["yaml"] = r.yaml_output

        summary.append(entry)
    return summary


async def _build_structured_data(session: Session) -> dict | None:
    """Post-process session state to build structured data for the frontend.
    
    Returns the most relevant structured payload based on current state:
    - yaml_preview: if any resource is in confirming state
    - resource_carousel: if multiple resources exist
    - None: if no special rendering needed
    """
    active = [r for r in session.resources if r.status != ResourceStatus.DROPPED]

    # If an approval-gated resource is pending, do not show field prompts for
    # already-created resources yet. The user must upload approval or skip the
    # gated resource first.
    pending_approval = await _load_pending_approval(session.session_id)
    if pending_approval:
        return {
            "type": "approval_required",
            "resource_types": pending_approval.get("resource_types", []),
            "blocked": pending_approval.get("blocked", []),
            "message": "Data owner approval is required before continuing field collection.",
        }

    # Show YAML preview only when every active resource is confirming.
    confirming = [r for r in active if r.status == ResourceStatus.CONFIRMING]
    if active and len(confirming) == len(active):
        previews = []
        for resource in confirming:
            config = _load_resource_config(resource.resource_type)
            editable_fields = []
            readonly_fields = []

            if config:
                for df in config.get("derive_fields", []):
                    edit_level = df.get("editable", "locked")
                    if edit_level in ("constrained", "free"):
                        editable_fields.append(df["name"])
                    else:
                        readonly_fields.append(df["name"])
                for cf in config.get("collect_fields", []):
                    editable_fields.append(cf["name"])

            previews.append({
                "resource_id": resource.resource_id,
                "resource_type": resource.resource_type,
                "all_fields": resource.all_fields,
                "editable_fields": editable_fields,
                "readonly_fields": readonly_fields,
            })

        return {
            "type": "yaml_preview",
            "resources": previews,
            # Keep backward-compat flat fields for single resource
            "resource_id": previews[0]["resource_id"],
            "resource_type": previews[0]["resource_type"],
            "all_fields": previews[0]["all_fields"],
            "editable_fields": previews[0]["editable_fields"],
            "readonly_fields": previews[0]["readonly_fields"],
        }

    # Check for collecting resources → field_prompts with options.
    # For multiple resources, ask common missing fields first, then specific fields.
    collecting = [r for r in active if r.status == ResourceStatus.COLLECTING]
    if collecting:
        if len(collecting) > 1:
            resource_missing: list[dict[str, Any]] = []
            missing_by_resource: dict[str, dict[str, dict[str, Any]]] = {}
            group_by_resource: dict[str, dict[str, str]] = {}

            for resource in collecting:
                config = _load_resource_config(resource.resource_type)
                if not config:
                    continue
                missing_by_resource[resource.resource_id] = {}
                group_by_resource[resource.resource_id] = {}
                for fs in config.get("collect_fields", []):
                    field_name = fs["name"]
                    group_by_resource[resource.resource_id][field_name] = fs.get("group", "")
                    if field_name in resource.collected_fields:
                        continue
                    field_info: dict[str, Any] = {
                        "field_name": field_name,
                        "label": fs.get("label", field_name),
                        "description": fs.get("description", ""),
                    }
                    if fs.get("options"):
                        field_info["options"] = fs["options"]
                    if fs.get("placeholder"):
                        field_info["placeholder"] = fs["placeholder"]
                    if fs.get("allow_empty"):
                        field_info["allow_empty"] = True
                    missing_by_resource[resource.resource_id][field_name] = field_info

            if missing_by_resource:
                resource_ids = list(missing_by_resource.keys())
                common_names = set(missing_by_resource[resource_ids[0]].keys())
                for rid in resource_ids[1:]:
                    common_names &= set(missing_by_resource[rid].keys())

                common_fields = []
                for field_name in sorted(common_names):
                    groups = {group_by_resource[rid].get(field_name, "") for rid in resource_ids}
                    if len(groups) == 1 and "" not in groups:
                        common_fields.append(missing_by_resource[resource_ids[0]][field_name])

                if common_fields:
                    return {
                        "type": "field_prompts",
                        "mode": "common_fields",
                        "resource_ids": resource_ids,
                        "resource_types": [r.resource_type for r in collecting],
                        "fields": common_fields,
                        "total_resources": len(active),
                    }

                for resource in collecting:
                    fields = list(missing_by_resource.get(resource.resource_id, {}).values())
                    if fields:
                        resource_missing.append({
                            "resource_id": resource.resource_id,
                            "resource_type": resource.resource_type,
                            "fields": fields,
                        })
                if resource_missing:
                    return {
                        "type": "field_prompts",
                        "mode": "resource_specific",
                        "resources": resource_missing,
                        "total_resources": len(active),
                    }

        resource = collecting[0]
        config = _load_resource_config(resource.resource_type)
        if config:
            missing_fields = []
            for fs in config.get("collect_fields", []):
                if fs["name"] not in resource.collected_fields:
                    field_info: dict[str, Any] = {
                        "field_name": fs["name"],
                        "label": fs.get("label", fs["name"]),
                        "description": fs.get("description", ""),
                    }
                    if fs.get("options"):
                        field_info["options"] = fs["options"]
                    if fs.get("placeholder"):
                        field_info["placeholder"] = fs["placeholder"]
                    if fs.get("allow_empty"):
                        field_info["allow_empty"] = True
                    missing_fields.append(field_info)

            if missing_fields:
                return {
                    "type": "field_prompts",
                    "resource_id": resource.resource_id,
                    "resource_type": resource.resource_type,
                    "fields": missing_fields,
                    "total_resources": len(active),
                }

    # Multiple active resources → carousel
    if len(active) > 1:
        return {
            "type": "resource_carousel",
            "count": len(active),
        }

    return None


# ─── Run ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)

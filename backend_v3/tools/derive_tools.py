"""Derive tools — compute derivable fields from collected values + config."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from models.state import ResourceStatus
from services.llm import chat_with_tools
from tools.session_tools import _get_session
from db.repository import save_resource

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
_CONTEXT_DIR = Path(__file__).resolve().parent.parent / "context"

# Cache
_accounts: list[dict] | None = None
_s3_naming_context: str | None = None
_glue_db_naming_context: str | None = None


def _load_accounts() -> list[dict]:
    """Load the accounts config."""
    global _accounts
    if _accounts is None:
        path = _CONFIG_DIR / "accounts.yaml"
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        _accounts = data.get("accounts", [])
    return _accounts


def _load_resource_config(resource_type: str) -> dict:
    path = _CONFIG_DIR / "resources" / f"{resource_type}.yaml"
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_s3_naming_context() -> str:
    """Load the dedicated S3 naming convention reference for LLM derivation."""
    global _s3_naming_context
    if _s3_naming_context is None:
        path = _CONTEXT_DIR / "shared" / "s3_naming_conventions.md"
        if path.exists():
            _s3_naming_context = path.read_text(encoding="utf-8")
        else:
            _s3_naming_context = "S3 naming convention context is unavailable."
    return _s3_naming_context


def _load_glue_db_naming_context() -> str:
    """Load the dedicated Glue DB naming convention reference for LLM derivation."""
    global _glue_db_naming_context
    if _glue_db_naming_context is None:
        path = _CONTEXT_DIR / "shared" / "glue_db_naming_conventions.md"
        if path.exists():
            _glue_db_naming_context = path.read_text(encoding="utf-8")
        else:
            _glue_db_naming_context = "Glue DB naming convention context is unavailable."
    return _glue_db_naming_context


def _extract_json_object(text: str | None) -> dict[str, Any]:
    """Parse a JSON object from an LLM response, tolerating accidental fences."""
    if not text or not text.strip():
        raise ValueError("LLM response was empty")

    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        parsed = json.loads(cleaned[start:end + 1])

    if not isinstance(parsed, dict):
        raise ValueError("LLM response must be a JSON object")
    return parsed


def _s3_llm_payload(collected: dict[str, Any], config: dict) -> dict[str, Any]:
    """Build the compact data payload sent to the S3 derivation LLM."""
    return {
        "collected_fields": collected,
        "accounts": _load_accounts(),
        "configured_usage_suffixes": config.get("derivation", {}).get("bucket_name", {}).get("suffix_map", {}),
        "derive_fields_required": [field.get("name") for field in config.get("derive_fields", [])],
        "minimal_tool_contract": {
            "derived_fields_required": ["bucket_name", "bucket_description", "aws_account_id", "aws_region"],
            "missing_inputs_behavior": "If you cannot confidently derive, return can_derive=false and list missing_inputs. Do not invent governance-sensitive values.",
        },
    }


async def _derive_s3_fields_with_llm(collected: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Use LLM-first S3 naming derivation with only minimal Python shape checks."""
    config = _load_resource_config("s3")
    naming_context = _load_s3_naming_context()
    payload = _s3_llm_payload(collected, config)

    messages = [
        {
            "role": "system",
            "content": (
                "You are the S3 naming derivation engine for Minerva/MiNi. "
                "Use the provided S3 naming convention reference and collected fields. "
                "Return only a JSON object. Do not use markdown. Do not call tools. "
                "Do not invent missing governance-sensitive values. "
                "Do not perform reviewer-style policy validation; choose the best convention and derive candidate fields."
            ),
        },
        {
            "role": "user",
            "content": (
                f"S3 naming convention reference:\n{naming_context}\n\n"
                "Input payload:\n"
                f"{json.dumps(payload, indent=2)}\n\n"
                "Return this exact JSON shape:\n"
                "{\n"
                "  \"can_derive\": true,\n"
                "  \"missing_inputs\": [],\n"
                "  \"derived_fields\": {\n"
                "    \"bucket_name\": \"...\",\n"
                "    \"bucket_description\": \"...\",\n"
                "    \"aws_account_id\": \"...\",\n"
                "    \"aws_region\": \"us-east-1\"\n"
                "  },\n"
                "  \"derivation\": {\n"
                "    \"convention\": \"...\",\n"
                "    \"account_association\": \"Lakehouse|Compute|Unknown\",\n"
                "    \"aws_account_abbreviation\": \"...\",\n"
                "    \"owning_entity\": \"...\",\n"
                "    \"usage_suffix\": \"src|dp|scripts|eng-assets|ops\",\n"
                "    \"confidence\": 0.0,\n"
                "    \"reasoning\": \"short reason\"\n"
                "  }\n"
                "}\n"
                "If any needed value is missing, return can_derive=false, missing_inputs with field names/descriptions, and no derived_fields."
            ),
        },
    ]

    response = await chat_with_tools(messages)
    parsed = _extract_json_object(response.get("content"))

    metadata = {
        "strategy": "llm_first",
        "llm_response": parsed,
    }

    missing_inputs = parsed.get("missing_inputs") or []
    if parsed.get("can_derive") is False or missing_inputs:
        metadata["missing_inputs"] = missing_inputs
        return None, metadata

    derived = parsed.get("derived_fields")
    if not isinstance(derived, dict):
        raise ValueError("LLM response missing derived_fields object")

    required_keys = ["bucket_name", "bucket_description", "aws_account_id", "aws_region"]
    missing_keys = [key for key in required_keys if not str(derived.get(key, "")).strip()]
    if missing_keys:
        raise ValueError(f"LLM derived_fields missing required keys: {missing_keys}")

    # Keep only configured derived fields so YAML generation and confirmation stay clean.
    allowed_derived = {field.get("name") for field in config.get("derive_fields", []) if field.get("name")}
    clean_derived = {key: value for key, value in derived.items() if key in allowed_derived}
    metadata["derivation"] = parsed.get("derivation") or {}
    return clean_derived, metadata


def _glue_db_llm_payload(collected: dict[str, Any], config: dict) -> dict[str, Any]:
    """Build the compact data payload sent to the Glue DB derivation LLM."""
    return {
        "collected_fields": collected,
        "accounts": _load_accounts(),
        "configured_derivation": config.get("derivation", {}),
        "derive_fields_required": [field.get("name") for field in config.get("derive_fields", [])],
        "minimal_tool_contract": {
            "derived_fields_required": ["database_name", "database_s3_location", "database_description", "aws_account_id", "region"],
            "missing_inputs_behavior": "If you cannot confidently derive, return can_derive=false and list missing_inputs. Do not invent governance-sensitive values.",
        },
    }


async def _derive_glue_db_fields_with_llm(collected: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Use LLM-first Glue DB derivation with only minimal Python shape checks."""
    config = _load_resource_config("glue_db")
    naming_context = _load_glue_db_naming_context()
    payload = _glue_db_llm_payload(collected, config)

    messages = [
        {
            "role": "system",
            "content": (
                "You are the Glue Database naming derivation engine for Minerva/MiNi. "
                "Use the provided Glue DB naming convention reference and collected fields. "
                "Return only a JSON object. Do not use markdown. Do not call tools. "
                "Do not invent missing governance-sensitive values. "
                "Do not perform reviewer-style policy validation; choose the best convention and derive candidate fields."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Glue DB naming convention reference:\n{naming_context}\n\n"
                "Input payload:\n"
                f"{json.dumps(payload, indent=2)}\n\n"
                "Return this exact JSON shape:\n"
                "{\n"
                "  \"can_derive\": true,\n"
                "  \"missing_inputs\": [],\n"
                "  \"derived_fields\": {\n"
                "    \"database_name\": \"...\",\n"
                "    \"database_s3_location\": \"s3://.../\",\n"
                "    \"database_description\": \"...\",\n"
                "    \"aws_account_id\": \"...\",\n"
                "    \"region\": \"us-east-1\"\n"
                "  },\n"
                "  \"derivation\": {\n"
                "    \"convention\": \"...\",\n"
                "    \"account_association\": \"Lakehouse|Compute|Unknown\",\n"
                "    \"aws_account_abbreviation\": \"...\",\n"
                "    \"source_or_product_token\": \"...\",\n"
                "    \"s3_location_pattern\": \"...\",\n"
                "    \"confidence\": 0.0,\n"
                "    \"reasoning\": \"short reason\"\n"
                "  }\n"
                "}\n"
                "If any needed value is missing, return can_derive=false, missing_inputs with field names/descriptions, and no derived_fields."
            ),
        },
    ]

    response = await chat_with_tools(messages)
    parsed = _extract_json_object(response.get("content"))

    metadata = {
        "strategy": "llm_first",
        "llm_response": parsed,
    }

    missing_inputs = parsed.get("missing_inputs") or []
    if parsed.get("can_derive") is False or missing_inputs:
        metadata["missing_inputs"] = missing_inputs
        return None, metadata

    derived = parsed.get("derived_fields")
    if not isinstance(derived, dict):
        raise ValueError("LLM response missing derived_fields object")

    required_keys = ["database_name", "database_s3_location", "database_description", "aws_account_id", "region"]
    missing_keys = [key for key in required_keys if not str(derived.get(key, "")).strip()]
    if missing_keys:
        raise ValueError(f"LLM derived_fields missing required keys: {missing_keys}")

    # Keep only configured derived fields so YAML generation and confirmation stay clean.
    allowed_derived = {field.get("name") for field in config.get("derive_fields", []) if field.get("name")}
    clean_derived = {key: value for key, value in derived.items() if key in allowed_derived}
    metadata["derivation"] = parsed.get("derivation") or {}
    return clean_derived, metadata


async def derive_fields(resource_id: str, **kwargs) -> str:
    """Derive computable fields for a resource."""
    session = _get_session()
    resource = session.get_resource(resource_id)

    if not resource:
        return json.dumps({"error": f"Resource '{resource_id}' not found"})

    if resource.status in (ResourceStatus.DONE, ResourceStatus.DROPPED):
        return json.dumps({"error": f"Cannot derive — resource status is '{resource.status.value}'. Resource is finalized."})

    # Guard: all required collect_fields must be present before deriving
    config = _load_resource_config(resource.resource_type)
    missing = []
    for field_spec in config.get("collect_fields", []):
        field_name = field_spec["name"]
        is_required = field_spec.get("required", False)
        allow_empty = field_spec.get("allow_empty", False)

        # Handle required_when condition
        required_when = field_spec.get("required_when")
        if required_when and not is_required:
            if " == " in required_when:
                cond_field, cond_value = required_when.split(" == ", 1)
                actual = resource.collected_fields.get(cond_field.strip(), "")
                if str(actual).strip() == cond_value.strip():
                    is_required = True
                    allow_empty = False

        if not is_required:
            continue
        if allow_empty:
            continue
        if field_name not in resource.collected_fields:
            missing.append(field_name)

    if missing:
        return json.dumps({
            "error": "Cannot derive — required fields are still missing",
            "missing_fields": missing,
            "resource_id": resource.resource_id,
        })

    # Route to resource-specific derivation
    derivation_metadata = None
    if resource.resource_type == "s3":
        try:
            derived, derivation_metadata = await _derive_s3_fields_with_llm(resource.collected_fields)
        except Exception as exc:
            return json.dumps({
                "error": "S3 LLM derivation failed",
                "resource_id": resource.resource_id,
                "detail": str(exc),
                "next_action": "Ask the user for missing context if applicable, then re-run derivation. Reviewer will perform full governance validation later.",
            }, default=str)

        if derived is None:
            missing_inputs = (derivation_metadata or {}).get("missing_inputs") or []
            return json.dumps({
                "error": "Cannot derive S3 fields — LLM identified missing naming inputs",
                "resource_id": resource.resource_id,
                "missing_inputs": missing_inputs,
                "derivation_metadata": derivation_metadata,
                "next_action": "Ask the user for the missing S3 naming inputs, store them with set_fields if they are configured collect fields, then re-run derive_fields.",
            }, default=str)
    elif resource.resource_type == "glue_db":
        try:
            derived, derivation_metadata = await _derive_glue_db_fields_with_llm(resource.collected_fields)
        except Exception as exc:
            return json.dumps({
                "error": "Glue DB LLM derivation failed",
                "resource_id": resource.resource_id,
                "detail": str(exc),
                "next_action": "Ask the user for missing context if applicable, then re-run derivation. Reviewer will perform full governance validation later.",
            }, default=str)

        if derived is None:
            missing_inputs = (derivation_metadata or {}).get("missing_inputs") or []
            return json.dumps({
                "error": "Cannot derive Glue DB fields — LLM identified missing naming inputs",
                "resource_id": resource.resource_id,
                "missing_inputs": missing_inputs,
                "derivation_metadata": derivation_metadata,
                "next_action": "Ask the user for the missing Glue DB naming inputs, store them with set_fields if they are configured collect fields, then re-run derive_fields.",
            }, default=str)
    else:
        derived = {}

    # Store derived fields
    resource.derived_fields = derived
    resource.status = ResourceStatus.CONFIRMING
    await save_resource(session.session_id, resource)

    # Code-enforced create-flow existence check: after derivation, resolve the
    # expected MIW repo path and block later create PR if the file already exists.
    resource_existence = None
    try:
        from tools.repo_tools import check_resource_exists
        existence_result = await check_resource_exists(resource_id=resource.resource_id)
        resource_existence = json.loads(existence_result)
    except Exception as exc:
        resource_existence = {
            "error": "Repository existence check failed",
            "detail": str(exc),
        }

    return json.dumps({
        "resource_id": resource.resource_id,
        "status": "confirming",
        "derived_fields": derived,
        "all_fields": resource.all_fields,
        "derivation_metadata": derivation_metadata,
        "resource_existence": resource_existence,
    }, default=str)

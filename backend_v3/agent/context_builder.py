"""Context builder — assembles the system prompt with dynamic context."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from models.state import Session

_CONTEXT_DIR = Path(__file__).resolve().parent.parent / "context"
_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def _build_supported_resources_section() -> str:
    """Build supported resources context from config/settings.yaml."""
    settings_path = _CONFIG_DIR / "settings.yaml"
    if not settings_path.exists():
        return "\n\n# Supported Resources\nNo supported resources are configured."

    data = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
    resources = data.get("supported_resources", [])
    unsupported_message = data.get("unsupported_message", "")

    lines = [
        "\n\n# Supported Resources (dynamic from config/settings.yaml)",
        "Resolve user resource requests using this list and aliases.",
    ]
    for item in resources:
        if isinstance(item, dict):
            rtype = item.get("type", "")
            display = item.get("display", rtype)
            aliases = item.get("aliases", [])
        else:
            rtype = str(item)
            display = rtype
            aliases = []
        alias_text = ", ".join(aliases) if aliases else "none"
        lines.append(f"- `{rtype}` — {display}; aliases: {alias_text}")

    if unsupported_message:
        lines.append("\nIf a request does not match these resources, use this message:")
        lines.append(unsupported_message.strip())

    return "\n".join(lines)


def _build_pre_validation_section() -> str:
    """Build pre-validation context from config/pre_validations.yaml."""
    path = _CONFIG_DIR / "pre_validations.yaml"
    if not path.exists():
        return "\n\n# Pre-Validation Requirements\nNo central pre-validation config found."

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    approval = data.get("data_owner_approval", {}) or {}
    if not approval.get("enabled", True):
        return "\n\n# Pre-Validation Requirements\nData owner approval validation is disabled."

    resources = ", ".join(approval.get("resources", [])) or "none"
    file_types = ", ".join(approval.get("accepted_file_types", [])) or "not configured"
    tool = approval.get("validator_tool", "validate_data_owner_approval_document")
    description = approval.get("description", "Upload data owner approval evidence.")

    return "\n".join([
        "\n\n# Pre-Validation Requirements (dynamic from config/pre_validations.yaml)",
        f"- Data owner approval resources: {resources}",
        f"- Required tool: `{tool}`",
        f"- Accepted file types: {file_types}",
        f"- User instruction: {description}",
        "If `create_resources` blocks a resource for data_owner_approval, ask for an approval PDF or screenshot before retrying that resource.",
    ])


def _build_route_skills_section(active_route: str | None = None) -> str:
    """Build create/update route skill context from context/skills/*.md."""
    skills_dir = _CONTEXT_DIR / "skills"
    if not skills_dir.exists():
        return ""
    parts = ["\n\n# Route Skills"]
    if active_route == "create":
        names = ["create_resource.md"]
    elif active_route == "update":
        names = ["update_resource.md"]
    else:
        names = ["create_resource.md", "update_resource.md"]
    for name in names:
        path = skills_dir / name
        if path.exists():
            parts.append(path.read_text(encoding="utf-8").strip())
    return "\n\n".join(parts)


def _build_update_capabilities_section(active_route: str | None = None) -> str:
    """Build update route requirements from config/update_capabilities.yaml."""
    if active_route != "update":
        return "\n\n# Update Capabilities\nHidden unless the active route is `update`."

    path = _CONFIG_DIR / "update_capabilities.yaml"
    if not path.exists():
        return "\n\n# Update Capabilities\nNo update capability config found."

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    capabilities = data.get("update_capabilities", {}) or {}
    lines = [
        "\n\n# Update Capabilities (dynamic from config/update_capabilities.yaml)",
        "Use this only in update route. In create route, do not switch to update when a resource already exists.",
    ]
    for resource_type, capability in capabilities.items():
        enabled = bool(capability.get("enabled", False))
        display = capability.get("display_name", resource_type)
        lines.append(f"- `{resource_type}` — {display}; update_enabled={str(enabled).lower()}")
        if not enabled:
            reason = capability.get("reason")
            if reason:
                lines.append(f"  - reason: {reason}")
            continue
        required_inputs = capability.get("required_inputs", []) or []
        if required_inputs:
            lines.append("  - Required before fetching existing file:")
            for field in required_inputs:
                example = field.get("example")
                example_text = f"; example: {example}" if example else ""
                lines.append(f"    - `{field.get('name')}` — {field.get('description', '')}{example_text}")
        if capability.get("append_only"):
            lines.append("  - Update rule: append-only; do not modify/delete existing YAML.")
        input_rule = capability.get("input_rule")
        if input_rule:
            lines.append(f"  - Input rule: {input_rule}")
    lines.append("Never invent branch, resource_name, or file_path. Prefer asking for branch + resource_name; use full file_path only if user provides it or name lookup is ambiguous.")
    return "\n".join(lines)


def _filter_system_prompt_for_route(system_md: str, active_route: str | None) -> str:
    """Remove route-specific guidance that is not relevant to the active route."""
    if active_route == "create":
        return re.sub(
            r"\n---\n\n# Resource Update Flow\n.*?(?=\n---\n)",
            "",
            system_md,
            flags=re.DOTALL,
        )
    if active_route == "update":
        return re.sub(
            r"\n---\n\n# Resource Creation Flow\n.*?(?=\n---\n)",
            "",
            system_md,
            flags=re.DOTALL,
        )
    return system_md


def build_system_prompt(session: Session, user_profile: str | None, active_route: str | None = None) -> str:
    """
    Build the full system prompt by combining:
    1. Base system prompt (system.md)
    2. User profile (behavioral description, if any)
    3. Supported resource types hint
    """
    # 1. Base system prompt
    system_md = (_CONTEXT_DIR / "system.md").read_text(encoding="utf-8")
    system_md = _filter_system_prompt_for_route(system_md, active_route)

    # 2. User profile
    profile_section = ""
    if user_profile:
        profile_section = (
            "\n\n# User Profile (adapt your style to this user)\n"
            + user_profile
        )
    else:
        profile_section = (
            "\n\n# User Profile\n"
            "No profile yet — this is a new user. Observe their behavior and update the profile "
            "after a productive interaction using `update_user_profile`."
        )

    # 3. Supported resources from settings.yaml
    resource_hint = _build_supported_resources_section()

    # 4. Pre-validation requirements from pre_validations.yaml
    pre_validation_hint = _build_pre_validation_section()

    # 5. Route skills
    route_skills_hint = _build_route_skills_section(active_route)

    # 6. Update capabilities
    update_capabilities_hint = _build_update_capabilities_section(active_route)

    return system_md + profile_section + resource_hint + pre_validation_hint + route_skills_hint + update_capabilities_hint


def build_conversation_messages(session: Session) -> list[dict]:
    """
    Convert session messages to OpenAI format.
    Only include user/assistant messages (not internal tool messages).
    """
    messages = []
    for msg in session.messages:
        if msg.role in ("user", "assistant"):
            entry = {"role": msg.role, "content": msg.content}
            if msg.role == "assistant" and msg.tool_calls:
                entry["tool_calls"] = msg.tool_calls
            messages.append(entry)
    return messages

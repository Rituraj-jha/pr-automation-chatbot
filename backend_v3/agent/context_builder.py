"""Context builder — assembles the system prompt with dynamic context."""
from __future__ import annotations

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


def build_system_prompt(session: Session, user_profile: str | None) -> str:
    """
    Build the full system prompt by combining:
    1. Base system prompt (system.md)
    2. User profile (behavioral description, if any)
    3. Supported resource types hint
    """
    # 1. Base system prompt
    system_md = (_CONTEXT_DIR / "system.md").read_text(encoding="utf-8")

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

    return system_md + profile_section + resource_hint


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

"""Data models for the agent system."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ResourceStatus(str, Enum):
    COLLECTING = "collecting"
    CONFIRMING = "confirming"
    REVIEWING = "reviewing"
    DONE = "done"
    DROPPED = "dropped"


@dataclass
class Resource:
    """A single resource being provisioned."""

    resource_id: str  # e.g. "s3_0", "s3_1", "glue_db_0"
    resource_type: str  # e.g. "s3", "glue_db"
    status: ResourceStatus = ResourceStatus.COLLECTING
    collected_fields: dict[str, Any] = field(default_factory=dict)
    derived_fields: dict[str, Any] = field(default_factory=dict)
    user_overrides: dict[str, Any] = field(default_factory=dict)
    yaml_output: str | None = None
    validation_result: dict | None = None

    @property
    def all_fields(self) -> dict[str, Any]:
        """Merged view: collected + derived + user overrides (overrides win)."""
        return {**self.collected_fields, **self.derived_fields, **self.user_overrides}

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "resource_type": self.resource_type,
            "status": self.status.value,
            "collected_fields": self.collected_fields,
            "derived_fields": self.derived_fields,
            "user_overrides": self.user_overrides,
            "yaml_output": self.yaml_output,
            "validation_result": self.validation_result,
        }


@dataclass
class Message:
    """A single conversation message."""

    role: str  # "user" | "assistant" | "tool"
    content: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    tool_calls: list[dict] | None = None  # for assistant messages with tool calls


@dataclass
class Preference:
    """A user preference stored for personalization."""

    key: str  # e.g. "fields_per_turn", "tone"
    value: str  # e.g. "2", "concise"
    user_id: str = "default"


@dataclass
class Session:
    """A conversation session with resources."""

    session_id: str
    user_id: str = "default"
    resources: list[Resource] = field(default_factory=list)
    messages: list[Message] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)

    def get_resource(self, resource_id: str) -> Resource | None:
        """Find resource by ID (supports fuzzy matching)."""
        # Exact match first
        for r in self.resources:
            if r.resource_id == resource_id:
                return r
        # Fuzzy: strip non-alphanumeric and compare
        clean = resource_id.lower().replace("_", "").replace("-", "")
        for r in self.resources:
            if r.resource_id.lower().replace("_", "").replace("-", "") == clean:
                return r
        return None

    def next_resource_id(self, resource_type: str) -> str:
        """Generate next unique ID for a resource type."""
        count = sum(1 for r in self.resources if r.resource_type == resource_type)
        return f"{resource_type}_{count}"

    def add_message(self, role: str, content: str, tool_calls: list[dict] | None = None):
        self.messages.append(Message(role=role, content=content, tool_calls=tool_calls))

    def to_state_summary(self) -> dict[str, Any]:
        """Compact state for tool responses."""
        return {
            "session_id": self.session_id,
            "resources": [r.to_dict() for r in self.resources],
            "message_count": len(self.messages),
        }

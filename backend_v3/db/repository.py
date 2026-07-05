"""Database repository — CRUD for sessions, resources, messages, preferences."""
from __future__ import annotations

import json
from datetime import datetime

from db.connection import get_db
from models.state import Session, Resource, Message, Preference, ResourceStatus


# ─── Sessions ─────────────────────────────────────────────────────────────────

async def save_session(session: Session, title: str | None = None):
    """Upsert session metadata."""
    db = await get_db()
    t = title or getattr(session, "title", "New Chat") or "New Chat"
    await db.execute(
        "INSERT OR REPLACE INTO sessions (session_id, user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (session.session_id, session.user_id, t, session.created_at.isoformat(), datetime.utcnow().isoformat()),
    )
    await db.commit()


async def load_session(session_id: str) -> Session | None:
    """Load a session with its resources and messages."""
    db = await get_db()
    row = await db.execute_fetchall(
        "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
    )
    if not row:
        return None

    session = Session(session_id=session_id, user_id=row[0]["user_id"])

    # Load resources
    resource_rows = await db.execute_fetchall(
        "SELECT * FROM resources WHERE session_id = ? ORDER BY id", (session_id,)
    )
    for r in resource_rows:
        vr_raw = r["validation_result"] if "validation_result" in r.keys() else None
        session.resources.append(Resource(
            resource_id=r["resource_id"],
            resource_type=r["resource_type"],
            status=ResourceStatus(r["status"]),
            collected_fields=json.loads(r["collected_fields"]),
            derived_fields=json.loads(r["derived_fields"]),
            user_overrides=json.loads(r["user_overrides"]) if r["user_overrides"] else {},
            yaml_output=r["yaml_output"],
            validation_result=json.loads(vr_raw) if vr_raw else None,
        ))

    # Load messages
    msg_rows = await db.execute_fetchall(
        "SELECT * FROM messages WHERE session_id = ? ORDER BY id", (session_id,)
    )
    for m in msg_rows:
        session.messages.append(Message(
            role=m["role"],
            content=m["content"],
            tool_calls=json.loads(m["tool_calls"]) if m["tool_calls"] else None,
        ))

    return session


async def list_sessions(user_id: str) -> list[dict]:
    """List all sessions for a user (for chat history sidebar)."""
    db = await get_db()
    rows = await db.execute_fetchall(
        """SELECT session_id, title, created_at, updated_at,
           (SELECT COUNT(*) FROM messages WHERE messages.session_id = sessions.session_id) as message_count
           FROM sessions WHERE user_id = ? ORDER BY updated_at DESC""",
        (user_id,),
    )
    return [
        {
            "id": r["session_id"],
            "title": r["title"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
            "message_count": r["message_count"],
        }
        for r in rows
    ]


async def delete_session(session_id: str):
    """Delete a session and all related data."""
    db = await get_db()
    await db.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    await db.execute("DELETE FROM resources WHERE session_id = ?", (session_id,))
    await db.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
    await db.commit()


async def update_session_title(session_id: str, title: str):
    """Update the title of a session."""
    db = await get_db()
    await db.execute(
        "UPDATE sessions SET title = ?, updated_at = ? WHERE session_id = ?",
        (title, datetime.utcnow().isoformat(), session_id),
    )
    await db.commit()


async def get_session_messages(session_id: str) -> list[dict]:
    """Get messages for a session in API format."""
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT id, role, content, tool_calls, created_at FROM messages WHERE session_id = ? AND role IN ('user', 'assistant') ORDER BY id",
        (session_id,),
    )
    return [
        {
            "id": r["id"],
            "role": r["role"],
            "content": r["content"],
            "created_at": r["created_at"],
            "metadata_json": None,
        }
        for r in rows
    ]


# ─── Resources ────────────────────────────────────────────────────────────────

async def save_resource(session_id: str, resource: Resource):
    """Upsert a resource."""
    db = await get_db()
    await db.execute(
        """INSERT OR REPLACE INTO resources
           (session_id, resource_id, resource_type, status, collected_fields, derived_fields, user_overrides, yaml_output, validation_result)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            session_id,
            resource.resource_id,
            resource.resource_type,
            resource.status.value,
            json.dumps(resource.collected_fields),
            json.dumps(resource.derived_fields),
            json.dumps(resource.user_overrides),
            resource.yaml_output,
            json.dumps(resource.validation_result) if resource.validation_result is not None else None,
        ),
    )
    await db.commit()


# ─── Messages ─────────────────────────────────────────────────────────────────

async def save_message(session_id: str, message: Message):
    """Append a message to the session."""
    db = await get_db()
    await db.execute(
        "INSERT INTO messages (session_id, role, content, tool_calls, created_at) VALUES (?, ?, ?, ?, ?)",
        (
            session_id,
            message.role,
            message.content,
            json.dumps(message.tool_calls) if message.tool_calls else None,
            message.timestamp.isoformat(),
        ),
    )
    await db.commit()


# ─── Preferences (legacy, kept for backward compat) ──────────────────────────

async def save_preference(user_id: str, key: str, value: str):
    """Upsert a user preference."""
    db = await get_db()
    await db.execute(
        """INSERT INTO preferences (user_id, key, value, updated_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(user_id, key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
        (user_id, key, value, datetime.utcnow().isoformat()),
    )
    await db.commit()


async def load_preferences(user_id: str) -> list[Preference]:
    """Load all preferences for a user."""
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT key, value FROM preferences WHERE user_id = ?", (user_id,)
    )
    return [Preference(key=r["key"], value=r["value"], user_id=user_id) for r in rows]


# ─── User Profiles ───────────────────────────────────────────────────────────

async def save_user_profile(user_id: str, profile: str):
    """Upsert the user's behavioral profile."""
    db = await get_db()
    await db.execute(
        """INSERT INTO user_profiles (user_id, profile, updated_at)
           VALUES (?, ?, ?)
           ON CONFLICT(user_id) DO UPDATE SET profile=excluded.profile, updated_at=excluded.updated_at""",
        (user_id, profile, datetime.utcnow().isoformat()),
    )
    await db.commit()


async def load_user_profile(user_id: str) -> str | None:
    """Load the user's behavioral profile."""
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT profile FROM user_profiles WHERE user_id = ?", (user_id,)
    )
    if rows and rows[0]["profile"]:
        return rows[0]["profile"]
    return None


# ─── GitHub Tokens ────────────────────────────────────────────────────────────

async def save_github_token(user_id: str, token: str):
    """Store/update GitHub OAuth token for a user."""
    db = await get_db()
    await db.execute(
        """INSERT INTO github_tokens (user_id, token, updated_at)
           VALUES (?, ?, ?)
           ON CONFLICT(user_id) DO UPDATE SET token=excluded.token, updated_at=excluded.updated_at""",
        (user_id, token, datetime.utcnow().isoformat()),
    )
    await db.commit()


async def load_github_token(user_id: str) -> str | None:
    """Retrieve stored GitHub token for a user."""
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT token FROM github_tokens WHERE user_id = ?", (user_id,)
    )
    if rows:
        return rows[0]["token"]
    return None


# ─── Session Fields (cross-resource reuse) ────────────────────────────────────

async def save_session_field(session_id: str, field_name: str, field_value: str):
    """Upsert a session-level field value for cross-resource reuse."""
    db = await get_db()
    await db.execute(
        """INSERT INTO session_fields (session_id, field_name, field_value, updated_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(session_id, field_name) DO UPDATE SET
             field_value=excluded.field_value, updated_at=excluded.updated_at""",
        (session_id, field_name, field_value, datetime.utcnow().isoformat()),
    )
    await db.commit()


async def load_session_fields(session_id: str) -> dict[str, str]:
    """Load all session-level field values for prefill."""
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT field_name, field_value FROM session_fields WHERE session_id = ?",
        (session_id,),
    )
    return {r["field_name"]: r["field_value"] for r in rows}

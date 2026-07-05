"""
GitHub OAuth — handles Cargill Enterprise GitHub SSO.
Authorization flow, token exchange, and user info lookup.
"""
from __future__ import annotations

import os
import secrets
import logging
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Config from env
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "")
GITHUB_ENTERPRISE_URL = (os.getenv("GITHUB_ENTERPRISE_URL") or "").rstrip("/")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
CA_BUNDLE = os.getenv("CUSTOM_CA_BUNDLE_PATH") or True

# Enterprise or public GitHub
GITHUB_WEB = GITHUB_ENTERPRISE_URL if GITHUB_ENTERPRISE_URL else "https://github.com"
GITHUB_API = f"{GITHUB_ENTERPRISE_URL}/api/v3" if GITHUB_ENTERPRISE_URL else "https://api.github.com"

# Allowed redirect origins for return_to parameter
ALLOWED_REDIRECT_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174",
]

# In-memory CSRF state store
_oauth_states: dict[str, dict] = {}


def get_auth_url(return_to: str | None = None) -> str:
    """Generate GitHub OAuth authorization URL with CSRF state."""
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = {
        "created_at": datetime.now(timezone.utc),
        "return_to": return_to,
    }

    params = urlencode({
        "client_id": GITHUB_CLIENT_ID,
        "scope": "repo user:email",
        "state": state,
    })
    return f"{GITHUB_WEB}/login/oauth/authorize?{params}"


def pop_state(state: str) -> dict | None:
    """Pop and return stored state dict, or None if invalid."""
    return _oauth_states.pop(state, None)


async def exchange_code(code: str, state: str | None = None) -> str:
    """Exchange authorization code for access token.

    Note: state validation/pop is now handled by pop_state() in the callback
    before this function is called, so we only do the token exchange here.
    """

    async with httpx.AsyncClient(verify=CA_BUNDLE, timeout=30) as client:
        resp = await client.post(
            f"{GITHUB_WEB}/login/oauth/access_token",
            json={
                "client_id": GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "code": code,
            },
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()

    data = resp.json()
    if "error" in data:
        raise ValueError(data.get("error_description", data["error"]))

    token = data.get("access_token")
    if not token:
        raise ValueError("No access_token in GitHub response")
    return token


async def get_username(token: str) -> str:
    """Fetch GitHub username from access token."""
    async with httpx.AsyncClient(verify=CA_BUNDLE, timeout=30) as client:
        resp = await client.get(
            f"{GITHUB_API}/user",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
        )
        resp.raise_for_status()

    username = resp.json().get("login")
    if not username:
        raise ValueError("GitHub username missing in response")
    return username

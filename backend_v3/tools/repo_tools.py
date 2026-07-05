"""Repository tools — route-aware GitHub/MIW repo file checks and update helpers."""
from __future__ import annotations

import difflib
import base64
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import yaml as pyyaml
from dotenv import load_dotenv

from db.repository import load_github_token, save_session_field
from tools.session_tools import _get_session

load_dotenv()

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
_BACKEND_DIR = Path(__file__).resolve().parent.parent

_REPO_MAP: dict | None = None
_ACCOUNTS: list[dict] | None = None
_UPDATE_CAPABILITIES: dict | None = None

GITHUB_ENTERPRISE_URL = (os.getenv("GITHUB_ENTERPRISE_URL") or "").rstrip("/")
GITHUB_API = f"{GITHUB_ENTERPRISE_URL}/api/v3" if GITHUB_ENTERPRISE_URL else "https://api.github.com"
GITHUB_UPSTREAM_OWNER = os.getenv("GITHUB_UPSTREAM_OWNER", "")
GITHUB_UPSTREAM_REPO = os.getenv("GITHUB_UPSTREAM_REPO", "")
GITHUB_UPSTREAM_BRANCH = os.getenv("GITHUB_UPSTREAM_BRANCH", "main")
CA_BUNDLE = os.getenv("CUSTOM_CA_BUNDLE_PATH") or True

RESOURCE_EXISTS_PREFIX = "__resource_exists:"
RESOURCE_EXISTENCE_DETAIL_PREFIX = "__resource_existence_detail:"
PENDING_UPDATE_KEY = "__pending_update"


class RepoAuthError(RuntimeError):
    """Raised when GitHub lookup needs authentication/configuration."""


def _repo_source() -> str:
    return str(_load_repo_map().get("existence_check", {}).get("source", "local_mock")).lower()


def _github_configured() -> bool:
    return bool(GITHUB_UPSTREAM_OWNER and GITHUB_UPSTREAM_REPO)


async def _github_token() -> str | None:
    session = _get_session()
    return await load_github_token(session.user_id)


def _github_headers(token: str | None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"token {token}"
    return headers


def _github_auth_error() -> dict:
    return {
        "error": "GitHub repository lookup is configured, but no GitHub token is available for this user.",
        "action_needed": "github_auth",
        "repo_owner": GITHUB_UPSTREAM_OWNER,
        "repo_name": GITHUB_UPSTREAM_REPO,
        "message": "Please authenticate with GitHub, then retry. Console tests need a saved GitHub token for the console user.",
    }


def _github_config_error() -> dict:
    return {
        "error": "GitHub repository lookup is configured, but GITHUB_UPSTREAM_OWNER or GITHUB_UPSTREAM_REPO is missing in .env.",
        "action_needed": "configure_github_repo",
    }


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return pyyaml.safe_load(f) or {}


def _load_repo_map() -> dict:
    """Load repo_directory_map.yaml."""
    global _REPO_MAP
    if _REPO_MAP is None:
        _REPO_MAP = _load_yaml(_CONFIG_DIR / "repo_directory_map.yaml")
    return _REPO_MAP


def _load_accounts() -> list[dict]:
    """Load account config."""
    global _ACCOUNTS
    if _ACCOUNTS is None:
        data = _load_yaml(_CONFIG_DIR / "accounts.yaml")
        _ACCOUNTS = data.get("accounts", [])
    return _ACCOUNTS


def _load_update_capabilities() -> dict:
    """Load update_capabilities.yaml."""
    global _UPDATE_CAPABILITIES
    if _UPDATE_CAPABILITIES is None:
        data = _load_yaml(_CONFIG_DIR / "update_capabilities.yaml")
        _UPDATE_CAPABILITIES = data.get("update_capabilities", {}) or {}
    return _UPDATE_CAPABILITIES


def _account_for_id(account_id: str) -> dict | None:
    clean_id = str(account_id or "").strip("'\"")
    return next((a for a in _load_accounts() if str(a.get("id")) == clean_id), None)


def _compute_number_from_account(account: dict) -> int:
    if account.get("compute_number"):
        return int(account["compute_number"])
    abbreviation = str(account.get("abbreviation", ""))
    match = re.search(r"cmp(\d+)", abbreviation)
    if match:
        return int(match.group(1))
    return 1


def resolve_resource_repo_path(resource_type: str, fields: dict[str, Any]) -> str:
    """Resolve a resource's repo-relative YAML path from fields and config."""
    repo_map = _load_repo_map()
    platform_root = repo_map.get("platforms", {}).get("aws_lakehouse", {}).get("root", "aws_lakehouse")
    resource_folder = repo_map.get("resource_folders", {}).get(resource_type, resource_type)
    naming = repo_map.get("file_naming", {}).get(resource_type, {})
    name_field = naming.get("name_field")
    extension = naming.get("extension", ".yaml")

    resource_name = fields.get(name_field) if name_field else None
    if not resource_name:
        resource_name = (
            fields.get("bucket_name")
            or fields.get("database_name")
            or fields.get("role_name")
            or fields.get("intake_id")
            or "unknown"
        )

    account = _account_for_id(str(fields.get("aws_account_id", "")))
    if account:
        account_type = account.get("type")
        account_folders = repo_map.get("account_folders", {})
        if account_type == "lakehouse":
            account_folder = account_folders.get("lakehouse", {}).get("folder", "lakehouse-001")
        elif account_type == "compute":
            pattern = account_folders.get("compute", {}).get("folder_pattern", "compute-{compute_number:03d}")
            account_folder = pattern.format(compute_number=_compute_number_from_account(account))
        else:
            account_folder = str(account.get("abbreviation") or account_type or "unknown-account")
    else:
        account_folder = "unknown-account"

    return "/".join([
        platform_root.strip("/"),
        account_folder.strip("/"),
        resource_folder.strip("/"),
        f"{resource_name}{extension}",
    ])


def _local_repo_root() -> Path:
    repo_map = _load_repo_map()
    configured = repo_map.get("repo", {}).get("local_mock_root", "../miw-repo/miw-object-provisioning")
    path = Path(configured)
    if not path.is_absolute():
        path = (_BACKEND_DIR / path).resolve()
    return path


def _candidate_paths(repo_relative_path: str) -> list[Path]:
    """Return local candidate paths, including yaml/yml extension alternatives."""
    root = _local_repo_root()
    primary = root.joinpath(*repo_relative_path.replace("\\", "/").split("/"))
    candidates = [primary]
    suffix = primary.suffix.lower()
    if suffix == ".yaml":
        candidates.append(primary.with_suffix(".yml"))
    elif suffix == ".yml":
        candidates.append(primary.with_suffix(".yaml"))
    return candidates


def _allowed_path_prefixes() -> list[str]:
    repo_map = _load_repo_map()
    prefixes = repo_map.get("existence_check", {}).get("allowed_path_prefixes", []) or []
    return [str(prefix).replace("\\", "/") for prefix in prefixes]


def _normalize_repo_relative_path(path: str) -> str:
    """Normalize user/local paths to paths relative to the actual GitHub repo root.

    The configured GitHub repo is the `miw-object-provisioning` repo itself, so paths
    inside GitHub should look like `aws_lakehouse/...`. Users may still paste local
    workspace-style paths like `miw-repo/miw-object-provisioning/aws_lakehouse/...`.
    """
    normalized = str(path or "").strip().replace("\\", "/")
    wrapper_prefixes = [
        "miw-repo/miw-object-provisioning/",
        "miw-object-provisioning/",
    ]
    for prefix in wrapper_prefixes:
        if normalized.startswith(prefix):
            return normalized.removeprefix(prefix)
    github_root = str(_load_repo_map().get("repo", {}).get("github_root", "") or "").strip("/")
    if github_root and normalized.startswith(f"{github_root}/"):
        return normalized.removeprefix(f"{github_root}/")
    return normalized


def _is_allowed_repo_path(path: str) -> bool:
    original = str(path or "").strip().replace("\\", "/")
    normalized = _normalize_repo_relative_path(original)
    prefixes = _allowed_path_prefixes()
    if not prefixes:
        return True
    return any(original.startswith(prefix) or normalized.startswith(prefix) for prefix in prefixes)


def _normalize_resource_name(name: str) -> str:
    value = str(name or "").strip().replace("\\", "/")
    value = value.rsplit("/", 1)[-1]
    if value.lower().endswith((".yaml", ".yml")):
        value = value.rsplit(".", 1)[0]
    return value


def _find_resource_files_by_name(resource_type: str, resource_name: str) -> list[Path]:
    """Find candidate YAML files for a resource name using repo_directory_map.yaml."""
    normalized_name = _normalize_resource_name(resource_name)
    if not normalized_name:
        return []

    repo_map = _load_repo_map()
    repo_root = _local_repo_root()
    platform_root = repo_map.get("platforms", {}).get("aws_lakehouse", {}).get("root", "aws_lakehouse")
    resource_folder = repo_map.get("resource_folders", {}).get(resource_type, resource_type)
    extensions = repo_map.get("existence_check", {}).get("accepted_extensions", [".yaml", ".yml"]) or [".yaml", ".yml"]
    matches: list[Path] = []

    platform_path = repo_root / platform_root
    if not platform_path.exists():
        return []

    for account_dir in platform_path.iterdir():
        if not account_dir.is_dir():
            continue
        resource_dir = account_dir / resource_folder
        if not resource_dir.exists() or not resource_dir.is_dir():
            continue
        for extension in extensions:
            candidate = resource_dir / f"{normalized_name}{extension}"
            if candidate.exists() and candidate.is_file():
                matches.append(candidate)
    return matches


def _match_resource_path(resource_type: str, resource_name: str, path: str) -> bool:
    """Return True if a repo path matches configured platform/resource folder/name."""
    repo_map = _load_repo_map()
    platform_root = repo_map.get("platforms", {}).get("aws_lakehouse", {}).get("root", "aws_lakehouse")
    resource_folder = repo_map.get("resource_folders", {}).get(resource_type, resource_type)
    extensions = repo_map.get("existence_check", {}).get("accepted_extensions", [".yaml", ".yml"]) or [".yaml", ".yml"]
    normalized_name = _normalize_resource_name(resource_name)
    normalized_path = _normalize_repo_relative_path(path)
    parts = normalized_path.split("/")
    if len(parts) < 4:
        return False
    if parts[0] != platform_root:
        return False
    if parts[-2] != resource_folder:
        return False
    return any(parts[-1] == f"{normalized_name}{extension}" for extension in extensions)


async def _github_get_file(path: str, branch: str, token: str | None) -> dict:
    """Get a file from configured GitHub repo using Contents API."""
    if not _github_configured():
        return {"found": False, **_github_config_error()}
    if not token:
        return {"found": False, **_github_auth_error()}

    normalized_path = path.strip().replace("\\", "/")
    encoded_path = "/".join(quote(part, safe="") for part in normalized_path.split("/"))
    url = f"{GITHUB_API}/repos/{GITHUB_UPSTREAM_OWNER}/{GITHUB_UPSTREAM_REPO}/contents/{encoded_path}"
    async with httpx.AsyncClient(headers=_github_headers(token), verify=CA_BUNDLE, timeout=30) as client:
        resp = await client.get(url, params={"ref": branch})

    if resp.status_code == 404:
        return {"found": False, "file_path": normalized_path}
    if resp.status_code not in (200, 201):
        return {
            "found": False,
            "error": f"GitHub file lookup failed: HTTP {resp.status_code}",
            "detail": resp.text[:500],
        }

    data = resp.json()
    if data.get("type") != "file":
        return {"found": False, "error": f"GitHub path is not a file: {normalized_path}"}

    encoded_content = data.get("content") or ""
    try:
        content = base64.b64decode(encoded_content).decode("utf-8")
    except Exception:
        content = ""

    return {
        "found": True,
        "file_path": normalized_path,
        "content": content,
        "sha": data.get("sha"),
        "html_url": data.get("html_url"),
    }


async def _github_tree_paths(branch: str, token: str | None) -> dict:
    """Return recursive tree paths from configured GitHub repo."""
    if not _github_configured():
        return {"success": False, **_github_config_error()}
    if not token:
        return {"success": False, **_github_auth_error()}

    encoded_branch = quote(branch, safe="")
    async with httpx.AsyncClient(headers=_github_headers(token), verify=CA_BUNDLE, timeout=30) as client:
        ref_resp = await client.get(
            f"{GITHUB_API}/repos/{GITHUB_UPSTREAM_OWNER}/{GITHUB_UPSTREAM_REPO}/git/ref/heads/{encoded_branch}"
        )
        if ref_resp.status_code == 404:
            return {"success": False, "error": f"Branch '{branch}' not found in GitHub repo."}
        if ref_resp.status_code not in (200, 201):
            return {
                "success": False,
                "error": f"GitHub branch lookup failed: HTTP {ref_resp.status_code}",
                "detail": ref_resp.text[:500],
            }
        commit_sha = ref_resp.json().get("object", {}).get("sha")
        tree_resp = await client.get(
            f"{GITHUB_API}/repos/{GITHUB_UPSTREAM_OWNER}/{GITHUB_UPSTREAM_REPO}/git/trees/{commit_sha}",
            params={"recursive": "1"},
        )

    if tree_resp.status_code not in (200, 201):
        return {
            "success": False,
            "error": f"GitHub tree lookup failed: HTTP {tree_resp.status_code}",
            "detail": tree_resp.text[:500],
        }
    tree = tree_resp.json().get("tree", [])
    return {
        "success": True,
        "paths": [item.get("path") for item in tree if item.get("type") == "blob" and item.get("path")],
    }


async def _github_find_resource_paths_by_name(resource_type: str, resource_name: str, branch: str, token: str | None) -> dict:
    tree_result = await _github_tree_paths(branch, token)
    if not tree_result.get("success"):
        return tree_result
    matches = [
        path for path in tree_result.get("paths", [])
        if _match_resource_path(resource_type, resource_name, path)
    ]
    return {"success": True, "matches": matches}


def _path_display(path: Path) -> str:
    try:
        root = _local_repo_root()
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


async def check_resource_exists(resource_id: str, **kwargs) -> str:
    """Check whether a derived create-flow resource already exists in the MIW repo."""
    session = _get_session()
    resource = session.get_resource(resource_id)
    if not resource:
        return json.dumps({"error": f"Resource '{resource_id}' not found"})

    repo_map = _load_repo_map()
    if not repo_map.get("existence_check", {}).get("enabled", True):
        return json.dumps({
            "resource_id": resource.resource_id,
            "resource_type": resource.resource_type,
            "skipped": True,
            "message": "Repository existence check is disabled.",
        })

    fields = resource.all_fields
    repo_path = resolve_resource_repo_path(resource.resource_type, fields)
    source = _repo_source()

    if source == "github":
        branch = str(GITHUB_UPSTREAM_BRANCH or repo_map.get("repo", {}).get("default_branch") or "main")
        token = await _github_token()
        github_result = await _github_get_file(repo_path, branch, token)
        if github_result.get("action_needed"):
            result = {
                "resource_id": resource.resource_id,
                "resource_type": resource.resource_type,
                "exists": None,
                "path": repo_path,
                "branch": branch,
                "source": "github",
                **github_result,
            }
            await save_session_field(session.session_id, f"{RESOURCE_EXISTS_PREFIX}{resource.resource_id}", "unknown")
            await save_session_field(session.session_id, f"{RESOURCE_EXISTENCE_DETAIL_PREFIX}{resource.resource_id}", json.dumps(result))
            return json.dumps(result)
        exists = bool(github_result.get("found"))
        resolved_path = repo_path
        result = {
            "resource_id": resource.resource_id,
            "resource_type": resource.resource_type,
            "exists": exists,
            "path": resolved_path,
            "branch": branch,
            "source": "github",
            "repo_owner": GITHUB_UPSTREAM_OWNER,
            "repo_name": GITHUB_UPSTREAM_REPO,
            "sha": github_result.get("sha"),
            "html_url": github_result.get("html_url"),
            "message": (
                "Resource already exists in GitHub. Create flow is blocked for this resource. Ask the user to change fields/name or create another resource."
                if exists
                else "Resource does not exist at the resolved GitHub repo path. Create flow may continue."
            ),
        }
        await save_session_field(session.session_id, f"{RESOURCE_EXISTS_PREFIX}{resource.resource_id}", "true" if exists else "false")
        await save_session_field(session.session_id, f"{RESOURCE_EXISTENCE_DETAIL_PREFIX}{resource.resource_id}", json.dumps(result))
        return json.dumps(result)

    existing_path = next((path for path in _candidate_paths(repo_path) if path.exists()), None)
    exists = existing_path is not None
    resolved_path = _path_display(existing_path) if existing_path else repo_path

    result = {
        "resource_id": resource.resource_id,
        "resource_type": resource.resource_type,
        "exists": exists,
        "path": resolved_path,
        "source": source,
        "message": (
            "Resource already exists. Create flow is blocked for this resource. Ask the user to change fields/name or create another resource."
            if exists
            else "Resource does not exist at the resolved repo path. Create flow may continue."
        ),
    }

    await save_session_field(session.session_id, f"{RESOURCE_EXISTS_PREFIX}{resource.resource_id}", "true" if exists else "false")
    await save_session_field(session.session_id, f"{RESOURCE_EXISTENCE_DETAIL_PREFIX}{resource.resource_id}", json.dumps(result))
    return json.dumps(result)


async def check_update_capability(resource_type: str, **kwargs) -> str:
    """Return update capability for a resource type."""
    capability = (_load_update_capabilities().get(resource_type) or {}).copy()
    if not capability:
        capability = {
            "enabled": False,
            "reason": f"{resource_type} update flow is not configured.",
        }
    capability["resource_type"] = resource_type
    if capability.get("enabled"):
        required_inputs = capability.get("required_inputs", []) or []
        capability["next_action"] = (
            "Ask the user for all required_inputs before calling fetch_existing_resource_file. "
            "Do not invent branch or file_path."
            if required_inputs
            else "No extra update inputs are configured."
        )
    return json.dumps(capability)


async def fetch_existing_resource_file(resource_type: str, file_path: str = "", branch: str = "", resource_name: str = "", **kwargs) -> str:
    """Fetch an existing resource YAML file for update flow.

    Reads from GitHub or local mock based on config/repo_directory_map.yaml.
    GitHub mode uses the upstream repo configured in .env.
    """
    capability = _load_update_capabilities().get(resource_type, {}) or {}
    if not capability.get("enabled", False):
        return json.dumps({
            "found": False,
            "resource_type": resource_type,
            "error": capability.get("reason") or f"{resource_type} update flow is not enabled.",
        })

    normalized_path = _normalize_repo_relative_path(file_path)
    resource_name = str(resource_name or "").strip()
    branch = str(branch or "").strip()

    if not branch:
        return json.dumps({
            "found": False,
            "requires_user_input": True,
            "missing_fields": ["branch"],
            "resource_type": resource_type,
            "file_path": normalized_path,
            "message": "Target branch is required before fetching an existing resource file. Ask the user for the branch.",
        })

    if not normalized_path and not resource_name:
        return json.dumps({
            "found": False,
            "requires_user_input": True,
            "missing_fields": ["resource_name_or_file_path"],
            "resource_type": resource_type,
            "branch": branch,
            "message": "Resource name or repo-relative YAML file path is required before fetching an existing resource file. Ask the user for the S3 bucket/resource name or path.",
        })

    if not normalized_path and resource_name:
        if _repo_source() == "github":
            token = await _github_token()
            find_result = await _github_find_resource_paths_by_name(resource_type, resource_name, branch, token)
            if not find_result.get("success"):
                return json.dumps({
                    "found": False,
                    "resource_type": resource_type,
                    "branch": branch,
                    "resource_name": _normalize_resource_name(resource_name),
                    "source": "github",
                    "repo_owner": GITHUB_UPSTREAM_OWNER,
                    "repo_name": GITHUB_UPSTREAM_REPO,
                    **find_result,
                })
            github_matches = find_result.get("matches", [])
            if not github_matches:
                return json.dumps({
                    "found": False,
                    "resource_type": resource_type,
                    "branch": branch,
                    "resource_name": _normalize_resource_name(resource_name),
                    "source": "github",
                    "repo_owner": GITHUB_UPSTREAM_OWNER,
                    "repo_name": GITHUB_UPSTREAM_REPO,
                    "message": f"No {resource_type} YAML file was found in GitHub for resource name '{_normalize_resource_name(resource_name)}'. Ask for a different name or full repo-relative file path.",
                })
            if len(github_matches) > 1:
                return json.dumps({
                    "found": False,
                    "requires_user_input": True,
                    "ambiguous": True,
                    "resource_type": resource_type,
                    "branch": branch,
                    "resource_name": _normalize_resource_name(resource_name),
                    "source": "github",
                    "matches": github_matches,
                    "message": "Multiple matching YAML files were found in GitHub. Ask the user to choose one file_path.",
                })
            normalized_path = github_matches[0]
        else:
            matches = _find_resource_files_by_name(resource_type, resource_name)
            if not matches:
                return json.dumps({
                    "found": False,
                    "resource_type": resource_type,
                    "branch": branch,
                    "resource_name": _normalize_resource_name(resource_name),
                    "message": f"No {resource_type} YAML file was found for resource name '{_normalize_resource_name(resource_name)}'. Ask for a different name or full repo-relative file path.",
                })
            if len(matches) > 1:
                return json.dumps({
                    "found": False,
                    "requires_user_input": True,
                    "ambiguous": True,
                    "resource_type": resource_type,
                    "branch": branch,
                    "resource_name": _normalize_resource_name(resource_name),
                    "matches": [_path_display(path) for path in matches],
                    "message": "Multiple matching YAML files were found. Ask the user to choose one file_path.",
                })
            normalized_path = _path_display(matches[0])

    if not _is_allowed_repo_path(normalized_path):
        return json.dumps({
            "found": False,
            "requires_user_input": True,
            "invalid_fields": ["file_path"],
            "resource_type": resource_type,
            "branch": branch,
            "file_path": normalized_path,
            "allowed_path_prefixes": _allowed_path_prefixes(),
            "message": "The file path is not under a configured MIW repo resource directory. Ask the user for a repo-relative path under aws_lakehouse/.",
        })

    normalized_path = _normalize_repo_relative_path(normalized_path)

    if _repo_source() == "github":
        token = await _github_token()
        github_result = await _github_get_file(normalized_path, branch, token)
        if not github_result.get("found"):
            return json.dumps({
                "found": False,
                "resource_type": resource_type,
                "branch": branch,
                "file_path": normalized_path,
                "source": "github",
                "repo_owner": GITHUB_UPSTREAM_OWNER,
                "repo_name": GITHUB_UPSTREAM_REPO,
                **github_result,
            })

        content = github_result.get("content", "")
        session = _get_session()
        pending = {
            "resource_type": resource_type,
            "branch": branch,
            "file_path": normalized_path,
            "original_yaml": content,
            "updated_yaml": None,
            "append_only_valid": False,
            "diff": None,
            "status": "loaded",
            "source": "github",
            "sha": github_result.get("sha"),
            "html_url": github_result.get("html_url"),
        }
        await save_session_field(session.session_id, PENDING_UPDATE_KEY, json.dumps(pending))
        return json.dumps({
            "found": True,
            "resource_type": resource_type,
            "branch": branch,
            "file_path": normalized_path,
            "content": content,
            "sha": github_result.get("sha"),
            "html_url": github_result.get("html_url"),
            "source": "github",
            "repo_owner": GITHUB_UPSTREAM_OWNER,
            "repo_name": GITHUB_UPSTREAM_REPO,
            "message": "Existing resource file loaded from GitHub. Ask the user what lines or YAML block to append.",
        })

    if not normalized_path and resource_name:
        matches = _find_resource_files_by_name(resource_type, resource_name)
        if not matches:
            return json.dumps({
                "found": False,
                "resource_type": resource_type,
                "branch": branch,
                "resource_name": _normalize_resource_name(resource_name),
                "message": f"No {resource_type} YAML file was found for resource name '{_normalize_resource_name(resource_name)}'. Ask for a different name or full repo-relative file path.",
            })
        if len(matches) > 1:
            return json.dumps({
                "found": False,
                "requires_user_input": True,
                "ambiguous": True,
                "resource_type": resource_type,
                "branch": branch,
                "resource_name": _normalize_resource_name(resource_name),
                "matches": [_path_display(path) for path in matches],
                "message": "Multiple matching YAML files were found. Ask the user to choose one file_path.",
            })
        normalized_path = _path_display(matches[0])

    repo_root = _local_repo_root()
    candidates = [repo_root.joinpath(*normalized_path.split("/"))]
    if normalized_path.startswith("miw-object-provisioning/"):
        candidates.append(repo_root.joinpath(*normalized_path.removeprefix("miw-object-provisioning/").split("/")))
    if normalized_path.startswith("miw-repo/miw-object-provisioning/"):
        candidates.append(repo_root.joinpath(*normalized_path.removeprefix("miw-repo/miw-object-provisioning/").split("/")))

    existing_path = next((path for path in candidates if path.exists() and path.is_file()), None)
    if not existing_path:
        return json.dumps({
            "found": False,
            "resource_type": resource_type,
            "branch": branch,
            "file_path": normalized_path,
            "error": f"File not found: {normalized_path}",
        })

    content = existing_path.read_text(encoding="utf-8")
    session = _get_session()
    pending = {
        "resource_type": resource_type,
        "branch": branch,
        "file_path": _path_display(existing_path),
        "original_yaml": content,
        "updated_yaml": None,
        "append_only_valid": False,
        "diff": None,
        "status": "loaded",
    }
    await save_session_field(session.session_id, PENDING_UPDATE_KEY, json.dumps(pending))
    return json.dumps({
        "found": True,
        "resource_type": resource_type,
        "branch": branch,
        "file_path": pending["file_path"],
        "content": content,
        "message": "Existing resource file loaded. Ask the user what lines or YAML block to append.",
    })


def _is_append_only(original: str, updated: str) -> tuple[bool, str]:
    """Strict append-only check: updated content must start with the original content."""
    if updated == original:
        return False, "No changes were made."
    if updated.startswith(original):
        return True, "Only new content was appended."
    if updated.startswith(original.rstrip("\n") + "\n"):
        return True, "Only new content was appended."
    return False, "Existing YAML was modified or removed. Update flow only allows appending new lines."


async def validate_append_only_change(original_yaml: str, updated_yaml: str, **kwargs) -> str:
    """Validate that an update only appends content and does not alter existing YAML."""
    valid, reason = _is_append_only(original_yaml, updated_yaml)
    return json.dumps({"valid": valid, "reason": reason})


async def preview_update_diff(file_path: str, original_yaml: str, updated_yaml: str, **kwargs) -> str:
    """Return a unified diff for an update."""
    diff_lines = difflib.unified_diff(
        original_yaml.splitlines(keepends=True),
        updated_yaml.splitlines(keepends=True),
        fromfile=f"old/{file_path}",
        tofile=f"new/{file_path}",
    )
    diff = "".join(diff_lines)
    return json.dumps({
        "file_path": file_path,
        "has_changes": original_yaml != updated_yaml,
        "diff": diff,
    })


async def stage_append_only_update(file_path: str, original_yaml: str, appended_yaml: str, branch: str = "", resource_type: str = "s3", **kwargs) -> str:
    """Stage an append-only YAML update and return a diff.

    appended_yaml should contain only the new block/lines to append.
    """
    append_block = appended_yaml.rstrip("\n")
    if not append_block.strip():
        return json.dumps({"staged": False, "error": "No appended YAML content was provided."})

    updated_yaml = original_yaml.rstrip("\n") + "\n" + append_block + "\n"
    valid, reason = _is_append_only(original_yaml, updated_yaml)
    diff_result = json.loads(await preview_update_diff(file_path=file_path, original_yaml=original_yaml, updated_yaml=updated_yaml))

    session = _get_session()
    pending = {
        "resource_type": resource_type,
        "branch": branch,
        "file_path": file_path,
        "original_yaml": original_yaml,
        "updated_yaml": updated_yaml,
        "append_only_valid": valid,
        "diff": diff_result.get("diff", ""),
        "status": "ready_for_review" if valid else "invalid",
    }
    await save_session_field(session.session_id, PENDING_UPDATE_KEY, json.dumps(pending))

    return json.dumps({
        "staged": valid,
        "append_only_valid": valid,
        "reason": reason,
        "file_path": file_path,
        "updated_yaml": updated_yaml,
        "diff": diff_result.get("diff", ""),
    })


async def stage_full_updated_yaml(file_path: str, original_yaml: str, updated_yaml: str, branch: str = "", resource_type: str = "s3", **kwargs) -> str:
    """Stage a full edited YAML document only if it is append-only."""
    valid, reason = _is_append_only(original_yaml, updated_yaml)
    diff_result = json.loads(await preview_update_diff(file_path=file_path, original_yaml=original_yaml, updated_yaml=updated_yaml))

    session = _get_session()
    pending = {
        "resource_type": resource_type,
        "branch": branch,
        "file_path": file_path,
        "original_yaml": original_yaml,
        "updated_yaml": updated_yaml,
        "append_only_valid": valid,
        "diff": diff_result.get("diff", ""),
        "status": "ready_for_review" if valid else "invalid",
    }
    await save_session_field(session.session_id, PENDING_UPDATE_KEY, json.dumps(pending))

    return json.dumps({
        "staged": valid,
        "append_only_valid": valid,
        "reason": reason,
        "file_path": file_path,
        "updated_yaml": updated_yaml,
        "diff": diff_result.get("diff", ""),
    })

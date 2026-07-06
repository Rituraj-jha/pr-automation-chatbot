"""PR creation tool — fork-based workflow for GitHub Enterprise."""
from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import asyncio
import httpx
import yaml as pyyaml
from dotenv import load_dotenv

from models.state import Session, Resource, ResourceStatus
from tools.session_tools import _get_session
from tools.repo_tools import PENDING_UPDATE_KEY, resolve_resource_repo_path
from db.repository import load_github_token, load_session_fields, save_resource, save_session_field

load_dotenv()

logger = logging.getLogger(__name__)

# Config from env
GITHUB_ENTERPRISE_URL = (os.getenv("GITHUB_ENTERPRISE_URL") or "").rstrip("/")
GITHUB_API = f"{GITHUB_ENTERPRISE_URL}/api/v3" if GITHUB_ENTERPRISE_URL else "https://api.github.com"
GITHUB_UPSTREAM_OWNER = os.getenv("GITHUB_UPSTREAM_OWNER", "")
GITHUB_UPSTREAM_REPO = os.getenv("GITHUB_UPSTREAM_REPO", "")
GITHUB_UPSTREAM_BRANCH = os.getenv("GITHUB_UPSTREAM_BRANCH", "main")
CA_BUNDLE = os.getenv("CUSTOM_CA_BUNDLE_PATH") or True

# Account → folder mapping
_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
_account_map: dict | None = None


def _load_account_map() -> dict:
    """Load account_directory_map.yaml."""
    global _account_map
    if _account_map is not None:
        return _account_map
    path = _CONFIG_DIR / "account_directory_map.yaml"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            _account_map = pyyaml.safe_load(f) or {}
    else:
        _account_map = {}
    return _account_map


def _resolve_file_path(resource_type: str, fields: dict) -> str:
    """Resolve the repo file path for a resource (e.g. aws_lakehouse/lakehouse-001/s3/bucket-name.yaml)."""
    try:
        return resolve_resource_repo_path(resource_type, fields)
    except Exception:
        logger.exception("Failed to resolve file path from repo_directory_map.yaml; falling back to legacy mapping")

    mapping = _load_account_map()
    accounts = mapping.get("accounts", {})
    resource_folders = mapping.get("resource_folders", {})
    name_fields = mapping.get("resource_name_fields", {})

    account_id = str(fields.get("aws_account_id", "")).strip("'\"")
    account_info = accounts.get(account_id)

    if not account_info:
        # Fallback
        return f"configs/{resource_type}/{fields.get('intake_id', 'unknown')}.yaml"

    account_folder = account_info["folder"]
    subfolder = resource_folders.get(resource_type, resource_type)
    name_field = name_fields.get(resource_type, "")
    resource_name = fields.get(name_field, "") if name_field else ""

    if not resource_name:
        resource_name = (
            fields.get("bucket_name")
            or fields.get("database_name")
            or fields.get("role_name")
            or fields.get("intake_id", "unknown")
        )

    return f"{account_folder}/{subfolder}/{resource_name}.yaml"


# ─── PR Template & Labels ─────────────────────────────────────────────────────

_pr_template: dict | None = None
PR_INTAKE_ANSWERS_KEY = "__pr_intake_answers"
PR_LABEL_ANSWERS_KEY = "__pr_label_answers"
PR_TARGET_BRANCH_KEY = "__pr_target_branch"


def _load_pr_template() -> dict:
    """Load pr_template.yaml config."""
    global _pr_template
    if _pr_template is not None:
        return _pr_template
    path = _CONFIG_DIR / "pr_template.yaml"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            _pr_template = pyyaml.safe_load(f) or {}
    else:
        _pr_template = {}
    return _pr_template


def _active_done_resources(session: Session) -> list[Resource]:
    return [
        r for r in session.resources
        if r.status == ResourceStatus.DONE and r.yaml_output
    ]


def _resource_field_values(resources: list[Resource], field_name: str) -> list[str]:
    values = []
    seen = set()
    for resource in resources:
        value = resource.all_fields.get(field_name)
        if value is None or str(value).strip() == "":
            continue
        text = str(value).strip()
        key = text.lower()
        if key not in seen:
            seen.add(key)
            values.append(text)
    return values


def _join_values(values: list[str], default: str = "") -> str:
    return ", ".join(values) if values else default


def _resource_type_summary(resources: list[Resource]) -> str:
    counts: dict[str, int] = {}
    for resource in resources:
        counts[resource.resource_type] = counts.get(resource.resource_type, 0) + 1
    return ", ".join(
        f"{count} {rtype.replace('_', ' ')}{'s' if count != 1 else ''}"
        for rtype, count in sorted(counts.items())
    )


def _derive_objective(resources: list[Resource]) -> str:
    resource_types = _resource_type_summary(resources)
    enterprise = _join_values(_resource_field_values(resources, "enterprise_or_func_name"), "the selected enterprise")
    subgroup = _join_values(_resource_field_values(resources, "enterprise_or_func_subgrp_name"))
    plat_env = _join_values(_resource_field_values(resources, "plat_env"), "the target environment")
    owner = f"{enterprise} {subgroup}".strip()
    return f"Provision {resource_types} for {owner} in {plat_env}"


def _derive_intake_approval(resources: list[Resource]) -> str:
    intake_ids = _resource_field_values(resources, "intake_id")
    if not intake_ids:
        return ""
    return "Yes — " + ", ".join(intake_ids)


def _derive_data_flow(resources: list[Resource]) -> str:
    sources = _resource_field_values(resources, "source_name")
    layers = _resource_field_values(resources, "data_layer")
    data_envs = _resource_field_values(resources, "data_env")
    constructs = _resource_field_values(resources, "data_construct")
    left = _join_values(sources, "source data")
    right_parts = []
    if layers:
        right_parts.append(_join_values(layers))
    if constructs:
        right_parts.append(_join_values(constructs))
    right = " / ".join(right_parts) if right_parts else "target data platform resources"
    suffix = f" ({_join_values(data_envs)})" if data_envs else ""
    return f"{left} → {right}{suffix}"


def _label_answer_field(label_def: dict) -> str:
    return label_def.get("prefix") or label_def.get("name", "")


def _question_auto_fill(question: dict, resources: list[Resource], session_fields: dict[str, str]) -> str | None:
    auto_fill = question.get("auto_fill")
    if not auto_fill:
        if question.get("default") is not None:
            return str(question.get("default"))
        return None

    strategy = auto_fill.get("strategy")
    if strategy == "derive_from_resources":
        if question.get("id") == "objective":
            return _derive_objective(resources)
    if strategy == "from_session_field":
        field = auto_fill.get("field", "")
        if field and session_fields.get(field):
            return session_fields.get(field)
        if field == "intake_id":
            return _derive_intake_approval(resources)
    return None


async def _load_pr_answers(session: Session) -> tuple[dict[str, str], dict[str, str], str, dict[str, str]]:
    session_fields = await load_session_fields(session.session_id)
    try:
        intake_answers = json.loads(session_fields.get(PR_INTAKE_ANSWERS_KEY, "{}") or "{}")
    except json.JSONDecodeError:
        intake_answers = {}
    try:
        label_answers = json.loads(session_fields.get(PR_LABEL_ANSWERS_KEY, "{}") or "{}")
    except json.JSONDecodeError:
        label_answers = {}
    target_branch = str(session_fields.get(PR_TARGET_BRANCH_KEY, "") or "").strip()
    return intake_answers, label_answers, target_branch, session_fields


async def _save_pr_answers(
    session: Session,
    intake_answers: dict[str, str],
    label_answers: dict[str, str],
    target_branch: str,
) -> None:
    await save_session_field(session.session_id, PR_INTAKE_ANSWERS_KEY, json.dumps(intake_answers))
    await save_session_field(session.session_id, PR_LABEL_ANSWERS_KEY, json.dumps(label_answers))
    if target_branch:
        await save_session_field(session.session_id, PR_TARGET_BRANCH_KEY, target_branch)


async def _build_pr_intake_status(session: Session, target_branch: str = "") -> dict[str, Any]:
    template = _load_pr_template()
    resources = _active_done_resources(session)
    if not resources:
        return {
            "ready": False,
            "error": "No completed resources to submit. Generate and review YAML first.",
        }

    intake_answers, label_answers, saved_branch, session_fields = await _load_pr_answers(session)
    branch = target_branch.strip() or saved_branch
    auto_filled: dict[str, str] = {}

    # Auto-fill deterministic/safe PR-intake answers from resource/session state.
    for question in template.get("intake_questions", []):
        qid = question.get("id")
        if not qid:
            continue
        if intake_answers.get(qid):
            continue
        derived = _question_auto_fill(question, resources, session_fields)
        if derived:
            intake_answers[qid] = derived
            auto_filled[qid] = derived

    # Apply optional defaults.
    for question in template.get("intake_questions", []):
        qid = question.get("id")
        if qid and not intake_answers.get(qid) and question.get("default") is not None:
            intake_answers[qid] = str(question.get("default"))
            auto_filled[qid] = str(question.get("default"))

    # Reuse session-level answers for ask labels such as Wave.
    for label_def in template.get("labels", []):
        if label_def.get("derive") or label_def.get("static"):
            continue
        field = _label_answer_field(label_def)
        if not field or label_answers.get(field):
            continue
        reuse_value = session_fields.get(f"__pr_label:{field}")
        if reuse_value:
            label_answers[field] = reuse_value

    await _save_pr_answers(session, intake_answers, label_answers, branch)

    missing_intake_questions = []
    for question in template.get("intake_questions", []):
        qid = question.get("id")
        if question.get("required", False) and qid and not str(intake_answers.get(qid, "")).strip():
            missing_intake_questions.append({
                "id": qid,
                "question": question.get("question", qid),
                "options": question.get("options"),
                "example": question.get("example"),
            })

    missing_labels = []
    for label_def in template.get("labels", []):
        if label_def.get("derive") or label_def.get("static"):
            continue
        field = _label_answer_field(label_def)
        if label_def.get("required", False) and field and not str(label_answers.get(field, "")).strip():
            missing_labels.append({
                "field": field,
                "question": label_def.get("ask", field),
                "options": label_def.get("values"),
            })

    missing = {
        "intake_questions": missing_intake_questions,
        "labels": missing_labels,
        "target_branch": not bool(branch),
    }
    labels_preview = _derive_labels(
        [{"fields": r.all_fields} for r in resources],
        intake_answers,
        label_answers,
    )
    return {
        "ready": not missing_intake_questions and not missing_labels and bool(branch),
        "auto_filled": auto_filled,
        "intake_answers": intake_answers,
        "label_answers": label_answers,
        "target_branch": branch,
        "missing": missing,
        "labels_preview": labels_preview,
        "instruction": "Ask the user only for missing items. Do not call create_pr until ready is true.",
    }


def _derive_labels(
    resources: list[dict],
    intake_answers: dict | None = None,
    label_answers: dict | None = None,
) -> list[str]:
    """Derive PR labels from resource fields and intake answers.

    Returns list of label strings like ["ENV:prd", "Enterprise/Function:AGTR-APAC", "CREATED_BY:MiNi"].
    """
    template = _load_pr_template()
    label_defs = template.get("labels", [])
    labels: list[str] = []

    # Collect field values from all resources for derivation.
    all_field_values: dict[str, set[str]] = {}

    for r in resources:
        fields = r.get("fields", {})
        for field_name, value in fields.items():
            if value is None or str(value).strip() == "":
                continue
            all_field_values.setdefault(field_name, set()).add(str(value).strip())

    for label_def in label_defs:
        # Static labels (always applied)
        if label_def.get("static"):
            labels.append(label_def["name"])
            continue

        prefix = label_def.get("prefix", "")
        if not prefix:
            continue

        if not label_def.get("derive"):
            answer = (label_answers or {}).get(prefix)
            if answer:
                labels.append(f"{prefix}:{answer}")
            continue

        # Derive from resource fields
        derive = label_def.get("derive")
        if derive and derive.get("strategy") == "from_resource_field":
            field = derive.get("field", "")
            values = all_field_values.get(field, set())
            if label_def.get("skip_if_empty") and not values:
                continue
            for val in sorted(values):
                labels.append(f"{prefix}:{val}")
        elif derive and derive.get("strategy") == "combine_resource_fields":
            fields_to_combine = derive.get("fields", []) or []
            separator = str(derive.get("separator", "-"))
            skip_empty_parts = bool(derive.get("skip_empty_parts", True))
            combined_values = set()
            for resource in resources:
                resource_fields = resource.get("fields", {})
                parts = []
                for field in fields_to_combine:
                    value = str(resource_fields.get(field, "") or "").strip()
                    if not value and skip_empty_parts:
                        continue
                    parts.append(value)
                combined = separator.join(part for part in parts if part or not skip_empty_parts).strip(separator)
                if combined:
                    combined_values.add(combined)
            for val in sorted(combined_values):
                labels.append(f"{prefix}:{val}")

    return labels


async def prepare_pr_intake(target_branch: str = "", **kwargs) -> str:
    """Prepare PR template answers and return missing required PR metadata."""
    session = _get_session()
    status = await _build_pr_intake_status(session, target_branch=target_branch)
    return json.dumps(status, indent=2)


async def set_pr_intake_answers(
    intake_answers: dict | None = None,
    label_answers: dict | None = None,
    target_branch: str = "",
    **kwargs,
) -> str:
    """Store and validate PR template answers before PR creation."""
    session = _get_session()
    template = _load_pr_template()
    existing_intake, existing_labels, saved_branch, _ = await _load_pr_answers(session)
    next_intake = dict(existing_intake)
    next_labels = dict(existing_labels)

    valid_question_ids = {
        question.get("id") for question in template.get("intake_questions", []) if question.get("id")
    }
    question_options = {
        question.get("id"): question.get("options")
        for question in template.get("intake_questions", [])
        if question.get("id") and question.get("options")
    }
    field_errors: dict[str, str] = {}

    for key, value in (intake_answers or {}).items():
        if key not in valid_question_ids:
            field_errors[key] = "Unknown PR intake question."
            continue
        text = str(value).strip()
        options = question_options.get(key)
        if options and text not in options:
            lower_map = {str(option).lower(): str(option) for option in options}
            mapped = lower_map.get(text.lower())
            if mapped:
                text = mapped
            else:
                field_errors[key] = f"Must be one of: {options}"
                continue
        next_intake[key] = text

    label_defs = [
        label_def for label_def in template.get("labels", [])
        if not label_def.get("derive") and not label_def.get("static")
    ]
    label_options = {
        _label_answer_field(label_def): label_def.get("values")
        for label_def in label_defs
        if _label_answer_field(label_def) and label_def.get("values")
    }
    valid_label_fields = {_label_answer_field(label_def) for label_def in label_defs if _label_answer_field(label_def)}
    for key, value in (label_answers or {}).items():
        if key not in valid_label_fields:
            field_errors[key] = "Unknown PR label field."
            continue
        text = str(value).strip()
        options = label_options.get(key)
        if options and text not in options:
            lower_map = {str(option).lower(): str(option) for option in options}
            mapped = lower_map.get(text.lower())
            if mapped:
                text = mapped
            else:
                field_errors[key] = f"Must be one of: {options}"
                continue
        next_labels[key] = text
        await save_session_field(session.session_id, f"__pr_label:{key}", text)

    branch = str(target_branch or saved_branch or "").strip()
    await _save_pr_answers(session, next_intake, next_labels, branch)
    status = await _build_pr_intake_status(session, target_branch=branch)
    if field_errors:
        status["valid"] = False
        status["field_errors"] = field_errors
        status["ready"] = False
    else:
        status["valid"] = True
    return json.dumps(status, indent=2)


def _format_pr_body(resources: list[dict], intake_answers: dict | None = None, labels: list[str] | None = None) -> str:
    """Format PR body using pr_template.yaml body_template.

    Falls back to basic format if template not available.
    """
    template = _load_pr_template()
    body_template = template.get("body_template", "")

    if not body_template or not intake_answers:
        # Fallback to basic format
        parts = ["## Infrastructure Configuration\n"]
        for r in resources:
            parts.append(f"### {r.get('resource_type', '').upper()} — {r.get('resource_name', '')}")
            parts.append(f"- **Intake ID:** {r.get('intake_id', 'N/A')}")
            parts.append(f"- **File:** `{r['file_path']}`")
            parts.append(f"\n```yaml\n{r['yaml_content']}\n```\n")
        parts.append("---\n_This PR was automatically generated by MiNi._")
        return "\n".join(parts)

    # Build resource summary
    resource_summary_parts = []
    for r in resources:
        resource_summary_parts.append(
            f"- **{r.get('resource_type', '').upper()}** `{r.get('resource_name', '')}` "
            f"→ `{r['file_path']}`"
        )
    resource_summary = "\n".join(resource_summary_parts)

    # Build labels list
    labels_list = ", ".join(f"`{l}`" for l in (labels or []))

    # Substitute placeholders
    body = body_template
    body = body.replace("{resource_summary}", resource_summary)
    body = body.replace("{labels_list}", labels_list)

    # Substitute intake answers
    for key, value in (intake_answers or {}).items():
        body = body.replace(f"{{intake_answers.{key}}}", str(value))

    # Clean up any remaining unreplaced placeholders
    import re
    body = re.sub(r"\{intake_answers\.\w+\}", "N/A", body)

    return body


def _format_pr_title(resources: list[dict]) -> str:
    """Format PR title using pr_template.yaml title_template."""
    template = _load_pr_template()
    title_template = template.get("title_template", "")

    # Gather values
    resource_types = ", ".join(sorted({r.get("resource_type", "").upper() for r in resources}))
    enterprises = ", ".join(sorted({r.get("fields", {}).get("enterprise_or_func_name", "") for r in resources if r.get("fields", {}).get("enterprise_or_func_name")}))
    plat_envs = ", ".join(sorted({r.get("fields", {}).get("plat_env", "") for r in resources if r.get("fields", {}).get("plat_env")}))
    intake_ids = ", ".join(sorted({r.get("intake_id", "") for r in resources if r.get("intake_id")}))

    if title_template:
        title = title_template
        title = title.replace("{resource_types}", resource_types)
        title = title.replace("{enterprise}", enterprises)
        title = title.replace("{plat_env}", plat_envs)
        title = title.replace("{intake_id}", intake_ids)
        return title

    # Fallback
    return f"[MiNi] {resource_types} — {intake_ids}"


def _apply_labels_sync(client: "httpx.Client", pr_number: int, labels: list[str]) -> bool:
    """Apply labels to a PR via GitHub API. Returns True on success."""
    if not labels:
        return True
    try:
        resp = client.post(
            f"{GITHUB_API}/repos/{GITHUB_UPSTREAM_OWNER}/{GITHUB_UPSTREAM_REPO}/issues/{pr_number}/labels",
            json={"labels": labels},
        )
        return resp.status_code in (200, 201)
    except Exception:
        logger.warning(f"Failed to apply labels to PR #{pr_number}")
        return False


def _create_pr_sync(
    token: str,
    username: str,
    resources: list[dict],
    target_branch: str = "",
    intake_answers: dict | None = None,
    label_answers: dict | None = None,
) -> dict:
    """
    Synchronous PR creation flow using GitHub REST API (httpx).
    Steps: fork → sync → branch → commit files → PR.
    """
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    with httpx.Client(headers=headers, verify=CA_BUNDLE, timeout=30) as client:
        # 1. Get or create fork
        fork_full = f"{username}/{GITHUB_UPSTREAM_REPO}"
        resp = client.get(f"{GITHUB_API}/repos/{fork_full}")
        if resp.status_code == 404:
            # Create fork
            resp = client.post(
                f"{GITHUB_API}/repos/{GITHUB_UPSTREAM_OWNER}/{GITHUB_UPSTREAM_REPO}/forks",
                json={},
            )
            if resp.status_code not in (200, 201, 202):
                return {"success": False, "error": f"Fork creation failed: {resp.text}"}
            # Wait for fork to be ready
            for _ in range(10):
                time.sleep(2)
                check = client.get(f"{GITHUB_API}/repos/{fork_full}")
                if check.status_code == 200:
                    break
            else:
                return {"success": False, "error": "Fork creation timed out"}

        # 2. Use user-specified branch or fall back to upstream default
        branch_name = target_branch or GITHUB_UPSTREAM_BRANCH

        # 3. Sync fork with upstream for this branch
        client.post(
            f"{GITHUB_API}/repos/{fork_full}/merge-upstream",
            json={"branch": branch_name},
        )

        # 4. Get branch SHA (create branch in fork if it doesn't exist)
        resp = client.get(
            f"{GITHUB_API}/repos/{fork_full}/git/ref/heads/{branch_name}"
        )
        if resp.status_code == 200:
            base_sha = resp.json()["object"]["sha"]
        else:
            # Branch doesn't exist in fork — get upstream branch SHA and create it
            upstream_ref = client.get(
                f"{GITHUB_API}/repos/{GITHUB_UPSTREAM_OWNER}/{GITHUB_UPSTREAM_REPO}/git/ref/heads/{branch_name}"
            )
            if upstream_ref.status_code != 200:
                return {"success": False, "error": f"Branch '{branch_name}' not found in upstream repo."}
            base_sha = upstream_ref.json()["object"]["sha"]
            create_ref = client.post(
                f"{GITHUB_API}/repos/{fork_full}/git/refs",
                json={"ref": f"refs/heads/{branch_name}", "sha": base_sha},
            )
            if create_ref.status_code not in (200, 201):
                return {"success": False, "error": f"Failed to create branch '{branch_name}' in fork: {create_ref.text}"}

        # 5. Commit files (one commit with tree API for batch)
        # Get base tree
        resp = client.get(f"{GITHUB_API}/repos/{fork_full}/git/commits/{base_sha}")
        base_tree_sha = resp.json()["tree"]["sha"]

        tree_entries = []
        file_paths = []
        for r in resources:
            path = r["file_path"]
            file_paths.append(path)
            # Create blob
            blob_resp = client.post(
                f"{GITHUB_API}/repos/{fork_full}/git/blobs",
                json={"content": r["yaml_content"], "encoding": "utf-8"},
            )
            if blob_resp.status_code not in (200, 201):
                return {"success": False, "error": f"Blob creation failed for {path}: {blob_resp.text}"}
            tree_entries.append({
                "path": path,
                "mode": "100644",
                "type": "blob",
                "sha": blob_resp.json()["sha"],
            })

        # Create tree
        tree_resp = client.post(
            f"{GITHUB_API}/repos/{fork_full}/git/trees",
            json={"base_tree": base_tree_sha, "tree": tree_entries},
        )
        if tree_resp.status_code not in (200, 201):
            return {"success": False, "error": f"Tree creation failed: {tree_resp.text}"}
        new_tree_sha = tree_resp.json()["sha"]

        # Create commit
        commit_msg = f"feat: add {len(resources)} resource config{'s' if len(resources) != 1 else ''}"
        commit_resp = client.post(
            f"{GITHUB_API}/repos/{fork_full}/git/commits",
            json={
                "message": commit_msg,
                "tree": new_tree_sha,
                "parents": [base_sha],
            },
        )
        if commit_resp.status_code not in (200, 201):
            return {"success": False, "error": f"Commit failed: {commit_resp.text}"}
        new_commit_sha = commit_resp.json()["sha"]

        # Update branch ref
        client.patch(
            f"{GITHUB_API}/repos/{fork_full}/git/refs/heads/{branch_name}",
            json={"sha": new_commit_sha},
        )

        # 6. Create PR (from fork:branch → upstream:branch)
        pr_title = _format_pr_title(resources)
        labels = _derive_labels(resources, intake_answers, label_answers)
        pr_body = _format_pr_body(resources, intake_answers, labels)

        pr_resp = client.post(
            f"{GITHUB_API}/repos/{GITHUB_UPSTREAM_OWNER}/{GITHUB_UPSTREAM_REPO}/pulls",
            json={
                "title": pr_title,
                "body": pr_body,
                "head": f"{username}:{branch_name}",
                "base": branch_name,
            },
        )
        if pr_resp.status_code not in (200, 201):
            return {"success": False, "error": f"PR creation failed: {pr_resp.text}"}

        pr_data = pr_resp.json()
        pr_number = pr_data.get("number")

        # 7. Apply labels
        if pr_number and labels:
            _apply_labels_sync(client, pr_number, labels)

        return {
            "success": True,
            "pr_url": pr_data.get("html_url"),
            "pr_number": pr_number,
            "branch_name": branch_name,
            "files_committed": file_paths,
            "title": pr_title,
            "labels": labels,
        }


async def create_pr(**kwargs) -> str:
    """
    Create a PR with all DONE resources in the current session.
    Uses the authenticated user's GitHub token from the DB.
    """
    target_branch = kwargs.get("target_branch", "").strip()
    session = _get_session()

    # Find all DONE resources with YAML
    done_resources = _active_done_resources(session)

    if not done_resources:
        return json.dumps({"error": "No completed resources to submit. Generate YAML first."})

    pr_status = await _build_pr_intake_status(session, target_branch=target_branch)
    if not pr_status.get("ready"):
        return json.dumps({
            "error": "PR intake is incomplete. Cannot create PR yet.",
            "missing": pr_status.get("missing"),
            "auto_filled": pr_status.get("auto_filled"),
            "intake_answers": pr_status.get("intake_answers"),
            "label_answers": pr_status.get("label_answers"),
            "labels_preview": pr_status.get("labels_preview"),
            "next_action": "Ask the user for the missing PR intake answers/labels/target branch, then call set_pr_intake_answers. Call create_pr only after ready is true.",
        }, indent=2)

    intake_answers = pr_status.get("intake_answers", {})
    label_answers = pr_status.get("label_answers", {})
    target_branch = pr_status.get("target_branch", target_branch)

    session_fields = await load_session_fields(session.session_id)
    existing_conflicts = []
    unknown_existence = []
    for resource in done_resources:
        existence_value = session_fields.get(f"__resource_exists:{resource.resource_id}")
        if existence_value in {"true", "unknown"}:
            detail = {}
            detail_raw = session_fields.get(f"__resource_existence_detail:{resource.resource_id}")
            if detail_raw:
                try:
                    detail = json.loads(detail_raw)
                except json.JSONDecodeError:
                    detail = {}
            conflict_entry = {
                "resource_id": resource.resource_id,
                "resource_type": resource.resource_type,
                "path": detail.get("path"),
                "action_needed": detail.get("action_needed"),
            }
            if existence_value == "unknown":
                unknown_existence.append(conflict_entry)
            else:
                existing_conflicts.append(conflict_entry)

    if unknown_existence:
        return json.dumps({
            "error": "Cannot create PR because repository existence could not be verified for one or more resources.",
            "conflicts": unknown_existence,
            "next_action": "Authenticate/configure GitHub repository access, then re-check whether these resources exist.",
        })

    if existing_conflicts:
        return json.dumps({
            "error": "Cannot create PR because one or more resources already exist in the repository.",
            "conflicts": existing_conflicts,
            "next_action": "Stay in create mode and change the fields/name that derive the resource name, or create another resource. This flow will not switch to update automatically.",
        })

    # Get user's GitHub token
    token = await load_github_token(session.user_id)
    if not token:
        return json.dumps({
            "error": "GitHub token not found. Please re-authenticate via GitHub OAuth.",
            "action_needed": "re_auth",
        })

    # Build resource entries for the PR
    pr_resources = []
    for r in done_resources:
        fields = r.all_fields
        file_path = _resolve_file_path(r.resource_type, fields)
        resource_name = (
            fields.get("bucket_name")
            or fields.get("database_name")
            or fields.get("role_name")
            or r.resource_id
        )
        pr_resources.append({
            "resource_type": r.resource_type,
            "resource_name": resource_name,
            "intake_id": fields.get("intake_id", ""),
            "file_path": file_path,
            "yaml_content": r.yaml_output,
            "fields": fields,  # Pass all fields for label derivation
        })

    # Run the sync GitHub operations in a thread pool
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as pool:
        result = await loop.run_in_executor(
            pool,
            _create_pr_sync,
            token,
            session.user_id,
            pr_resources,
            target_branch,
            intake_answers,
            label_answers,
        )

    return json.dumps(result)


async def create_update_pr(**kwargs) -> str:
    """Create a PR for the staged append-only update in the current session."""
    target_branch = kwargs.get("target_branch", "").strip()
    session = _get_session()
    session_fields = await load_session_fields(session.session_id)
    pending_raw = session_fields.get(PENDING_UPDATE_KEY)

    if not pending_raw:
        return json.dumps({"error": "No staged update found. Fetch and stage an append-only update first."})

    try:
        pending = json.loads(pending_raw)
    except json.JSONDecodeError:
        return json.dumps({"error": "Staged update state is invalid. Please stage the update again."})

    if not pending.get("append_only_valid"):
        return json.dumps({
            "error": "Cannot create update PR because append-only validation has not passed.",
            "next_action": "Stage an update that only appends new YAML lines and does not modify existing content.",
        })

    updated_yaml = pending.get("updated_yaml")
    file_path = pending.get("file_path")
    resource_type = pending.get("resource_type", "resource")
    if not updated_yaml or not file_path:
        return json.dumps({"error": "Staged update is missing file path or updated YAML."})

    if not target_branch:
        target_branch = str(pending.get("branch") or "").strip()
    if not target_branch:
        return json.dumps({"error": "Please specify which branch to push to (e.g. 'main', 'dev')."})

    token = await load_github_token(session.user_id)
    if not token:
        return json.dumps({
            "error": "GitHub token not found. Please re-authenticate via GitHub OAuth.",
            "action_needed": "re_auth",
        })

    pr_resources = [{
        "resource_type": resource_type,
        "resource_name": Path(file_path).stem,
        "intake_id": "",
        "file_path": file_path,
        "yaml_content": updated_yaml,
        "fields": {},
    }]

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as pool:
        result = await loop.run_in_executor(
            pool,
            _create_pr_sync,
            token,
            session.user_id,
            pr_resources,
            target_branch,
        )

    return json.dumps(result)
